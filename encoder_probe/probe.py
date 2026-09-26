#!/usr/bin/env python
"""Where does image information get lost? Linear probes on Qwen3-VL-4B vision features vs asking the model.

If a linear classifier on frozen vision features reads a symbol that the model itself gets wrong, the information
is in the encoder and the bottleneck is decoding (LLM side). If the probe also fails, the encoder loses it.
Tasks mirror diagnosed failures: sheet-music reading (synthetic, exact labels) and histology tissue type.

python encoder_probe/probe.py data                 # render music tasks + fetch histology -> encoder_probe/data/
python encoder_probe/probe.py features --device cpu  # vision features per layer -> encoder_probe/data/<task>.npz
python encoder_probe/probe.py ask                  # same test items asked to the model (vLLM, greedy) -> ask.jsonl
python encoder_probe/probe.py fit                  # probe accuracy per layer + model accuracy -> encoder_probe/results.md
Runs in the `vllm-train` env (verovio, cairosvg, scikit-learn added there).
"""
import io, json, random, sys
from pathlib import Path

import numpy as np

MODEL, MODEL_REV = "Qwen/Qwen3-VL-4B-Instruct", "ebb281ec70b05090aa6165b016eac8ec08e71b17"
HISTO, HISTO_REV = "owkin/nct-crc-he", "efccf16ed2897a8d2de035f8c68c48ff1f38bf82"
PIXELS = dict(min_pixels=4 * 32 * 32, max_pixels=1280 * 32 * 32)  # same image budget as run_eval.py
D = Path(__file__).parent / "data"
DIRECT = "Answer with the option's letter from the given choices directly."  # MMMU official direct prompt

PITCHES = "C D E F G A B c d e f g a".split()  # ABC octave 4..5 = C4..A5
PITCH_NAMES = [p.upper() + ("4" if p.isupper() else "5") for p in PITCHES]
RANGE = {"treble": PITCHES, "bass": "E,, F,, G,, A,, B,, C, D, E, F, G, A, B, C".split(),
         "alto": "D, E, F, G, A, B, C D E F G A B".split()}
KEYS = {"C": "no sharps or flats", "G": "1 sharp", "D": "2 sharps", "A": "3 sharps", "E": "4 sharps", "B": "5 sharps",
        "F#": "6 sharps", "F": "1 flat", "Bb": "2 flats", "Eb": "3 flats", "Ab": "4 flats", "Db": "5 flats", "Gb": "6 flats"}
TIMES = ["2/4", "3/4", "4/4", "6/8", "3/8", "2/2"]
TASKS = {  # task -> (question, class names)
    "clef": ("Which clef appears at the beginning of this staff?", ["treble clef", "bass clef", "alto clef"]),
    "keysig": ("How many sharps or flats are in the key signature?", list(KEYS.values())),
    "timesig": ("What is the time signature?", TIMES),
    "pitch": ("What is the pitch of the note?", PITCH_NAMES),
    "histo": ("Which tissue type is shown in this H&E-stained image patch?",
              ["adipose tissue", "background (no tissue)", "debris/necrosis", "lymphocytes", "mucus",
               "smooth muscle", "normal colon mucosa", "cancer-associated stroma", "colorectal adenocarcinoma epithelium"]),
}


def abc_tune(rng, clef, key, time, notes=None):
    if notes is None:  # two measures of random notes that fill the meter (unit = eighth note)
        num, den = map(int, time.split("/"))
        body = []
        for _ in range(2):
            left, bar = num * 8 // den, []
            while left:
                d = rng.choice([x for x in (1, 2, 4) if x <= left])
                bar.append(rng.choice(RANGE[clef]) + (str(d) if d > 1 else ""))
                left -= d
            body.append(" ".join(bar))
        notes = " | ".join(body) + " |]"
        return f"X:1\nM:{time}\nL:1/8\nK:{key} clef={clef}\n{notes}\n"
    return f"X:1\nM:{time}\nL:1/1\nK:{key} clef={clef}\n{notes}\n"


def render(tk, abc, size=(640, 160)):
    from PIL import Image, ImageOps
    import cairosvg
    tk.loadData(abc)
    png = cairosvg.svg2png(bytestring=tk.renderToSVG(1).encode(), background_color="white", output_width=1400)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    img = img.crop(ImageOps.invert(img.convert("L")).getbbox())
    img.thumbnail((size[0] - 20, size[1] - 20))
    canvas = Image.new("RGB", size, "white")
    canvas.paste(img, (10, (size[1] - img.height) // 2))
    return canvas


def make_data(n_per_task=600, n_train=450, seed=0):
    import verovio
    from datasets import load_dataset
    rng = random.Random(seed)
    tk = verovio.toolkit()
    tk.setOptions({"scale": 60, "pageWidth": 3000, "adjustPageHeight": True, "adjustPageWidth": True,
                   "header": "none", "footer": "none"})
    items = []
    for task in ["clef", "keysig", "timesig", "pitch"]:
        (D / task).mkdir(parents=True, exist_ok=True)
        n_cls = len(TASKS[task][1])
        for i in range(n_per_task):
            y = i % n_cls  # balanced classes
            clef, key, time = rng.choice(list(RANGE)), rng.choice(list(KEYS)), rng.choice(TIMES)
            if task == "clef":
                clef = list(RANGE)[y]
            elif task == "keysig":
                clef, key = "treble", list(KEYS)[y]
            elif task == "timesig":
                clef, time = "treble", TIMES[y]
            abc = abc_tune(rng, clef, key, time) if task != "pitch" else abc_tune(rng, "treble", "C", "4/4", PITCHES[y] + " |]")
            f = D / task / f"{i}.png"
            render(tk, abc).save(f)
            items.append({"task": task, "file": str(f.relative_to(D)), "label": y, "abc": abc})
    rng.shuffle(items)
    for task in ["clef", "keysig", "timesig", "pitch"]:  # split after shuffling, per task
        for j, it in enumerate([it for it in items if it["task"] == task]):
            it["split"] = "train" if j < n_train else "test"
    (D / "histo").mkdir(parents=True, exist_ok=True)
    tr = load_dataset(HISTO, split="nct_crc_he_1k", revision=HISTO_REV)  # NCT-CRC-HE-100K subset
    va = load_dataset(HISTO, split="crc_val_he_7k", revision=HISTO_REV)  # different patients -> test
    for i, r in enumerate(tr):
        r["image"].convert("RGB").save(D / "histo" / f"train_{i}.png")
        items.append({"task": "histo", "split": "train", "file": f"histo/train_{i}.png", "label": r["label"]})
    by = {}
    for i, y in enumerate(va["label"]):
        by.setdefault(y, []).append(i)
    for y, idx in sorted(by.items()):
        for i in random.Random(seed).sample(idx, 33):
            va[i]["image"].convert("RGB").save(D / "histo" / f"test_{i}.png")
            items.append({"task": "histo", "split": "test", "file": f"histo/test_{i}.png", "label": y})
    (D / "items.jsonl").write_text("".join(json.dumps(it) + "\n" for it in items))
    print({t: sum(it["task"] == t for it in items) for t in TASKS})


def pooled(tokens, grid, rows):
    """tokens: (h/2*w/2, D) merged-grid order -> global mean (+ per-row means, keeps vertical position)."""
    _, h, w = grid
    g = tokens.reshape(h // 2, w // 2, -1)
    out = [g.mean((0, 1))]
    if rows:
        out.append(g.mean(1).reshape(-1))
    return np.concatenate(out)


def features(device="cpu", bs=8):
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor
    from PIL import Image
    proc = AutoProcessor.from_pretrained(MODEL, revision=MODEL_REV, **PIXELS)
    model = AutoModelForImageTextToText.from_pretrained(MODEL, revision=MODEL_REV, dtype=torch.bfloat16)
    vis = model.model.visual.to(device, torch.float32 if device == "cpu" else torch.bfloat16).eval()
    del model
    items = [json.loads(l) for l in open(D / "items.jsonl")]
    for task in TASKS:
        its = [it for it in items if it["task"] == task]
        feats = {k: [] for k in ["vit_L5", "vit_L11", "vit_L17", "vit_last", "merger_out"]}
        for i in range(0, len(its), bs):
            imgs = [Image.open(D / it["file"]).convert("RGB") for it in its[i:i + bs]]
            enc = proc.image_processor(images=imgs, return_tensors="pt")
            with torch.no_grad():
                out = vis(enc["pixel_values"].to(device, vis.dtype), grid_thw=enc["image_grid_thw"].to(device))
            n = (enc["image_grid_thw"].prod(-1) // 4).tolist()
            reps = {"vit_L5": out.deepstack_features[0], "vit_L11": out.deepstack_features[1],
                    "vit_L17": out.deepstack_features[2], "merger_out": out.pooler_output,
                    "vit_last": out.last_hidden_state.reshape(-1, 4, out.last_hidden_state.shape[-1]).mean(1)}
            for k, v in reps.items():
                for tok, grid in zip(torch.split(v.float().cpu(), n), enc["image_grid_thw"].tolist()):
                    feats[k].append(pooled(tok.numpy(), grid, rows=task != "histo"))
            print(f"{task} {min(i + bs, len(its))}/{len(its)}", flush=True)
        np.savez(D / f"{task}.npz", y=np.array([it["label"] for it in its]),
                 split=np.array([it["split"] for it in its]), **{k: np.stack(v) for k, v in feats.items()})


def ask():
    import os
    os.environ.setdefault("VLLM_BATCH_INVARIANT", "1")
    from transformers import AutoProcessor
    from vllm import LLM, SamplingParams
    from PIL import Image
    proc = AutoProcessor.from_pretrained(MODEL, revision=MODEL_REV, **PIXELS)
    items = [json.loads(l) for l in open(D / "items.jsonl") if json.loads(l)["split"] == "test"]
    prompts = []
    for it in items:
        q, names = TASKS[it["task"]]
        text = q + "\n" + "".join(f"({chr(65 + j)}) {c}\n" for j, c in enumerate(names)) + DIRECT
        chat = proc.apply_chat_template([{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": text}]}],
                                        add_generation_prompt=True, tokenize=False)
        prompts.append({"prompt": chat, "multi_modal_data": {"image": [Image.open(D / it["file"]).convert("RGB")]}})
    llm = LLM(model=MODEL, revision=MODEL_REV, max_model_len=4096, gpu_memory_utilization=0.90,
              limit_mm_per_prompt={"image": 1}, mm_processor_kwargs=PIXELS, seed=0)
    outs = llm.generate(prompts, SamplingParams(temperature=0, max_tokens=4))
    with open(D / "ask.jsonl", "w") as f:
        for it, o in zip(items, outs):
            t = o.outputs[0].text.strip().lstrip("(")
            pred = ord(t[0].upper()) - 65 if t and t[0].isalpha() else -1
            f.write(json.dumps({**it, "response": o.outputs[0].text, "pred": pred, "correct": pred == it["label"]}) + "\n")


def fit():
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GridSearchCV
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    asked = [json.loads(l) for l in open(D / "ask.jsonl")] if (D / "ask.jsonl").exists() else []
    layers = ["vit_L5", "vit_L11", "vit_L17", "vit_last", "merger_out"]
    lines = ["| task | classes | chance | " + " | ".join(f"probe {l}" for l in layers) + " | model asked directly |",
             "|---|---|---|" + "---|" * (len(layers) + 1)]
    for task, (_, names) in TASKS.items():
        z = np.load(D / f"{task}.npz")
        tr, te = z["split"] == "train", z["split"] == "test"
        accs = []
        for l in layers:
            clf = GridSearchCV(make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)),
                               {"logisticregression__C": [0.001, 0.01, 0.1, 1.0]}, cv=3)
            clf.fit(z[l][tr], z["y"][tr])
            accs.append(100 * clf.score(z[l][te], z["y"][te]))
        a = [x["correct"] for x in asked if x["task"] == task]
        asked_s = f"{100 * np.mean(a):.1f} (n={len(a)})" if a else "—"
        lines.append(f"| {task} | {len(names)} | {100 / len(names):.1f} | " + " | ".join(f"{x:.1f}" for x in accs)
                     + f" | {asked_s} |")
        print(lines[-1], flush=True)
    (Path(__file__).parent / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "data":
        make_data()
    elif cmd == "features":
        features(sys.argv[sys.argv.index("--device") + 1] if "--device" in sys.argv else "cuda")
    elif cmd == "ask":
        ask()
    elif cmd == "fit":
        fit()

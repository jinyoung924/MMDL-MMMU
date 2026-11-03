#!/usr/bin/env python
"""LoRA SFT of Qwen3-VL-4B-Instruct on one or more record files (data_ablation/common.py format).

python data_ablation/train_sft.py --data runs/abl_cosyn/data/sft.jsonl --out runs/abl_cosyn/train
python data_ablation/train_sft.py --merge runs/abl_cosyn/train/step1500 [--merged-dir /content/merged/abl_cosyn]

Generalised from pilot_forgetting/train_sft.py (same LoRA targets, optimiser, masking) with three changes:
  * data comes from jsonl records (prompt / response / images) instead of a hard-coded dataset
  * the prompt is the evaluation's own CoT wording (built in prepare_data.py) and the loss covers the whole
    response = explanation + "Answer: X" line, so what is learned is the same behaviour the evaluation measures
  * the budget is FIXED across conditions: --steps x --bs x --accum examples (default 1500 x 8 x 1 = 12,000),
    so every dataset gets the same number of gradient updates and the same number of examples

Resumable: every --ckpt-every steps the adapter + optimiser + scheduler + RNG + data cursor go to <out>/latest/.
Re-running the same command continues from there (Colab sessions die; at most --ckpt-every steps are lost).
Runs in the training env (eval env + peft/accelerate; cloud/runpod.sh TRAIN=1 or data_ablation/setup_colab.sh).
"""
import argparse, json, math, random, shutil, sys, time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import git_commit, read_jsonl  # noqa: E402

MODEL, MODEL_REV = "Qwen/Qwen3-VL-4B-Instruct", "ebb281ec70b05090aa6165b016eac8ec08e71b17"
LORA_TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
PIXELS = dict(min_pixels=4 * 32 * 32, max_pixels=1280 * 32 * 32)  # same image budget as run_eval.py


def load_records(paths, max_images):
    rows = []
    for p in paths:
        base = Path(p).parent
        for r in read_jsonl(p):
            if not r.get("response") or not r.get("prompt"):
                continue
            if len(r["images"]) > max_images:
                continue
            r["_images"] = [base / q for q in r["images"]]
            rows.append(r)
    return rows


class SkipBatch(Exception):
    """Every example in the batch is longer than --max-len (nothing to train on)."""


def encode(proc, rows, max_len):
    """Batch -> input_ids/pixel values/labels. Loss only on the assistant tokens (prompt tokens are -100).

    No tokenizer truncation: cutting a sequence can slice through image tokens and the processor refuses it
    (ValueError "Mismatch in image token count"). Examples longer than max_len are dropped from the batch instead
    and counted by the caller (returned as the second value)."""
    from PIL import Image
    prompts, imgs, full = [], [], []
    for r in rows:
        content = [{"type": "image"} for _ in r["_images"]] + [{"type": "text", "text": r["prompt"]}]
        p = proc.apply_chat_template([{"role": "user", "content": content}], add_generation_prompt=True, tokenize=False)
        prompts.append(p)
        imgs.append([Image.open(q).convert("RGB") for q in r["_images"]])
        full.append(p + r["response"].strip() + "<|im_end|>")
    proc.tokenizer.padding_side = "right"
    enc = proc(text=full, images=[im for group in imgs for im in group] or None, return_tensors="pt", padding=True)
    lengths = enc["attention_mask"].sum(1).tolist()
    keep = [i for i, n in enumerate(lengths) if n <= max_len]
    dropped = len(rows) - len(keep)
    if not keep:
        raise SkipBatch(f"all {len(rows)} examples exceed max_len={max_len} (lengths {lengths})")
    if dropped:
        prompts, imgs, full = [prompts[i] for i in keep], [imgs[i] for i in keep], [full[i] for i in keep]
        enc = proc(text=full, images=[im for group in imgs for im in group] or None, return_tensors="pt", padding=True)
    labels = enc["input_ids"].clone()
    for i, (p, group) in enumerate(zip(prompts, imgs)):
        n_prompt = proc(text=[p], images=group or None, return_tensors="pt")["input_ids"].shape[1]
        labels[i, :n_prompt] = -100
    labels[enc["attention_mask"] == 0] = -100
    enc["labels"] = labels
    return enc, dropped


def save_ckpt(model, opt, sched, state, out, tag):
    """Write to <out>/<tag>.tmp then rename, so a session dying mid-save never leaves a half checkpoint."""
    tmp, dst = out / f"{tag}.tmp", out / tag
    if tmp.exists():
        shutil.rmtree(tmp)
    model.save_pretrained(tmp)
    torch.save({"opt": opt.state_dict(), "sched": sched.state_dict(), "torch_rng": torch.get_rng_state(),
                "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None, **state}, tmp / "state.pt")
    if dst.exists():
        shutil.rmtree(dst)
    tmp.rename(dst)


def train(a):
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForImageTextToText, AutoProcessor
    torch.manual_seed(a.seed)
    rows = load_records(a.data, a.max_images)
    assert rows, "no trainable records (empty response?)"
    need = a.steps * a.bs * a.accum
    print(f"[train] {len(rows)} records, budget {a.steps} steps x {a.bs} x {a.accum} = {need} examples "
          f"({need / len(rows):.2f} epochs)", flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    proc = AutoProcessor.from_pretrained(MODEL, revision=MODEL_REV, **PIXELS)
    model = AutoModelForImageTextToText.from_pretrained(MODEL, revision=MODEL_REV, dtype=torch.bfloat16).to(a.device)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    latest = out / "latest"
    resume = a.resume and (latest / "state.pt").exists()
    if resume:
        model = PeftModel.from_pretrained(model, latest, is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05,
                                                 target_modules=LORA_TARGETS))
    model.print_trainable_parameters()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)

    def lr_mult(s):
        warm = min(1.0, (s + 1) / a.warmup)
        if not a.cosine:
            return warm
        frac = min(1.0, max(0, s - a.warmup) / max(1, a.steps - a.warmup))
        return warm * 0.5 * (1 + math.cos(math.pi * frac))

    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_mult)
    rng = random.Random(a.seed)
    order, pos, step0, log, skipped_oom, skipped_long, elapsed0 = list(range(len(rows))), len(rows), 0, [], 0, 0, 0.0
    if resume:
        st = torch.load(latest / "state.pt", map_location="cpu", weights_only=False)
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        torch.set_rng_state(st["torch_rng"])
        if st.get("cuda_rng") is not None and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(st["cuda_rng"])
        rng.setstate(st["py_rng"])
        order, pos, step0, log, skipped_oom, elapsed0 = st["order"], st["pos"], st["step"], st["log"], st["skipped_oom"], st["elapsed_s"]
        skipped_long = st.get("skipped_long", 0)
        assert st["n_records"] == len(rows), f"resume: data changed ({st['n_records']} -> {len(rows)} records)"
        print(f"[train] resumed from step {step0} ({latest})", flush=True)
    t0 = time.time() - elapsed0

    def state():
        return {"step": step, "py_rng": rng.getstate(), "order": order, "pos": pos, "log": log, "skipped_oom": skipped_oom, "skipped_long": skipped_long,
                "elapsed_s": time.time() - t0, "n_records": len(rows), "config": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()}}

    def write_log():
        (out / "log.json").write_text(json.dumps({"config": state()["config"], "n_records": len(rows), "skipped_oom": skipped_oom, "skipped_long": skipped_long,
                                                  "code_commit": git_commit(), "log": log}, indent=2))

    model.train()
    step = step0
    for step in range(step0 + 1, a.steps + 1):
        losses = []
        for _ in range(a.accum):
            if pos + a.bs > len(order):
                rng.shuffle(order)
                pos = 0
            batch = [rows[i] for i in order[pos:pos + a.bs]]
            pos += a.bs
            try:
                enc, dropped = encode(proc, batch, a.max_len)
                skipped_long += dropped
            except SkipBatch as e:
                skipped_long += len(batch)
                print(f"[train] step {step}: {e} -> micro-batch skipped", flush=True)
                continue
            try:
                loss = model(**enc.to(a.device)).loss
                (loss / a.accum).backward()
                losses.append(loss.item())
            except torch.cuda.OutOfMemoryError:
                # Long sequences on a 24 GB card: retry the same examples one at a time (same data, same update).
                del enc
                torch.cuda.empty_cache()
                n_ok = 0
                for r in batch:
                    try:
                        enc1, _ = encode(proc, [r], a.max_len)
                        loss = model(**enc1.to(a.device)).loss
                        (loss / (a.accum * len(batch))).backward()
                        losses.append(loss.item())
                        n_ok += 1
                    except (torch.cuda.OutOfMemoryError, SkipBatch):
                        torch.cuda.empty_cache()
                        skipped_oom += 1
                print(f"[train] OOM at step {step}: retried one by one, {n_ok}/{len(batch)} ok (skipped so far {skipped_oom})", flush=True)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        if losses and (step % a.log_every == 0 or step == 1):
            log.append({"step": step, "loss": sum(losses) / len(losses), "lr": sched.get_last_lr()[0],
                        "elapsed_s": round(time.time() - t0)})
            print(f"step {step}/{a.steps} loss {log[-1]['loss']:.4f} lr {log[-1]['lr']:.2e} {log[-1]['elapsed_s']}s", flush=True)
        if step % a.ckpt_every == 0 and step < a.steps:
            save_ckpt(model, opt, sched, state(), out, "latest")
            write_log()
        if step in a.save_at or step == a.steps:
            model.save_pretrained(out / f"step{step}")
            write_log()
    if (out / "latest").exists() and step == a.steps:
        shutil.rmtree(out / "latest")  # final adapter is in step<N>/; the resume state is no longer needed
    print(f"[train] done in {(time.time() - t0) / 60:.1f} min, adapters in {out}", flush=True)


def merge(adapter, merged_dir=""):
    """Adapter -> full bf16 model dir that run_eval.py / vLLM can load like the original checkpoint."""
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText, AutoProcessor
    base = AutoModelForImageTextToText.from_pretrained(MODEL, revision=MODEL_REV, dtype=torch.bfloat16)
    dst = Path(merged_dir) if merged_dir else Path(str(adapter).rstrip("/") + "_merged")
    PeftModel.from_pretrained(base, adapter).merge_and_unload().save_pretrained(dst)
    AutoProcessor.from_pretrained(MODEL, revision=MODEL_REV).save_pretrained(dst)
    print(f"merged -> {dst}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", nargs="*", default=[], help="one or more sft.jsonl files")
    ap.add_argument("--out", default="runs/sft/train")
    ap.add_argument("--merge", default="", help="adapter dir to merge instead of training")
    ap.add_argument("--merged-dir", default="", help="where the merged model goes (default <adapter>_merged)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--bs", type=int, default=8, help="A100 80GB default; 24GB (L4/4090): --bs 2 --accum 4")
    ap.add_argument("--accum", type=int, default=1)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--cosine", type=int, default=1, help="1 = cosine decay after warmup, 0 = constant")
    ap.add_argument("--max-len", type=int, default=4096, help="tokens per example incl. image tokens")
    ap.add_argument("--max-images", type=int, default=4)
    ap.add_argument("--save-at", type=int, nargs="*", default=[])
    ap.add_argument("--ckpt-every", type=int, default=100, help="resume checkpoint interval (steps)")
    ap.add_argument("--resume", type=int, default=1, help="1 = continue from <out>/latest if present")
    ap.add_argument("--log-every", type=int, default=25)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.merge:
        merge(a.merge, a.merged_dir)
    else:
        assert a.data, "--data is required"
        train(a)

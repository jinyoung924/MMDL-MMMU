#!/usr/bin/env python
"""Convert one external dataset into the common SFT record format (data_ablation/common.py).

python data_ablation/prepare_data.py --dataset cosyn  --n 12000 --out runs/abl_cosyn/data
python data_ablation/prepare_data.py --dataset vwi    --n 12000 --out runs/abl_vwi/data
python data_ablation/prepare_data.py --dataset pmcvqa --n 12000 --out runs/abl_pmcvqa/data
python data_ablation/prepare_data.py --dataset vwi --inspect        # print raw schema + 2 rows, convert nothing

Every adapter is deterministic (seeded shuffle, fixed revision recorded in manifest.json) and writes
  <out>/raw.jsonl      records (response filled where the dataset ships an explanation, else "")
  <out>/images/        PNG/JPG files referenced by the records
  <out>/manifest.json  dataset id, resolved revision sha, seed, counts, filters, code commit

Prompts are built with run_eval.build_prompt(style="cot"), i.e. the exact wording the evaluation uses, so the
only thing that differs between conditions is the data.
"""
import argparse, csv, json, random, re, sys, time, zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LETTERS, git_commit, make_prompt, make_response, write_jsonl  # noqa: E402

DATASETS = {
    "cosyn": dict(repo="allenai/CoSyn-400K", subsets=["chemical", "circuit", "music", "chart", "diagram"]),
    "vwi": dict(repo="TIGER-Lab/VisualWebInstruct", config="conversation"),
    "pmcvqa": dict(repo="xmcmic/PMC-VQA", csv="train.csv"),
}
PATH_KEYWORDS = ["histolog", "microscop", "stain", "h&e", "patholog", "biops", "cytolog", "immunohisto",
                 "smear", "electron micro", "gram stain", "culture"]


def resolve_sha(repo, revision):
    from huggingface_hub import HfApi
    info = HfApi().dataset_info(repo, revision=revision)
    return info.sha


def save_image(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(path)


# ----------------------------------------------------------------------------------------------- CoSyn
def prep_cosyn(a, cfg):
    from datasets import load_dataset
    subsets = a.subsets or cfg["subsets"]
    per_subset = a.n // len(subsets)
    rng = random.Random(a.seed)
    rows, counts = [], Counter()
    for sub in subsets:
        ds = load_dataset(cfg["repo"], sub, split="train", revision=a.revision)
        idx = list(range(len(ds)))
        rng.shuffle(idx)
        want_imgs = -(-per_subset // a.qa_per_image)  # ceil
        got = 0
        for i in idx:
            if got >= per_subset:
                break
            r = ds[i]
            qas = [q for q in r["qa_pairs"] if q.get("question") and q.get("answer")]
            if not qas:
                continue
            rng.shuffle(qas)
            img_rel = f"images/cosyn_{sub}_{i}.png"
            save_image(r["image"], a.out / img_rel)
            for q in qas[:a.qa_per_image]:
                if got >= per_subset:
                    break
                prompt, _ = make_prompt(q["question"].strip(), [], "open")
                rows.append({"id": f"cosyn:{sub}:{i}:{counts[sub]}", "source": "cosyn", "images": [img_rel],
                             "question": q["question"].strip(), "question_type": "open", "options": {},
                             "answer": str(q["answer"]).strip(), "prompt": prompt,
                             "response": make_response(q.get("explanation", ""), q["answer"]),
                             "meta": {"subset": sub, "figure_type": (r.get("metadata") or {}).get("figure_type", "")}})
                got += 1
                counts[sub] += 1
        print(f"[cosyn] {sub}: {counts[sub]} records from {len(ds)} images (wanted ~{want_imgs} images)", flush=True)
    return rows, {"subsets": subsets, "qa_per_image": a.qa_per_image, "per_subset": dict(counts)}


# ------------------------------------------------------------------------------ VisualWebInstruct (web part only)
BOXED = re.compile(r"\\boxed\s*\{")
FINAL_PATTERNS = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in (
    r"final answer\s*(?:is|:)[\s:]*\**\s*(.+?)\s*\**\s*$",
    r"\banswer\s*(?:is|:)[\s:]*\**\s*(.+?)\s*\**\s*$",
    r"=\s*([^=\n]{1,60})$",
)]


def extract_boxed(text):
    """Last \\boxed{...} with balanced braces, or None."""
    out = None
    for m in BOXED.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        if depth == 0:
            out = text[m.end():i - 1]
    return out


def clean_answer(s):
    s = s.strip().strip("$").strip()
    s = re.sub(r"\\(?:text|mathrm|textbf|mathbf)\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[,;!]", " ", s).replace("\\%", "%").replace("\\$", "$")
    s = s.strip("*: ").rstrip(".").strip()
    return s


def final_answer(solution):
    b = extract_boxed(solution)
    if b is not None:
        return clean_answer(b)
    tail = [l.strip() for l in solution.strip().splitlines() if l.strip()][-3:]
    for line in reversed(tail):
        for p in FINAL_PATTERNS:
            m = p.search(line)
            if m:
                return clean_answer(m.group(1))
    return None


def open_zip_index(zpath):
    z = zipfile.ZipFile(zpath)
    idx = {}
    for name in z.namelist():
        if name.endswith("/"):
            continue
        parts = name.split("/")
        idx.setdefault("/".join(parts[-2:]), name)  # "visualwebinstruct/123.png"
        idx.setdefault(parts[-1], name)              # "123.png"
    return z, idx


def find_zip(repo, revision, pattern, override):
    from huggingface_hub import HfApi, hf_hub_download
    if override:
        return Path(override)
    files = HfApi().list_repo_files(repo, repo_type="dataset", revision=revision)
    cands = [f for f in files if re.search(pattern, f, re.IGNORECASE)]
    if not cands:
        sys.exit(f"no image archive matching /{pattern}/ in {repo}: {files[:40]}")
    print(f"[zip] candidates {cands} -> using {cands[0]}", flush=True)
    return Path(hf_hub_download(repo, cands[0], repo_type="dataset", revision=revision))


def prep_vwi(a, cfg):
    from datasets import load_dataset
    ds = load_dataset(cfg["repo"], cfg["config"], split="train", revision=a.revision)
    print(f"[vwi] {len(ds)} conversations; filtering to single-turn web items with images", flush=True)
    # Only the web-crawled part. The other image sources (coco, chartqa, ai2d, sqa, ...) are standard VLM
    # training sets -> no new information for the model and a confound with other conditions.
    keep = []  # image column only: the conversations column of 1M rows is several GB, read per row below
    for i, imgs in enumerate(ds["image"]):
        if not imgs or len(imgs) > a.max_images:
            continue
        if not all(str(p).startswith("visualwebinstruct/") for p in imgs):
            continue
        keep.append(i)
    print(f"[vwi] {len(keep)} candidates after filtering", flush=True)
    rng = random.Random(a.seed)
    rng.shuffle(keep)
    zpath = find_zip(cfg["repo"], a.revision, r"im(a)?g(e)?s.*\.zip$", a.images_zip)
    z, zidx = open_zip_index(zpath)
    rows, skipped = [], Counter()
    for i in keep:
        if len(rows) >= a.n:
            break
        r = ds[i]
        if len(r["conversations"]) != 2:
            skipped["multi_turn"] += 1
            continue
        human = next((c["value"] for c in r["conversations"] if c["from"] in ("human", "user")), None)
        gpt = next((c["value"] for c in r["conversations"] if c["from"] in ("gpt", "assistant")), None)
        if not human or not gpt:
            skipped["no_turns"] += 1
            continue
        ans = final_answer(gpt)
        if not ans or len(ans) > a.max_answer_chars:
            skipped["no_final_answer"] += 1
            continue
        if len(gpt) > a.max_response_chars:
            skipped["too_long"] += 1
            continue
        question = re.sub(r"<image>\s*", "", human).strip()
        rels = []
        for k, p in enumerate(r["image"]):
            member = zidx.get(p) or zidx.get(Path(p).name)
            if not member:
                break
            rel = f"images/vwi_{i}_{k}{Path(p).suffix or '.png'}"
            dst = a.out / rel
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(member))
            rels.append(rel)
        if len(rels) != len(r["image"]):
            skipped["image_missing"] += 1
            continue
        prompt, _ = make_prompt(question, [], "open")
        rows.append({"id": f"vwi:{r.get('id', i)}", "source": "vwi", "images": rels, "question": question,
                     "question_type": "open", "options": {}, "answer": ans, "prompt": prompt,
                     "response": make_response(gpt, ans), "meta": {"n_images": len(rels)}})
    print(f"[vwi] kept {len(rows)}, skipped {dict(skipped)}", flush=True)
    return rows, {"config": cfg["config"], "filter": "single-turn, images all under visualwebinstruct/",
                  "skipped": dict(skipped), "images_zip": str(zpath)}


# ------------------------------------------------------------------------------------------- PMC-VQA
def strip_choice(s):
    return re.sub(r"^\s*[A-D]\s*[:.)]\s*", "", str(s)).strip()


def prep_pmcvqa(a, cfg):
    from huggingface_hub import hf_hub_download
    csv_path = hf_hub_download(cfg["repo"], a.csv or cfg["csv"], repo_type="dataset", revision=a.revision)
    with open(csv_path, encoding="utf-8", newline="") as f:
        raw = list(csv.DictReader(f))
    print(f"[pmcvqa] {len(raw)} rows in {Path(csv_path).name}; columns {list(raw[0].keys())}", flush=True)
    rng = random.Random(a.seed)

    def label(r):
        lab = (r.get("Answer_label") or "").strip().upper()
        if lab in LETTERS[:4]:
            return lab
        ans = strip_choice(r.get("Answer", ""))
        for L in LETTERS[:4]:
            if strip_choice(r.get(f"Choice {L}", "")) == ans:
                return L
        return None

    cands = []
    for i, r in enumerate(raw):
        lab = label(r)
        choices = [strip_choice(r.get(f"Choice {L}", "")) for L in LETTERS[:4]]
        if not lab or not all(choices) or not r.get("Question", "").strip() or not r.get("Figure_path"):
            continue
        text = (r.get("Question", "") + " " + r.get("Caption", "")).lower()
        kw = any(k in text for k in PATH_KEYWORDS)
        cands.append((i, lab, choices, kw))
    kw_rows = [c for c in cands if c[3]]
    other = [c for c in cands if not c[3]]
    rng.shuffle(kw_rows)
    rng.shuffle(other)
    n_kw = min(len(kw_rows), int(a.n * a.keyword_share))
    picked = kw_rows[:n_kw] + other[:a.n - n_kw]
    print(f"[pmcvqa] {len(cands)} valid rows, {len(kw_rows)} keyword hits -> picking {n_kw} keyword + {len(picked) - n_kw} other", flush=True)
    zpath = find_zip(cfg["repo"], a.revision, r"^images\.zip$|im(a)?g(e)?s.*\.zip$", a.images_zip)
    z, zidx = open_zip_index(zpath)
    rows, missing = [], 0
    for i, lab, choices, kw in picked:
        r = raw[i]
        member = zidx.get(r["Figure_path"]) or zidx.get(Path(r["Figure_path"]).name)
        if not member:
            missing += 1
            continue
        rel = f"images/pmcvqa_{i}{Path(member).suffix or '.jpg'}"
        dst = a.out / rel
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(member))
        q = r["Question"].strip()
        prompt, index2ans = make_prompt(q, choices, "multiple-choice")
        rows.append({"id": f"pmcvqa:{r.get('index', i)}", "source": "pmcvqa", "images": [rel], "question": q,
                     "question_type": "multiple-choice", "options": index2ans, "answer": lab, "prompt": prompt,
                     "response": "",  # no explanation in the dataset -> self_cot.py fills it
                     "meta": {"keyword_hit": kw}})
    print(f"[pmcvqa] kept {len(rows)}, images missing {missing}", flush=True)
    return rows, {"csv": a.csv or cfg["csv"], "keyword_share": a.keyword_share, "keywords": PATH_KEYWORDS,
                  "images_missing": missing, "images_zip": str(zpath)}


# ------------------------------------------------------------------------------------------------ main
def inspect(name, cfg, a):
    from datasets import load_dataset
    if name == "cosyn":
        ds = load_dataset(cfg["repo"], (a.subsets or cfg["subsets"])[0], split="train", revision=a.revision)
    elif name == "vwi":
        ds = load_dataset(cfg["repo"], cfg["config"], split="train", revision=a.revision)
    else:
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(cfg["repo"], a.csv or cfg["csv"], repo_type="dataset", revision=a.revision)
        with open(p, encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            print("columns:", rd.fieldnames)
            for _, r in zip(range(2), rd):
                print(json.dumps(r, ensure_ascii=False)[:1500])
        return
    print(ds)
    print(ds.features)
    for i in range(2):
        r = {k: (v if not hasattr(v, "size") else f"<image {v.size}>") for k, v in ds[i].items()}
        print(json.dumps(r, ensure_ascii=False, default=str)[:2500])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    ap.add_argument("--out", type=Path, default=None, help="default data_ablation/data/<dataset>")
    ap.add_argument("--n", type=int, default=12000, help="records to produce (before decontamination)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--revision", default=None, help="dataset git revision (sha) to pin; default = main, sha recorded")
    ap.add_argument("--inspect", action="store_true", help="print raw schema + first rows and exit")
    # cosyn
    ap.add_argument("--subsets", nargs="*", default=None)
    ap.add_argument("--qa-per-image", type=int, default=2)
    # vwi
    ap.add_argument("--max-images", type=int, default=4)
    ap.add_argument("--max-answer-chars", type=int, default=60)
    ap.add_argument("--max-response-chars", type=int, default=6000)
    ap.add_argument("--images-zip", default=None, help="local path of the image archive (skips the download)")
    # pmcvqa
    ap.add_argument("--csv", default=None)
    ap.add_argument("--keyword-share", type=float, default=0.5,
                    help="share of records drawn from pathology/microscopy keyword hits (MMMU weak types)")
    a = ap.parse_args()
    cfg = DATASETS[a.dataset]
    a.out = a.out or Path("data_ablation/data") / a.dataset
    if a.inspect:
        inspect(a.dataset, cfg, a)
        return
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sha = resolve_sha(cfg["repo"], a.revision)
    print(f"[{a.dataset}] {cfg['repo']} @ {sha[:8]}", flush=True)
    rows, extra = {"cosyn": prep_cosyn, "vwi": prep_vwi, "pmcvqa": prep_pmcvqa}[a.dataset](a, cfg)
    write_jsonl(a.out / "raw.jsonl", rows)
    manifest = {"dataset": a.dataset, "repo": cfg["repo"], "revision": sha, "seed": a.seed, "n_requested": a.n,
                "n_records": len(rows), "n_images": len({p for r in rows for p in r["images"]}),
                "with_response": sum(bool(r["response"]) for r in rows), "code_commit": git_commit(),
                "elapsed_min": round((time.time() - t0) / 60, 1), **extra}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Remove training records that overlap with MMMU (dev + validation + test) or MMMU-Pro.

python data_ablation/decontaminate.py --data runs/abl_cosyn/data            # raw.jsonl -> clean.jsonl + report
python data_ablation/decontaminate.py --data runs/abl_vwi/data --no-images  # text only (synthetic images etc.)

Protected set
  MMMU/MMMU @ DATA_REV, all 30 configs, splits dev/validation/test (test answers are hidden but its questions and
  images are public, and MMMU-Pro is built from MMMU validation+test items -> protecting all three covers MMMU-Pro).
  Optionally MMMU/MMMU_Pro (standard setting) on top, --pro.

Checks (a record is removed if ANY fires; the report says which)
  image_exact   md5 of the raw bytes equals a protected image
  image_phash   64-bit perceptual hash (DCT of a 32x32 grayscale) within --phash-dist Hamming bits
  text_ngram    any --ngram-size word n-gram of the question appears in a protected question
  text_exact    normalized question identical

Stdlib + numpy + PIL only; the protected index is cached next to the data dir so repeated conditions reuse it.
"""
import argparse, hashlib, json, sys, time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, ngrams, norm_text, read_jsonl, write_jsonl  # noqa: E402
sys.path.insert(0, str(ROOT))
from run_eval import DATA_REV, SUBJECTS  # noqa: E402


def phash(img, size=32, keep=8):
    """Classic pHash: grayscale -> 32x32 -> DCT -> top-left 8x8 (minus DC) vs median -> 64 bits (as int)."""
    g = np.asarray(img.convert("L").resize((size, size), Image.Resampling.LANCZOS), dtype=np.float64)
    n = size
    k = np.arange(n)
    c = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))  # DCT-II basis
    d = c @ g @ c.T
    low = d[:keep, :keep].flatten()[1:]
    bits = low > np.median(low)
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a, b):
    return bin(a ^ b).count("1")


def img_bytes_md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def pil_md5(img):
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return hashlib.md5(buf.getvalue()).hexdigest()


def build_protected(cache, ngram_size, with_pro):
    if cache.exists():
        d = json.loads(cache.read_text())
        if d.get("ngram_size") == ngram_size and d.get("with_pro") == with_pro:
            print(f"[protect] cached index {cache} ({d['n_questions']} questions, {d['n_images']} images)", flush=True)
            return d
    from datasets import load_dataset
    phashes, md5s, grams, texts = {}, {}, set(), set()
    n_q = n_img = 0
    t0 = time.time()
    for s in SUBJECTS:
        for split in ("dev", "validation", "test"):
            ds = load_dataset("MMMU/MMMU", s, split=split, revision=DATA_REV)
            for r in ds:
                n_q += 1
                toks = norm_text(r["question"])
                texts.add(" ".join(toks))
                grams |= ngrams(toks, ngram_size)
                for k in range(1, 8):
                    im = r.get(f"image_{k}")
                    if im is None:
                        continue
                    n_img += 1
                    phashes[str(phash(im))] = f"{r['id']}#{k}"
                    md5s[pil_md5(im.convert("RGB"))] = f"{r['id']}#{k}"
        print(f"[protect] {s}: {n_q} questions, {n_img} images so far ({time.time() - t0:.0f}s)", flush=True)
    if with_pro:
        ds = load_dataset("MMMU/MMMU_Pro", "standard (10 options)", split="test")
        for r in ds:
            n_q += 1
            toks = norm_text(r["question"])
            texts.add(" ".join(toks))
            grams |= ngrams(toks, ngram_size)
            for k in range(1, 8):
                im = r.get(f"image_{k}")
                if im is None:
                    continue
                n_img += 1
                phashes[str(phash(im))] = f"pro:{r['id']}#{k}"
                md5s[pil_md5(im.convert("RGB"))] = f"pro:{r['id']}#{k}"
    d = {"ngram_size": ngram_size, "with_pro": with_pro, "n_questions": n_q, "n_images": n_img,
         "phash": phashes, "md5": md5s, "grams": sorted(grams), "texts": sorted(texts)}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(d))
    print(f"[protect] built index: {n_q} questions, {n_img} images, {len(grams)} {ngram_size}-grams", flush=True)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="dir with raw.jsonl and images/")
    ap.add_argument("--inp", default="raw.jsonl")
    ap.add_argument("--out", default="clean.jsonl")
    ap.add_argument("--ngram-size", type=int, default=8)
    ap.add_argument("--phash-dist", type=int, default=6, help="Hamming distance (of 64 bits) treated as a match")
    ap.add_argument("--no-images", action="store_true", help="skip image checks (synthetic images)")
    ap.add_argument("--pro", action="store_true", help="also protect MMMU-Pro standard (needs HF access to MMMU/MMMU_Pro)")
    ap.add_argument("--cache", type=Path, default=Path("data_ablation/data/protected_index.json"))
    a = ap.parse_args()

    prot = build_protected(a.cache, a.ngram_size, a.pro)
    grams, texts = set(prot["grams"]), set(prot["texts"])
    phashes = {int(k): v for k, v in prot["phash"].items()}
    md5s = prot["md5"]
    ph_arr = np.array(list(phashes), dtype=np.uint64) if phashes else np.zeros(0, dtype=np.uint64)
    ph_ids = list(phashes.values())

    rows = read_jsonl(a.data / a.inp)
    kept, removed, reasons, examples = [], [], Counter(), []
    img_cache = {}
    for r in rows:
        hits = []
        toks = norm_text(r["question"])
        if " ".join(toks) in texts:
            hits.append(("text_exact", ""))
        else:
            g = ngrams(toks, a.ngram_size) & grams
            if g:
                hits.append(("text_ngram", next(iter(g))))
        if not a.no_images:
            for rel in r["images"]:
                p = a.data / rel
                if rel not in img_cache:
                    try:
                        im = Image.open(p)
                        img_cache[rel] = (pil_md5(im.convert("RGB")), phash(im))
                    except Exception as e:  # unreadable image -> drop the record, say why
                        img_cache[rel] = (None, None)
                        hits.append(("image_unreadable", str(e)[:80]))
                        continue
                m, h = img_cache[rel]
                if m is None:
                    hits.append(("image_unreadable", rel))
                elif m in md5s:
                    hits.append(("image_exact", md5s[m]))
                elif len(ph_arr):
                    x = np.bitwise_xor(ph_arr, np.uint64(h))
                    dist = np.array([bin(int(v)).count("1") for v in x])
                    j = int(dist.argmin())
                    if dist[j] <= a.phash_dist:
                        hits.append(("image_phash", f"{ph_ids[j]} d={int(dist[j])}"))
        if hits:
            removed.append(r["id"])
            for k, v in hits:
                reasons[k] += 1
            if len(examples) < 30:
                examples.append({"id": r["id"], "hits": hits, "question": r["question"][:200]})
        else:
            kept.append(r)
    write_jsonl(a.data / a.out, kept)
    report = {"input": len(rows), "kept": len(kept), "removed": len(removed), "reasons": dict(reasons),
              "ngram_size": a.ngram_size, "phash_dist": a.phash_dist, "images_checked": not a.no_images,
              "protected": {"questions": prot["n_questions"], "images": prot["n_images"], "mmmu_pro": a.pro},
              "removed_ids": removed, "examples": examples}
    (a.data / "decontam_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k not in ("removed_ids", "examples")}, indent=2))
    print(f"-> {a.data / a.out}")


if __name__ == "__main__":
    main()

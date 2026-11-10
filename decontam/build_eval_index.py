#!/usr/bin/env python
"""Step 0: build the E index once (MMMU dev+val, MMMU-Pro standard-10 + vision), reused by every dataset check.

    python decontam/build_eval_index.py --out /workspace/decontam/eval_index                  # GPU pod
    python decontam/build_eval_index.py --out /tmp/idx --local tests/e.jsonl --image-embedder tiny --text-embedder hash

Writes
  items.jsonl        eid, bench (mmmu|pro), question text, normalized text
  images.npz         per image: eid, pixel SHA-256, SSCD embedding (L2-normalized)
  text_emb.npy       per item: multilingual sentence embedding of question+options
  grams.json         13-gram -> eids, exact normalized texts -> eids
  thumbs/<n>.jpg     every E image as a 384-px thumbnail, so near-duplicate pairs can be checked by eye
  calib.json         SSCD review band: 1st percentile of cos(E image, its crop/resize/JPEG copy)  (section 2.1)
"""
import argparse
import io
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from common import ROOT, image_embedder, item_text, ngrams, norm_text, pixel_sha256, text_embedder, to_rgb


def variants(im, rng):
    """The edits section 2.1 calls near-duplicates: crop, resize, JPEG, and all three together."""
    im = to_rgb(im)
    w, h = im.size
    c = rng.uniform(0.03, 0.10)
    crop = im.crop((int(w * c), int(h * c), w - int(w * c), h - int(h * c)))
    small = im.resize((max(8, w // 2), max(8, h // 2)), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=40)
    jpg = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    buf = io.BytesIO()
    crop.resize((max(8, crop.width // 2), max(8, crop.height // 2))).save(buf, "JPEG", quality=40)
    allv = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    return {"crop": crop, "resize": small, "jpeg": jpg, "all": allv}


def load_eval_items(local=None):
    """Yield dicts: eid, bench, question, options, images (PIL list)."""
    if local:
        base = Path(local).parent
        for l in open(local, encoding="utf-8"):
            r = json.loads(l)
            yield {"eid": r["id"], "bench": r["bench"], "question": r["question"], "options": r.get("options", []),
                   "images": [Image.open(base / p) for p in r.get("images", [])]}
        return
    from datasets import load_dataset
    from run_eval import DATA_REV, SUBJECTS
    for s in SUBJECTS:
        for split in ("dev", "validation"):
            for r in load_dataset("MMMU/MMMU", s, split=split, revision=DATA_REV):
                yield {"eid": f"mmmu:{r['id']}", "bench": "mmmu", "question": r["question"], "options": r["options"],
                       "images": [r[f"image_{k}"] for k in range(1, 8) if r.get(f"image_{k}") is not None]}
    # MMMU-Pro: test is the only split; the 4- and 10-option configs share questions, vision shares ids
    pro = {}
    for r in load_dataset("MMMU/MMMU_Pro", "standard (10 options)", split="test"):
        pro[r["id"]] = {"eid": f"pro:{r['id']}", "bench": "pro", "question": r["question"], "options": r["options"],
                        "images": [r[f"image_{k}"] for k in range(1, 8) if r.get(f"image_{k}") is not None]}
    for r in load_dataset("MMMU/MMMU_Pro", "vision", split="test"):
        if r["id"] in pro and r.get("image") is not None:
            pro[r["id"]]["images"].append(r["image"])       # the screenshot that carries the question
    yield from pro.values()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--local", help="test mode: jsonl of {id, bench, question, options, images[]} instead of HF")
    ap.add_argument("--image-embedder", default="sscd", choices=["sscd", "tiny"])
    ap.add_argument("--text-embedder", default="st", choices=["st", "hash"])
    ap.add_argument("--calib-images", type=int, default=500)
    a = ap.parse_args()
    (a.out / "thumbs").mkdir(parents=True, exist_ok=True)

    items, img_eid, img_sha, imgs = [], [], [], []
    grams, exact = defaultdict(set), defaultdict(set)
    for it in load_eval_items(a.local):
        text = item_text(it["question"], it["options"])
        toks = norm_text(text)
        items.append({"eid": it["eid"], "bench": it["bench"], "question": str(it["question"])[:500],
                      "text": " ".join(toks)})
        for g in ngrams(toks):
            grams[g].add(it["eid"])
        exact[" ".join(toks)].add(it["eid"])
        exact[" ".join(norm_text(it["question"]))].add(it["eid"])    # question alone, for T without options
        for im in it["images"]:
            img_eid.append(it["eid"])
            img_sha.append(pixel_sha256(im))
            im = to_rgb(im)
            im.thumbnail((1024, 1024))    # keep RAM bounded (Pro screenshots are large); SSCD resizes to 288 anyway
            imgs.append(im)
            th = imgs[-1].copy()
            th.thumbnail((384, 384))
            th.save(a.out / "thumbs" / f"{len(imgs) - 1}.jpg", quality=85)
        if len(items) % 500 == 0:
            print(f"[E] {len(items)} items, {len(imgs)} images", flush=True)

    emb_img = image_embedder(a.image_embedder)
    E = emb_img(imgs)
    T = text_embedder(a.text_embedder)([i["text"] for i in items])

    # calibration: how similar is an E image to its own edited copy? below 0.95 but above this = eyeball band
    rng = random.Random(0)
    pick = rng.sample(range(len(imgs)), min(a.calib_images, len(imgs)))
    sims = {}
    for kind in ("crop", "resize", "jpeg", "all"):
        V = emb_img([variants(imgs[i], random.Random(i))[kind] for i in pick])
        sims[kind] = (V * E[pick]).sum(1)
    allsims = np.concatenate(list(sims.values()))
    calib = {"review_floor": float(np.percentile(allsims, 1)), "match": 0.95, "embedder": a.image_embedder,
             "by_variant": {k: {"p1": float(np.percentile(v, 1)), "median": float(np.median(v))} for k, v in sims.items()},
             "n_calib": len(pick)}

    with open(a.out / "items.jsonl", "w", encoding="utf-8") as f:
        for i in items:
            f.write(json.dumps(i, ensure_ascii=False) + "\n")
    np.savez_compressed(a.out / "images.npz", eid=np.array(img_eid), sha=np.array(img_sha), emb=E.astype(np.float16))
    np.save(a.out / "text_emb.npy", T.astype(np.float16))
    (a.out / "grams.json").write_text(json.dumps({"ngram": {k: sorted(v) for k, v in grams.items()},
                                                  "exact": {k: sorted(v) for k, v in exact.items()},
                                                  "embedders": [a.image_embedder, a.text_embedder]}), encoding="utf-8")
    (a.out / "calib.json").write_text(json.dumps(calib, indent=2), encoding="utf-8")
    n = {b: sum(i["bench"] == b for i in items) for b in ("mmmu", "pro")}
    print(json.dumps({"items": n, "images": len(imgs), "grams": len(grams), "calib": calib}, indent=2))


if __name__ == "__main__":
    main()

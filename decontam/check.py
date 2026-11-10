#!/usr/bin/env python
"""Steps 1-2 of reports/dataset_search.md section 2: detect overlap of one dataset (T) with E, then grade A/B/C/D.

    # detect (slow part, GPU helps): writes hits.jsonl, judge_candidates.jsonl, review/, detect.json
    python decontam/check.py detect --index IDX --out OUT/cosyn_music --hf allenai/CoSyn-400K --config music
    python decontam/check.py detect --index IDX --out OUT/slake --json SLAKE/train.json --image-root SLAKE/imgs --where q_lang=en
    # after the LLM judge (judge.py) and, optionally, eyeballing review/ pairs:
    python decontam/check.py grade  --out OUT/cosyn_music [--verdicts .../verdicts.jsonl] [--confirmed review_ok.txt]
                                    [--recall RECALL_OUT/recall.json]

Detection, per T record (section 2.1)
  image exact   pixel SHA-256 equal to an E image
  image near    SSCD cosine >= 0.95 with an E image; [calibrated floor, 0.95) -> review/ for eyeballing
  text 13-gram  a 13-gram of normalized question+options shared with E (shorter than 13 tokens: whole text equal)
  paraphrase    top-5 E items by multilingual embedding with cosine >= --para-min -> LLM judge decides
  template      a question string seen >= 10 times in T counts as a text match only together with an image match
Grades (section 2.2): A image+text, B image only, C text only AND judge says same problem, D clean.
"""
import argparse
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from common import (E_SIZE, NGRAM, SSCD_MATCH, TEMPLATE_MIN, image_embedder, item_text, ngrams, norm_text,
                    pixel_sha256, text_embedder, to_rgb)
import load_train


def _sha_map(shas, eids):
    """pixel SHA -> every E item that uses that image (MMMU val and MMMU-Pro share many images)."""
    m = defaultdict(set)
    for s, e in zip(shas, eids):
        m[s].add(e)
    return m


def load_index(d):
    d = Path(d)
    items = [json.loads(l) for l in open(d / "items.jsonl", encoding="utf-8")]
    z = np.load(d / "images.npz")
    g = json.loads((d / "grams.json").read_text(encoding="utf-8"))
    return {"items": {i["eid"]: i for i in items}, "eids": [i["eid"] for i in items],
            "img_eid": z["eid"].tolist(), "sha": _sha_map(z["sha"].tolist(), z["eid"].tolist()),
            "img_emb": z["emb"].astype(np.float32), "txt_emb": np.load(d / "text_emb.npy").astype(np.float32),
            "ngram": g["ngram"], "exact": g["exact"], "embedders": g["embedders"],
            "calib": json.loads((d / "calib.json").read_text(encoding="utf-8")), "dir": d}


def safe_name(x):
    """A record id as a file name on every OS (Windows refuses <>:"/\\|?*)."""
    return re.sub(r'[<>:"/\\|?*\s]', "_", str(x))[:150]


def qkey(q):
    return hashlib.md5(" ".join(norm_text(q)).encode()).hexdigest()[:12]


def detect(a):
    idx = load_index(a.index)
    emb_img = None if a.no_images else image_embedder(idx["embedders"][0])
    emb_txt = text_embedder(idx["embedders"][1])
    floor = min(idx["calib"]["review_floor"], SSCD_MATCH)
    out = Path(a.out)
    (out / "review").mkdir(parents=True, exist_ok=True)
    fh = open(out / "hits.jsonl", "w", encoding="utf-8")
    qcount, subsets = Counter(), Counter()
    stats = Counter()
    n_review = [0]
    t0 = time.time()

    def flush(batch):
        if not batch:
            return
        texts = [item_text(r["question"], r["options"]) for r in batch]
        T = emb_txt(texts)
        S = T @ idx["txt_emb"].T                                   # (batch, |E|)
        top = np.argsort(-S, axis=1)[:, :5]
        flat, owner = [], []
        if emb_img is not None:
            for j, r in enumerate(batch):
                for im in r["images"]:
                    try:
                        flat.append(to_rgb(im))
                        owner.append(j)
                    except Exception:
                        stats["image_unreadable"] += 1
        V = emb_img(flat) if flat else np.zeros((0, 1))
        sim = V @ idx["img_emb"].T if len(flat) else np.zeros((0, 0))
        per = defaultdict(lambda: {"img_exact": set(), "img_near": {}, "review": {}})
        for n, j in enumerate(owner):
            per[j]["img_exact"] |= idx["sha"].get(pixel_sha256(flat[n]), set())
            k = int(sim[n].argmax())
            s, e2 = float(sim[n, k]), idx["img_eid"][k]
            if s >= SSCD_MATCH:   # every E image above the bar, not just the best: a shared image has two owners
                for kk in np.flatnonzero(sim[n] >= SSCD_MATCH):
                    ee = idx["img_eid"][kk]
                    per[j]["img_near"][ee] = max(float(sim[n, kk]), per[j]["img_near"].get(ee, 0))
            elif s >= floor:
                per[j]["review"][e2] = s
                n_review[0] += 1
            if floor <= s < SSCD_MATCH and n_review[0] <= a.review_max:   # save the T side; E side is thumbs/<k>.jpg
                flat[n].copy().resize((384, max(1, int(384 * flat[n].height / max(1, flat[n].width))))).save(
                    out / "review" / f"{safe_name(batch[j]['tid'])}__{k}__{s:.3f}.jpg", quality=85)
        for j, r in enumerate(batch):
            toks = norm_text(texts[j])
            hit_text = set()
            if len(toks) < NGRAM:
                hit_text |= set(idx["exact"].get(" ".join(toks), []))
                hit_text |= set(idx["exact"].get(" ".join(norm_text(r["question"])), []))
            else:
                for g in ngrams(toks):
                    hit_text |= set(idx["ngram"].get(g, []))
            para = {idx["eids"][k]: float(S[j, k]) for k in top[j] if S[j, k] >= a.para_min}
            p = per.get(j, {"img_exact": set(), "img_near": {}, "review": {}})
            if hit_text or para or p["img_exact"] or p["img_near"] or p["review"]:
                fh.write(json.dumps({"tid": r["tid"], "subset": r["subset"], "qkey": qkey(r["question"]),
                                     "question": r["question"][:400],
                                     "img_exact": sorted(p["img_exact"]), "img_near": p["img_near"],
                                     "review": p["review"], "ngram": sorted(hit_text), "para": para},
                                    ensure_ascii=False) + "\n")
        stats["records"] += len(batch)
        stats["images"] += len(flat)

    batch = []
    for r in load_train.stream(a):
        qcount[qkey(r["question"])] += 1
        subsets[r["subset"]] += 1
        batch.append(r)
        if len(batch) >= a.batch:
            flush(batch)
            batch = []
            if stats["records"] % (a.batch * 20) == 0:
                print(f"[T] {stats['records']} records, {stats['images']} images, {time.time() - t0:.0f}s", flush=True)
    flush(batch)
    fh.close()
    templates = {k: v for k, v in qcount.items() if v >= TEMPLATE_MIN}
    meta = {"source": a.hf or a.json, "config": a.config, "split": a.split, "where": a.where,
            "records": stats["records"], "images": stats["images"], "image_unreadable": stats["image_unreadable"],
            "images_checked": not a.no_images, "subsets": dict(subsets), "templates": templates,
            "para_min": a.para_min, "review_floor": floor, "embedders": idx["embedders"], "index": str(idx["dir"]),
            "seconds": round(time.time() - t0)}
    (out / "detect.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    write_judge_candidates(out, idx, templates)
    print(json.dumps({k: v for k, v in meta.items() if k != "templates"}, indent=2, ensure_ascii=False))


def write_judge_candidates(out, idx, templates):
    """Text-only signals need the judge (grade C). Records with an image match are A/B without it."""
    n = 0
    with open(out / "judge_candidates.jsonl", "w", encoding="utf-8") as f:
        for h in map(json.loads, open(out / "hits.jsonl", encoding="utf-8")):
            if h["img_exact"] or h["img_near"] or h["qkey"] in templates:
                continue
            for e in sorted(set(h["ngram"]) | set(h["para"])):
                f.write(json.dumps({"tid": h["tid"], "eid": e, "t_question": h["question"],
                                    "e_question": idx["items"][e]["question"],
                                    "why": "ngram" if e in h["ngram"] else f"para {h['para'][e]:.3f}"},
                                   ensure_ascii=False) + "\n")
                n += 1
    print(f"[judge] {n} candidate pairs -> {out / 'judge_candidates.jsonl'}")


def grade(a):
    out = Path(a.out)
    meta = json.loads((out / "detect.json").read_text(encoding="utf-8"))
    templates = set(meta["templates"])
    verdict = None
    if a.verdicts:
        verdict = {(v["tid"], v["eid"]): v["same"] for v in map(json.loads, open(a.verdicts, encoding="utf-8"))}
    confirmed = set(Path(a.confirmed).read_text(encoding="utf-8").split()) if a.confirmed else set()   # "tid eid" lines -> image match
    cnt = Counter()
    hits_e = {"mmmu": set(), "pro": set()}
    removed, pending, by_subset = [], 0, Counter()
    for h in map(json.loads, open(out / "hits.jsonl", encoding="utf-8")):
        img = set(h["img_exact"]) | set(h["img_near"]) | {e for e in h["review"] if f"{h['tid']} {e}" in confirmed}
        cnt["exact"] += bool(h["img_exact"])
        cnt["near"] += bool(not h["img_exact"] and (h["img_near"] or img))
        txt = set(h["ngram"])
        if h["qkey"] in templates:                      # template question: text alone is not evidence
            txt &= img
        cnt["ngram"] += bool(txt)
        if img:
            g, eids = ("A" if txt or set(h["para"]) & img else "B"), img | txt
        else:
            cands = (txt | set(h["para"])) if h["qkey"] not in templates else set()
            if not cands:
                continue
            if verdict is None:
                pending += 1
                continue
            same = {e for e in cands if verdict.get((h["tid"], e))}
            if not same:
                continue
            g, eids = "C", same
            cnt["para"] += bool(same - txt)
        cnt[g] += 1
        removed.append(h["tid"])
        by_subset[h["subset"]] += 1
        for e in eids:
            hits_e["pro" if e.startswith("pro:") else "mmmu"].add(e)
    N = meta["records"]
    k = {b: len(v) for b, v in hits_e.items()}
    rep = {"records": N, "exact": cnt["exact"], "near_dup": cnt["near"], "ngram13": cnt["ngram"],
           "paraphrase": cnt["para"], "A": cnt["A"], "B": cnt["B"], "C": cnt["C"], "C_pending_judge": pending,
           "removed": len(removed), "removed_pct": round(100 * len(removed) / max(1, N), 3),
           "k": k, "hit_eids": {b: sorted(v) for b, v in hits_e.items()}, "removed_by_subset": dict(by_subset),
           "images_checked": meta["images_checked"]}
    rep.update(risk(k, a.recall, by_subset, a.recall_kinds))
    (out / "removed_ids.txt").write_text("\n".join(removed) + ("\n" if removed else ""), encoding="utf-8")
    rep["line"] = line(rep)
    (out / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({x: rep[x] for x in rep if x != "hit_eids"}, indent=2, ensure_ascii=False))


def risk(k, recall_path, by_subset, kinds=None):
    """Section 2.3: residual = k (1 - r) / r, inflation = residual / |E| in %p, judged per benchmark, worst wins.
    r = the smallest recall over the variant kinds that apply to this dataset (--recall-kinds)."""
    r = None
    if recall_path:
        rk = json.loads(Path(recall_path).read_text(encoding="utf-8"))["r_by_kind"]
        use = [x for x in (kinds.split(",") if kinds else rk) if x in rk]
        r = min(rk[x] for x in use) if use else None
    res = {"recall_r": r, "recall_kinds": kinds}
    if sum(k.values()) == 0:
        res["verdict"] = "Safe"
        return res
    if not r:
        res["verdict"] = "pending (recall not measured)"
        return res
    infl = {b: round(100 * k[b] * (1 - r) / r / E_SIZE[b], 3) for b in k}
    res["residual_inflation_pp"] = infl
    res["verdict"] = "Risky" if max(infl.values()) >= 0.5 else "Use after removal"
    tot = sum(by_subset.values())
    if tot and by_subset.most_common(1)[0][1] > tot / 2 and len(by_subset) > 1:
        res["note"] = f"over half of the hits are in subset {by_subset.most_common(1)[0][0]}: drop it and re-grade"
    return res


def line(r):
    """Column-4 format of reports/dataset_search.md."""
    ab = f"A/B/C = {r['A']}/{r['B']}/{r['C']}" + (f" (+{r['C_pending_judge']} judge 대기)" if r["C_pending_judge"] else "")
    img = f"exact {r['exact']} · near-dup {r['near_dup']}" if r["images_checked"] else "이미지 검사 안 함"
    return (f"{img} · 13-gram {r['ngram13']} · paraphrase {r['paraphrase']} · {ab} · "
            f"제거 {r['removed']}건 ({r['removed_pct']}%) · 적중 MMMU {r['k']['mmmu']} / Pro {r['k']['pro']} · {r['verdict']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--index", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--hf")
    d.add_argument("--config")
    d.add_argument("--split")
    d.add_argument("--json")
    d.add_argument("--image-root")
    d.add_argument("--fields", default="")
    d.add_argument("--where", default="")
    d.add_argument("--limit", type=int, default=0)
    d.add_argument("--no-images", action="store_true", help="text checks only (images not available)")
    d.add_argument("--para-min", type=float, default=0.80, help="embedding cosine for a judge candidate")
    d.add_argument("--batch", type=int, default=256)
    d.add_argument("--review-max", type=int, default=300)
    g = sub.add_parser("grade")
    g.add_argument("--out", required=True)
    g.add_argument("--verdicts")
    g.add_argument("--confirmed")
    g.add_argument("--recall", help="recall.json from recall.py score")
    g.add_argument("--recall-kinds", help="variant kinds that apply, e.g. image (synthetic text) or image,text,both")
    i = sub.add_parser("inspect", help="print the first records as the reader sees them")
    for x in ("--hf", "--config", "--split", "--json", "--image-root"):
        i.add_argument(x)
    i.add_argument("--fields", default="")
    i.add_argument("--where", default="")
    i.add_argument("--limit", type=int, default=0)
    i.add_argument("--no-images", action="store_true")
    a = ap.parse_args()
    if a.cmd == "detect":
        assert a.hf or a.json, "--hf or --json"
        detect(a)
    elif a.cmd == "inspect":
        load_train.inspect(a)
    else:
        grade(a)


if __name__ == "__main__":
    main()

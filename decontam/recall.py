#!/usr/bin/env python
"""Section 2.3 recall r: hide edited copies of known E items and count how many the detector finds again.

    python decontam/recall.py make  --out R               # 50 MMMU val + 50 MMMU-Pro items -> R/records.jsonl, R/img/
    python decontam/check.py detect --index IDX --out R --json R/records.jsonl --image-root R
    python decontam/judge.py --cands R/judge_candidates.jsonl
    python decontam/recall.py score --out R               # -> R/recall.json  {r_by_kind, n}

Kinds (one record per source item and kind)
  image  every image edited (crop 3-10% + half size + JPEG 40), question removed   -> tests the image detectors
  text   question paraphrased by the LLM, no image                                   -> tests 13-gram + embedding + judge
  trans  question translated to Chinese, no image                                    -> tests cross-lingual retrieval
  both   edited images + paraphrased question
Detection is per record (only the template count looks at the rest of T, and these copies are unique), so checking
the copies on their own gives the same result as mixing them into a copy of T. The copies are thrown away afterwards.
"""
import argparse
import json
import random
import zlib
from pathlib import Path

from build_eval_index import load_eval_items, variants

PARA = "Rewrite the following exam question in different words. Keep every number, name and the thing asked; do not \
answer it. Output only the rewritten question.\n\n{q}"
TRANS = "Translate the following exam question into Chinese. Keep every number and formula; do not answer it. Output \
only the translation.\n\n{q}"


def make(a):
    from judge import LLM
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    pool = {"mmmu": [], "pro": []}
    for it in load_eval_items(a.local):
        if it["images"] and (it["bench"] == "pro" or a.local or "validation_" in it["eid"]):
            pool[it["bench"]].append(it)
    rng = random.Random(0)
    src = [x for b in pool for x in rng.sample(pool[b], min(a.n, len(pool[b])))]
    llm = LLM(a.model, a.backend) if "text" in a.kinds or "trans" in a.kinds or "both" in a.kinds else None
    para = dict(zip([s["eid"] for s in src], llm.chat([PARA.format(q=s["question"]) for s in src], 512, 0.7))) if llm else {}
    trans = dict(zip([s["eid"] for s in src], llm.chat([TRANS.format(q=s["question"]) for s in src], 512))) if llm else {}
    recs = []
    for s in src:
        key = s["eid"].replace(":", "_")
        paths = []
        for i, im in enumerate(s["images"]):
            p = f"img/{key}_{i}.jpg"
            variants(im, random.Random(zlib.crc32(key.encode()) + i))["all"].save(out / p, quality=90)
            paths.append(p)
        for kind in a.kinds.split(","):
            q = {"image": "", "text": para.get(s["eid"]), "trans": trans.get(s["eid"]), "both": para.get(s["eid"])}[kind]
            if q is None:
                continue
            recs.append({"id": f"{kind}:{s['eid']}", "kind": kind, "source_eid": s["eid"], "question": q,
                         "options": [] if kind == "image" else s["options"],
                         "images": paths if kind in ("image", "both") else []})
    with open(out / "records.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[recall] {len(src)} source items, {len(recs)} edited copies -> {out / 'records.jsonl'}")


def score(a):
    out = Path(a.out)
    recs = {r["id"]: r for r in map(json.loads, open(out / "records.jsonl", encoding="utf-8"))}
    verdict = {}
    if (out / "verdicts.jsonl").exists():
        verdict = {(v["tid"], v["eid"]): v["same"] for v in map(json.loads, open(out / "verdicts.jsonl", encoding="utf-8"))}
    found = set()
    for h in map(json.loads, open(out / "hits.jsonl", encoding="utf-8")):
        r = recs.get(h["tid"])
        if not r:
            continue
        e = r["source_eid"]
        img = e in h["img_exact"] or e in h["img_near"]
        txt = (e in h["ngram"] or e in h["para"]) and (img or verdict.get((h["tid"], e), False))
        if img or txt:
            found.add(h["tid"])
    by = {}
    for kind in sorted({r["kind"] for r in recs.values()}):
        ids = [i for i, r in recs.items() if r["kind"] == kind]
        by[kind] = round(sum(i in found for i in ids) / len(ids), 3)
    missed = sorted(set(recs) - found)
    res = {"r_by_kind": by, "n": {k: sum(r["kind"] == k for r in recs.values()) for k in by}, "missed": missed[:50]}
    (out / "recall.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--out", required=True)
    m.add_argument("--n", type=int, default=50, help="items per benchmark")
    m.add_argument("--kinds", default="image,text,trans,both")
    m.add_argument("--local", help="test mode: E jsonl instead of HF")
    m.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    m.add_argument("--backend", default="vllm", choices=["vllm", "dummy"])
    s = sub.add_parser("score")
    s.add_argument("--out", required=True)
    a = ap.parse_args()
    make(a) if a.cmd == "make" else score(a)


if __name__ == "__main__":
    main()

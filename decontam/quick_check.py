#!/usr/bin/env python
"""Quick contamination check on a laptop (CPU only, no GPU, no LLM): fills column 4 of reports/dataset_search.md.

    python decontam/quick_check.py all              # index E, check every dataset, write dataset_search_filled.md
    python decontam/quick_check.py all --only slake,pathvqa
    python decontam/quick_check.py grade            # after filling the `same` column of text_candidates.csv by hand

What it does differently from section 2 of dataset_search.md (and what it gives up)
  near-duplicate images  pHash (64-bit DCT hash, Hamming <= 8) instead of SSCD   -> heavy crops can be missed
  text                   13-gram + exact match only, no embedding retrieval       -> paraphrases/translations missed
  judge                  text-only hits go to text_candidates.csv for a person    -> no LLM needed
  synthetic datasets     image check skipped: their images are rendered by code, so they cannot be MMMU images
  recall                 image recall only (edited E images vs the pHash index)
Work files go to decontam/qc_work (delete it afterwards). Re-running skips datasets that already have a report.
"""
import argparse
import csv
import io
import json
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import NGRAM, TEMPLATE_MIN, item_text, ngrams, norm_text, pixel_sha256, to_rgb  # noqa: E402
import load_train  # noqa: E402

WORK = HERE / "qc_work"
MATCH, REVIEW = 8, 12          # pHash Hamming: <= 8 near-duplicate, 9..12 saved for eyeballing
SUBJECTS = ["Accounting", "Agriculture", "Architecture_and_Engineering", "Art", "Art_Theory", "Basic_Medical_Science",
            "Biology", "Chemistry", "Clinical_Medicine", "Computer_Science", "Design", "Diagnostics_and_Laboratory_Medicine",
            "Economics", "Electronics", "Energy_and_Power", "Finance", "Geography", "History", "Literature", "Manage",
            "Marketing", "Materials", "Math", "Mechanical_Engineering", "Music", "Pharmacy", "Physics", "Psychology",
            "Public_Health", "Sociology"]

# name: repo / files (HF glob) / reader options / images checked? / note for column 4
DATASETS = {
    "cosyn_music":    dict(repo="allenai/CoSyn-400K", files=["music/train-*.parquet"], images=False, synthetic="LilyPond 렌더"),
    "musixqa":        dict(repo="puar-playground/MusiXQA", files=["train_qa_simple.json"], images=False, synthetic="MusiXTeX 렌더"),
    "cosyn_circuit":  dict(repo="allenai/CoSyn-400K", files=["circuit/train-*.parquet"], images=False, synthetic="LaTeX 렌더"),
    "circuitvqa":     dict(gdrive=["10kqGKCNAIG3VpOUvj4Ym6AH49ZaLvC_1", "1qH6jfWym0Wjg9KKCPQto7MZr0VWM9QpF"], images=True,
                           read="questions/all/master.json", where="splittype=train", fields="image=file",
                           image_root="384a/model-inputs"),   # master_*.json are prompt variants of the same QA
    "cosyn_chemical": dict(repo="allenai/CoSyn-400K", files=["chemical/train-*.parquet"], images=False, synthetic="RDKit 렌더"),
    "pathvqa":        dict(repo="flaviagiammarino/path-vqa", files=["data/train-*.parquet"], images=True),
    "slake":          dict(repo="BoKelvin/SLAKE", files=["train.json", "imgs.zip"], images=True,
                           fields="image=img_name", where="q_lang=en", read="train.json"),
    "vqarad":         dict(repo="flaviagiammarino/vqa-rad", files=["data/train-*.parquet"], images=True),
    "pubmedvision":   dict(repo="FreedomIntelligence/PubMedVision", files=["*InstructionTuning*.json"], images=False,
                           textonly="이미지 60GB라 텍스트만"),
    "chemvqa":        dict(local="chemvqa", images=False, synthetic="RDKit 렌더"),
    "ssmr":           dict(repo="Sylence/SSMR-Bench", files=["data/Train_visual-*.parquet", "data/Train_textual-*.parquet"],
                           images=False, synthetic="악보 렌더"),
    "nota":           dict(repo="MYTH-Lab/NOTA-dataset", files=["data/train_IE-*.parquet", "data/train_alignment-*.parquet",
                           "data/train_analysis-*.parquet"], images=False, textonly="이미지가 행에 없어 텍스트만"),
    "openmmreasoner": dict(repo="OpenMMReasoner/OpenMMReasoner-SFT-874K", files=["parquet/*.parquet"], images=False,
                           textonly="이미지가 행에 없어 텍스트만"),
    "virl39k":        dict(repo="TIGER-Lab/ViRL39K", files=["39Krelease.parquet", "images.zip"], images=True,
                           fields="image=image", read="39Krelease.parquet"),
}


# --- image hash ----------------------------------------------------------------------------------------------------
_N = 32
_D = np.sqrt(2 / _N) * np.cos(np.pi * (2 * np.arange(_N)[None] + 1) * np.arange(_N)[:, None] / (2 * _N))
_D[0] /= np.sqrt(2)
_POP = np.array([bin(i).count("1") for i in range(256)], np.uint8)


def phash(im):
    """64-bit perceptual hash; None for nearly blank images (they would match each other by accident)."""
    a = np.asarray(to_rgb(im).convert("L").resize((_N, _N), Image.Resampling.LANCZOS), np.float64)
    if a.std() < 3:
        return None
    low = (_D @ a @ _D.T)[:8, :8].ravel()
    bits = low > np.median(low)
    return int(np.packbits(bits).view(">u8")[0])


_THUMB = {}


def _gray(im):
    a = np.asarray(to_rgb(im).convert("L").resize((64, 64), Image.Resampling.BILINEAR), np.float32).ravel()
    a -= a.mean()
    return a / (np.linalg.norm(a) + 1e-6)


def same_picture(im, k, ncc_min=0.8, ar_tol=0.15):
    """Second check after pHash: same aspect ratio (resize/JPEG keep it, a 10% crop moves it < 0.15 in log) and
    pixel correlation at 64x64. Plain diagrams, tables and screenshots collide in pHash but fail this."""
    if k not in _THUMB:
        e = Image.open(WORK / "thumbs" / f"{k}.jpg")
        _THUMB[k] = (np.log(e.width / e.height), _gray(e))
    ar, g = _THUMB[k]
    im = to_rgb(im)
    if abs(np.log(im.width / im.height) - ar) > ar_tol:
        return False
    return float(_gray(im) @ g) >= ncc_min


def hamming(q, E):
    """q: (n,) uint64, E: (m,) uint64 -> (n, m) bit distances."""
    x = np.bitwise_xor(q[:, None], E[None, :])
    return _POP[x.view(np.uint8)].reshape(len(q), len(E), 8).sum(-1)


# --- downloads -----------------------------------------------------------------------------------------------------
def hf_files(repo, patterns, to):
    from huggingface_hub import snapshot_download
    snapshot_download(repo, repo_type="dataset", allow_patterns=patterns, local_dir=to)
    for z in Path(to).rglob("*.zip"):
        done = z.with_name(z.name + ".unpacked")
        if not done.exists():
            print(f"  unzip {z.name}", flush=True)
            with zipfile.ZipFile(z) as f:
                f.extractall(z.parent)
            done.touch()
    return Path(to)


def rows_of(path):
    """Rows of a parquet / json / jsonl / csv file, streamed."""
    p = Path(path)
    if p.suffix == ".parquet":
        import pyarrow.parquet as pq
        for b in pq.ParquetFile(p).iter_batches(batch_size=256):
            yield from b.to_pylist()
    else:
        yield from load_train.open_json(p)


# --- E index ---------------------------------------------------------------------------------------------------------
def eval_items(d):
    for s in SUBJECTS:
        for f in sorted((d / "mmmu" / s).glob("*.parquet")):
            if f.name.startswith(("dev", "validation")):
                for r in rows_of(f):
                    yield {"eid": f"mmmu:{r['id']}", "question": r["question"], "options": r["options"],
                           "images": [r[f"image_{k}"] for k in range(1, 8) if r.get(f"image_{k}")]}
    pro = {}
    for f in sorted((d / "pro" / "standard (10 options)").glob("*.parquet")):
        for r in rows_of(f):
            pro[r["id"]] = {"eid": f"pro:{r['id']}", "question": r["question"], "options": r["options"],
                            "images": [r[f"image_{k}"] for k in range(1, 8) if r.get(f"image_{k}")]}
    for f in sorted((d / "pro" / "vision").glob("*.parquet")):
        for r in rows_of(f):
            if r["id"] in pro and r.get("image"):
                pro[r["id"]].setdefault("shots", []).append(r["image"])
    yield from pro.values()


def build_index():
    out = WORK / "eval_index.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    print("== E: MMMU dev+val, MMMU-Pro (standard 10 + vision) ==", flush=True)
    d = WORK / "eval"
    hf_files("MMMU/MMMU", [f"{s}/dev-*" for s in SUBJECTS] + [f"{s}/validation-*" for s in SUBJECTS], d / "mmmu")
    hf_files("MMMU/MMMU_Pro", ["standard (10 options)/*", "vision/*"], d / "pro")
    (WORK / "thumbs").mkdir(parents=True, exist_ok=True)
    items, grams, exact, sha, ph, ph_eid, calib = {}, defaultdict(list), defaultdict(list), {}, [], [], []
    rng = np.random.default_rng(0)
    for it in eval_items(d):
        toks = norm_text(item_text(it["question"], it["options"]))
        items[it["eid"]] = str(it["question"])[:500]
        for g in ngrams(toks):
            grams[g].append(it["eid"])
        exact[" ".join(toks)].append(it["eid"])
        exact[" ".join(norm_text(it["question"]))].append(it["eid"])
        for im in it["images"] + it.get("shots", []):
            shot = any(im is x for x in it.get("shots", []))
            im = to_rgb(im)
            key = pixel_sha256(im)
            sha.setdefault(key, [])
            if it["eid"] not in sha[key]:
                sha[key].append(it["eid"])                   # MMMU-Pro reuses MMMU images: keep every owner
            if shot:          # a whole exam page: only an exact copy can match it, pHash would only add noise
                continue
            h = phash(im)
            if h is not None:
                n = len(ph)
                ph.append(h)
                ph_eid.append(it["eid"])
                th = im.copy()
                th.thumbnail((384, 384))
                th.save(WORK / "thumbs" / f"{n}.jpg", quality=85)
                if rng.random() < 0.1:                  # recall sample: edited copies of ~10% of E images
                    calib.append((n, edits(im, rng)))
    E = np.array(ph, np.uint64)
    r = {k: [] for k in ("resize", "jpeg", "crop", "all")}
    for n, ed in calib:
        for k, v in ed.items():
            h = phash(v)
            r[k].append(h is not None and int(hamming(np.array([h], np.uint64), E[n:n + 1])[0, 0]) <= MATCH
                        and same_picture(v, n))
    idx = {"version": 2, "items": items, "grams": grams, "exact": exact, "sha": sha, "phash": [str(x) for x in ph], "phash_eid": ph_eid,
           "recall_image": {k: round(float(np.mean(v)), 3) for k, v in r.items() if v}, "n_recall": len(calib)}
    out.write_text(json.dumps(idx), encoding="utf-8")
    print(f"  {sum(e.startswith('mmmu:') for e in items)} MMMU + {sum(e.startswith('pro:') for e in items)} Pro items, "
          f"{len(ph)} images, image recall {idx['recall_image']}", flush=True)
    return idx


def edits(im, rng):
    import io as _io
    w, h = im.size
    c = 0.05
    crop = im.crop((int(w * c), int(h * c), w - int(w * c), h - int(h * c)))
    small = im.resize((max(8, w // 2), max(8, h // 2)))
    b = _io.BytesIO()
    im.save(b, "JPEG", quality=40)
    jpg = Image.open(_io.BytesIO(b.getvalue())).convert("RGB")
    b = _io.BytesIO()
    crop.resize((max(8, crop.width // 2), max(8, crop.height // 2))).save(b, "JPEG", quality=40)
    return {"resize": small, "jpeg": jpg, "crop": crop, "all": Image.open(_io.BytesIO(b.getvalue())).convert("RGB")}


# --- one dataset -----------------------------------------------------------------------------------------------------
def source_files(name, spec):
    d = WORK / "data" / name
    if "repo" in spec:
        hf_files(spec["repo"], spec["files"], d)
        pats = [spec["read"]] if "read" in spec else [p for p in spec["files"] if not p.endswith(".zip")]
        return d, [f for p in pats for f in sorted(d.glob(p))]
    if "gdrive" in spec:
        import gdown
        d.mkdir(parents=True, exist_ok=True)
        if not list(d.glob("*.unpacked")):
            for fid in spec["gdrive"]:
                gdown.download(id=fid, output=str(d) + "/", quiet=False)
            import tarfile
            for t in list(d.glob("*.tar")) + list(d.glob("*.tar.gz")) + list(d.glob("*.zip")):
                (zipfile.ZipFile(t).extractall(d) if t.suffix == ".zip" else tarfile.open(t).extractall(d))
            (d / "done.unpacked").touch()
        if "read" in spec:
            return d, sorted(d.glob(spec["read"]))
        return d, sorted(f for f in d.rglob("*") if f.suffix in (".json", ".jsonl", ".csv") and f.stat().st_size > 1000)
    d = WORK / "data" / spec["local"]
    return d, sorted(f for f in d.rglob("*") if f.suffix in (".json", ".jsonl", ".csv", ".parquet"))


def check(name, spec, idx, E, eids):
    out = WORK / "results" / name
    if (out / "hits.json").exists() and (out / "meta.json").exists():     # detection done: just (re)grade
        return grade_one(name, spec, idx)
    print(f"== {name} ==", flush=True)
    root, files = source_files(name, spec)
    if not files:
        raise FileNotFoundError(f"no data files for {name} under {root}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "image_review").mkdir(exist_ok=True)
    fields = dict(kv.split("=", 1) for kv in spec.get("fields", "").split(",") if "=" in kv)
    where = dict(kv.split("=", 1) for kv in spec.get("where", "").split(",") if "=" in kv)
    rd = load_train.Reader(fields, root / spec["image_root"] if "image_root" in spec else root)
    hits, qcount, n, n_img, t0 = [], Counter(), 0, 0, time.time()
    for f in files:
        rows = (r for r in rows_of(f) if all(str(r.get(k)) == v for k, v in where.items()))
        for rec in rd.records(rows, subset=f.stem):
            n += 1
            q = " ".join(norm_text(rec["question"]))
            qcount[q] += 1
            toks = norm_text(item_text(rec["question"], rec["options"]))
            txt = set(idx["exact"].get(" ".join(toks), [])) | set(idx["exact"].get(q, [])) if len(toks) < NGRAM else \
                {e for g in ngrams(toks) for e in idx["grams"].get(g, [])}
            img_exact, img_near, review = set(), {}, {}
            if spec["images"]:
                for im in rec["images"]:
                    try:
                        im = to_rgb(im)
                    except Exception:
                        continue
                    n_img += 1
                    img_exact.update(idx["sha"].get(pixel_sha256(im), []))
                    h = phash(im)
                    if h is None or not len(E):
                        continue
                    dist = hamming(np.array([h], np.uint64), E)[0]
                    for k in np.argsort(dist)[:5]:
                        e, dk = eids[k], int(dist[k])
                        if dk > REVIEW or e in img_exact:
                            continue
                        if dk <= MATCH and same_picture(im, int(k)):
                            if dk < img_near.get(e, 99):
                                img_near[e] = dk
                                side_by_side(im, int(k), out / "image_review" / f"{safe(rec['tid'])}__{dk}.jpg")
                        elif dk < review.get(e, 99):
                            review[e] = dk
            if txt or img_exact or img_near or review:
                hits.append({"tid": rec["tid"], "subset": rec["subset"], "q": q, "question": rec["question"][:300],
                             "txt": sorted(txt), "img_exact": sorted(img_exact), "img_near": img_near, "review": review})
            if n % 20000 == 0:
                print(f"  {n} records, {n_img} images, {time.time() - t0:.0f}s", flush=True)
    templates = {q for q, c in qcount.items() if c >= TEMPLATE_MIN}
    for h in hits:
        h["template"] = h["q"] in templates
        del h["q"]
    (out / "hits.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "text_candidates.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["same(Y/N)", "tid", "eid", "train_question", "eval_question"])
        for h in hits:
            if h["txt"] and not (h["img_exact"] or h["img_near"]) and not h["template"]:
                for e in h["txt"]:
                    w.writerow(["", h["tid"], e, h["question"], idx["items"][e]])
    meta = {"records": n, "images": n_img, "seconds": round(time.time() - t0), "files": [str(f.name) for f in files]}
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"  {n} records, {n_img} images, {len(hits)} with a signal, {meta['seconds']}s", flush=True)
    return grade_one(name, spec, idx)


E_SIZE = {"mmmu": 900, "pro": 1730}     # section 2.3: inflation per MMMU val item / per MMMU-Pro item


def risk(rep, spec, idx, by_sub):
    """Section 2.3. r = smallest measured recall among the kinds that apply. Only image recall is measured here
    (pHash on edited E images), so text-only datasets with hits stay 'pending'."""
    k = rep["k"]
    if rep["pending"] or rep["img_pending"]:
        parts = ([f"이미지 후보 {rep['img_pending']}건"] if rep["img_pending"] else []) + \
                ([f"텍스트 후보 {rep['pending']}건"] if rep["pending"] else [])
        return {"verdict": f"판정 보류({', '.join(parts)} 사람 확인 필요)", "recall_r": None}
    if sum(k.values()) == 0:
        return {"verdict": "Safe", "recall_r": None}
    r = min(idx["recall_image"].values()) if spec["images"] and rep["images"] else None
    if not r:
        return {"verdict": "판정 보류(text recall 미측정)", "recall_r": None}
    infl = {b: round(100 * k[b] * (1 - r) / r / E_SIZE[b], 3) for b in k}
    out = {"recall_r": r, "residual_inflation_pp": infl,
           "verdict": "Risky" if max(infl.values()) >= 0.5 else "Use after removal"}
    tot = sum(by_sub.values())
    if len(by_sub) > 1 and by_sub.most_common(1)[0][1] > tot / 2:
        out["note"] = f"적중 과반이 subset {by_sub.most_common(1)[0][0]}: 그 subset 제외 후 재계산 권장"
    return out


def side_by_side(im, k, path):
    t = im.copy()
    t.thumbnail((384, 384))
    e = Image.open(WORK / "thumbs" / f"{k}.jpg")
    c = Image.new("RGB", (t.width + e.width + 8, max(t.height, e.height)), "white")
    c.paste(t, (0, 0))
    c.paste(e, (t.width + 8, 0))
    c.save(path, quality=85)


def safe(x):
    import re
    return re.sub(r'[<>:"/\\|?*\s]', "_", str(x))[:120]


def grade_one(name, spec, idx):
    """A = image+text, B = image only, C = text only confirmed by a person (same=Y in text_candidates.csv)."""
    out = WORK / "results" / name
    hits = json.loads((out / "hits.json").read_text(encoding="utf-8"))
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    said = {}
    with open(out / "text_candidates.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["same(Y/N)"].strip():
                said[(r["tid"], r["eid"])] = r["same(Y/N)"].strip().upper().startswith("Y")
    # pHash is coarse (two plain-background images can collide), so a pHash-only match counts after a person
    # looks at the pair: image_candidates.csv, one row per E item, the side-by-side picture is in image_review/
    ic = out / "image_candidates.csv"
    if not ic.exists():
        grp = defaultdict(list)
        for h in hits:
            for e, dist in h["img_near"].items():
                if e not in h["img_exact"]:
                    grp[e].append((h["tid"], dist))
        with open(ic, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["same(Y/N)", "eid", "n_records", "pHash", "picture (image_review/)", "tids"])
            for e, v in sorted(grp.items()):
                w.writerow(["", e, len(v), min(d for _, d in v), f"{safe(v[0][0])}__{v[0][1]}.jpg",
                            " ".join(t for t, _ in v[:50])])
    img_ok = {}
    with open(ic, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["same(Y/N)"].strip():
                img_ok[r["eid"]] = r["same(Y/N)"].strip().upper().startswith("Y")
    c, removed, k = Counter(), [], {"mmmu": set(), "pro": set()}
    for h in hits:
        near_pending = {e for e in h["img_near"] if e not in h["img_exact"] and e not in img_ok}
        c["img_pending"] += bool(near_pending)
        h["img_near"] = {e: d for e, d in h["img_near"].items() if e in h["img_exact"] or img_ok.get(e)}
        img = set(h["img_exact"]) | set(h["img_near"])
        txt = set(h["txt"]) & img if h["template"] else set(h["txt"])
        c["exact"] += bool(h["img_exact"])
        c["near"] += bool(h["img_near"] and not h["img_exact"])
        c["ngram"] += bool(txt)
        if img:
            g, e = ("A" if txt else "B"), img | txt
        elif txt:
            ok = {x for x in txt if said.get((h["tid"], x))}
            if not ok:
                c["pending"] += any((h["tid"], x) not in said for x in txt)
                continue
            g, e = "C", ok
        else:
            continue
        c[g] += 1
        removed.append(h["tid"])
        for x in e:
            k["pro" if x.startswith("pro:") else "mmmu"].add(x)
    N = meta["records"]
    by_sub = Counter(h["subset"] for h in hits if h["tid"] in set(removed))
    rep = {"records": N, "images": meta["images"], **{x: c[x] for x in ("exact", "near", "ngram", "A", "B", "C", "pending", "img_pending")},
           "removed": len(removed), "k": {b: len(v) for b, v in k.items()}, "hit_eids": {b: sorted(v) for b, v in k.items()},
           "review_band": sum(bool(h["review"]) for h in hits), "removed_by_subset": dict(by_sub)}
    rep.update(risk(rep, spec, idx, by_sub))
    imgs = spec["images"] and meta["images"] > 0
    how = ("이미지 검사 생략(합성: %s)" % spec["synthetic"] if spec.get("synthetic") else
           "이미지 검사 생략(%s)" % spec["textonly"] if spec.get("textonly") else
           "이미지 0장 읽힘, 필드 확인 필요" if not imgs else "near-dup은 pHash")
    rep["line"] = (f"exact {c['exact'] if imgs else '-'} · near-dup {c['near'] if imgs else '-'} · 13-gram {c['ngram']} · "
                   f"paraphrase - · A/B/C = {c['A']}/{c['B']}/{c['C']} · 제거 {len(removed)}건 "
                   f"({100 * len(removed) / max(1, N):.2f}%) · 적중 MMMU {rep['k']['mmmu']} / Pro {rep['k']['pro']} · "
                   f"{rep['verdict']} (간이 검사: {how}, paraphrase 미검사)")
    (out / "removed_ids.txt").write_text("\n".join(removed) + ("\n" if removed else ""), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  -> {rep['line']}", flush=True)
    return rep


# --- column 4 ----------------------------------------------------------------------------------------------------------
ROW = {"cosyn_music": "[CoSyn-400K music]", "musixqa": "[MusiXQA]", "cosyn_circuit": "[CoSyn-400K circuit]",
       "circuitvqa": "[CircuitVQA]", "cosyn_chemical": "[CoSyn-400K chemical]", "pathvqa": "[PathVQA]",
       "slake": "[SLAKE]", "vqarad": "[VQA-RAD]", "pubmedvision": "[PubMedVision]", "chemvqa": "[ChemVQA-2K]",
       "ssmr": "[SSMR-Bench", "nota": "[NOTA]", "openmmreasoner": "[OpenMMReasoner", "virl39k": "[ViRL39K]"}


def fill(md, lines, out):
    res = []
    for l in Path(md).read_text(encoding="utf-8").splitlines():
        cells = l.split("|")
        if l.startswith("| [") and len(cells) >= 7:
            key = next((k for k, p in ROW.items() if cells[1].strip().startswith(p) and k in lines), None)
            if key:
                cells[5] = f" {lines[key]} "
                l = "|".join(cells)
        res.append(l)
    Path(out).write_text("\n".join(res) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["all", "grade"])
    ap.add_argument("--only", default="")
    ap.add_argument("--md", default=str(HERE.parent / "dataset_search.md"))
    a = ap.parse_args()
    WORK.mkdir(exist_ok=True)
    idx = build_index()
    if idx.get("version") != 2:                    # index from an earlier version of this script
        (WORK / "eval_index.json").replace(WORK / "eval_index.old.json")
        print("E index format changed: rebuilding (about 4 min)", flush=True)
        idx = build_index()
    E = np.array([int(x) for x in idx["phash"]], np.uint64)
    names = [x for x in a.only.split(",") if x] or list(DATASETS)
    lines, failed = {}, {}
    for name in names:
        try:
            if a.cmd == "grade":
                rep = grade_one(name, DATASETS[name], idx) if (WORK / "results" / name / "hits.json").exists() else None
            else:
                rep = check(name, DATASETS[name], idx, E, idx["phash_eid"])
            if rep:
                lines[name] = rep["line"]
        except Exception as e:                      # one dataset failing must not stop the rest
            failed[name] = f"{type(e).__name__}: {e}"
            print(f"  !! {name} failed: {failed[name]}", flush=True)
            lines[name] = ("미검사 (데이터를 받지 못함" + (": IEEE DataPort 구독 필요" if name == "chemvqa" else "")
                           + (f". 합성({DATASETS[name]['synthetic']})이라 이미지 겹침 위험은 낮음" if DATASETS[name].get("synthetic") else "")
                           + ")") if isinstance(e, FileNotFoundError) else f"미검사 (오류: {type(e).__name__})"
    rec = idx["recall_image"]
    summary = {"lines": lines, "failed": failed, "image_recall_pHash": rec, "pHash_match": MATCH}
    (WORK / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if Path(a.md).exists():
        out = Path(a.md).with_name("dataset_search_filled.md")
        fill(a.md, lines, out)
        print(f"\n4열을 채운 표: {out}")
    print(f"이미지 recall(pHash, E 편집본): {rec}")
    if failed:
        print("실패:", json.dumps(failed, ensure_ascii=False, indent=1))
    pend = [n for n, l in lines.items() if "사람 확인 필요" in l]
    if pend:
        print(f"사람 확인 필요: {', '.join(pend)} -> decontam/qc_work/results/<이름>/ 의 image_candidates.csv(그림은 "
              f"image_review/)와 text_candidates.csv 의 same(Y/N) 칸을 채우고 `python decontam/quick_check.py grade` 실행")


if __name__ == "__main__":
    main()

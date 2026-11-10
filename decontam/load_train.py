"""Read one candidate dataset (T) as a stream of records: {tid, subset, question, options, images}.

Two sources:
  hf    --hf REPO [--config C] [--split S]    any HF dataset; fields are found automatically (override with --fields)
  json  --json FILE[,GLOB] [--image-root DIR] a .json list, .jsonl, .csv or .parquet (datasets shipped outside HF, or our own T)
  --where k=v       keep rows whose field k equals v (SLAKE: q_lang=en)
  --fields image=doc_id,image_pattern={}.png   image named by a field that holds an id, not a file name

Automatic field detection (print what was picked with --inspect):
  question  first of question/query/problem/prompt/text, else the first user turn of conversations/messages
  options   options/choices; SSMR-style correct_answer + incorrect_answer1..3
  images    every value that is a PIL image, an HF image dict, a list of those, or a path string to an image file
  QA lists  a list-of-dict field holding questions (CoSyn qa_pairs) becomes one record per question, same images
"""
import io
import json
from pathlib import Path

from PIL import Image

Q_KEYS = ("question", "query", "problem", "prompt", "Question", "text", "instruction")
CONV_KEYS = ("conversations", "messages", "conversation")
OPT_KEYS = ("options", "choices", "Choices")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")


def _is_img(v):
    return isinstance(v, Image.Image) or (isinstance(v, dict) and ("bytes" in v or "path" in v) and
                                          (v.get("bytes") or str(v.get("path", "")).lower().endswith(IMG_EXT)))


def _first_user_turn(conv):
    for t in conv or []:
        if not isinstance(t, dict):
            continue
        role = t.get("from", t.get("role", ""))
        if role in ("human", "user"):
            c = t.get("value", t.get("content", ""))
            if isinstance(c, list):        # OpenAI-style content parts
                c = " ".join(p.get("text") or "" for p in c if isinstance(p, dict))   # image parts have text=None
            return str(c)
    return ""


class Reader:
    def __init__(self, fields=None, image_root=None):
        self.f = dict(fields or {})
        self.root = Path(image_root) if image_root else None
        self.pattern = self.f.pop("image_pattern", None)
        self._by_name = None

    def _resolve(self, x):
        """A path string -> an existing file: as given, under --image-root, or by file name / stem anywhere below it."""
        p = Path(x)
        for c in ([p] + ([self.root / x] if self.root else [])):
            if c.is_file():
                return str(c)
        if not self.root:
            return None
        if self._by_name is None:
            self._by_name = {}
            for f in self.root.rglob("*"):
                if f.suffix.lower() in IMG_EXT:
                    self._by_name.setdefault("/".join(f.parts[-2:]), str(f))   # "xmlab102/source.jpg" (SLAKE)
                    self._by_name.setdefault(f.name, str(f))
                    self._by_name.setdefault(f.stem, str(f))
        if len(p.parts) >= 2:        # a relative path: never fall back to the bare file name (SLAKE: all are source.jpg)
            return self._by_name.get("/".join(p.parts[-2:]))
        return self._by_name.get(p.name) or self._by_name.get(p.stem)

    def _images(self, r):
        keys = [self.f["image"]] if "image" in self.f else list(r)
        out = []
        for k in keys:
            v = r.get(k)
            vs = v if isinstance(v, list) else [v]
            for x in vs:
                if self.pattern and k == self.f.get("image") and isinstance(x, (str, int)):
                    x = self.pattern.format(x)
                if _is_img(x):
                    out.append(x)
                elif isinstance(x, str) and (x.lower().endswith(IMG_EXT) or k == self.f.get("image")):
                    path = self._resolve(x)
                    if path:
                        out.append(path)
                    else:
                        self.missing = getattr(self, "missing", 0) + 1
        return out

    def _question(self, r):
        if "question" in self.f:
            return str(r.get(self.f["question"], ""))
        for k in Q_KEYS:
            if isinstance(r.get(k), str) and r[k].strip():
                return r[k]
        for k in CONV_KEYS:
            if isinstance(r.get(k), list):
                return _first_user_turn(r[k])
        return ""

    def _options(self, r):
        if "options" in self.f:
            return r.get(self.f["options"]) or []
        for k in OPT_KEYS:
            if r.get(k):
                return r[k]
        if "correct_answer" in r and any(k.startswith("incorrect_answer") for k in r):
            return [r["correct_answer"]] + [r[k] for k in sorted(r) if k.startswith("incorrect_answer") and
                                            isinstance(r[k], str)]
        return []

    def _qa_list(self, r):
        """CoSyn-style: a list (or dict-of-lists) of QA dicts under one image."""
        key = self.f.get("qa")
        cands = [key] if key else [k for k, v in r.items() if isinstance(v, (list, dict))]
        for k in cands:
            v = r.get(k)
            if isinstance(v, dict) and "question" in v and isinstance(v["question"], list):   # columnar
                return [dict(zip(v, vals)) for vals in zip(*v.values())]
            if isinstance(v, list) and v and isinstance(v[0], dict) and "question" in v[0]:
                return v
        return None

    def records(self, rows, subset=""):
        for i, r in enumerate(rows):
            rid = str(r.get("id", r.get("qid", i)))
            imgs = self._images(r)
            qas = None if any(isinstance(r.get(k), str) for k in Q_KEYS) else self._qa_list(r)
            if qas:
                for j, qa in enumerate(qas):
                    yield {"tid": f"{rid}#{j}", "subset": subset, "question": str(qa.get("question", "")),
                           "options": qa.get("options") or [], "images": imgs}
            else:
                yield {"tid": rid, "subset": subset, "question": self._question(r), "options": self._options(r),
                       "images": imgs}


def open_hf(repo, config=None, split=None, streaming=True):
    from datasets import get_dataset_split_names, load_dataset
    names = get_dataset_split_names(repo, config)
    if split:
        want = [x.strip() for x in split.split(",")]
        splits = [n for w in want for n in names if n.lower() == w.lower()]
        assert splits, f"split {split!r} not in {names}"
    else:
        splits = names
    for s in splits:
        yield s, load_dataset(repo, config, split=s, streaming=streaming)


def open_json(path):
    p = Path(path)
    if p.suffix == ".parquet":
        import pyarrow.parquet as pq
        return (row for b in pq.ParquetFile(p).iter_batches(batch_size=512) for row in b.to_pylist())
    if p.suffix == ".csv":
        import csv
        return csv.DictReader(open(p, encoding="utf-8", newline=""))
    if p.suffix == ".jsonl":
        return (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())
    d = json.loads(p.read_text(encoding="utf-8"))
    return d if isinstance(d, list) else d.get("data", d.get("annotations", []))


def stream(a):
    """All T records for the CLI arguments in `a` (hf/config/split/json/fields/image_root/limit)."""
    fields = dict(kv.split("=", 1) for kv in (a.fields or "").split(",") if "=" in kv)
    rd = Reader(fields, a.image_root)
    where = dict(kv.split("=", 1) for kv in (a.where or "").split(",") if "=" in kv)
    keep = (lambda r: all(str(r.get(k)) == v for k, v in where.items())) if where else (lambda r: True)
    n = 0
    if a.json:
        import glob   # glob.glob takes absolute patterns on every OS (pathlib.glob refuses "C:\\..." on Windows)
        files = [Path(f) for pat in a.json.split(",") for f in sorted(glob.glob(pat, recursive=True))] or [Path(a.json)]
        sources = [(f.stem, open_json(f)) for f in files]
    else:
        sources = [(f"{a.config or 'default'}/{s}", ds) for s, ds in open_hf(a.hf, a.config, a.split)]
    for name, rows in sources:
        for rec in rd.records((r for r in rows if keep(r)), subset=name):
            yield rec
            n += 1
            if a.limit and n >= a.limit:
                return


def inspect(a, k=3):
    for i, rec in enumerate(stream(a)):
        imgs = [type(x).__name__ if not isinstance(x, str) else x for x in rec["images"]]
        print(json.dumps({"tid": rec["tid"], "subset": rec["subset"], "question": rec["question"][:300],
                          "options": str(rec["options"])[:200], "images": imgs}, ensure_ascii=False, indent=1))
        if i + 1 >= k:
            break

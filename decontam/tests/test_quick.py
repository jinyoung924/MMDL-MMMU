"""Offline check of quick_check.py: fake MMMU/MMMU-Pro parquet files and a fake real-image dataset.

    python decontam/tests/test_quick.py      # PASS or the failed expectation
"""
import io
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quick_check as Q  # noqa: E402


def pic(seed, w=320, h=240):
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    for _ in range(12):
        x, y = rng.randrange(w), rng.randrange(h)
        d.rectangle([x, y, x + rng.randrange(20, 120), y + rng.randrange(20, 90)], fill=tuple(rng.randrange(256) for _ in range(3)))
    return im


def png(im, fmt="PNG", **kw):
    b = io.BytesIO()
    im.save(b, fmt, **kw)
    return {"bytes": b.getvalue(), "path": None}


def main():
    work = Path(tempfile.mkdtemp())
    Q.WORK = work
    Q.hf_files = lambda repo, pats, to: Path(to)          # no network
    Q.SUBJECTS = ["Physics"]
    eq = ["A uniform rod of length 2 m is pivoted at one end and released from rest at the horizontal position. Find the angular speed.",
          "How many resistors are connected in parallel between nodes a and b in the circuit shown in the figure?"]
    m = work / "eval" / "mmmu" / "Physics"
    m.mkdir(parents=True)
    rows = [{"id": f"validation_Physics_{i}", "question": f"<image 1> {q}", "options": "['1', '2']", "image_1": png(pic(i)),
             **{f"image_{k}": None for k in range(2, 8)}} for i, q in enumerate(eq)]
    pq.write_table(pa.Table.from_pylist(rows), m / "validation-0.parquet")
    p = work / "eval" / "pro" / "standard (10 options)"
    p.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([{"id": "test_Physics_9", "question": eq[0], "options": "['a']", "image_1": png(pic(0)),
                                          **{f"image_{k}": None for k in range(2, 8)}}]), p / "test-0.parquet")
    (work / "eval" / "pro" / "vision").mkdir(parents=True)
    # T: exact copy (A), jpeg+resize copy only (B), text-only copy (C candidate), clean
    t = work / "data" / "fake"
    t.mkdir(parents=True)
    small = pic(1).resize((160, 120))
    T = [{"id": "t0", "question": eq[0], "image": png(pic(0))},
         {"id": "t1", "question": "What period is this excerpt from?", "image": png(small, "JPEG", quality=60)},
         {"id": "t2", "question": "Consider: " + eq[1], "image": png(pic(50))},
         {"id": "t3", "question": "What is the boiling point of the drawn compound at 1 atm?", "image": png(pic(51))}]
    pq.write_table(pa.Table.from_pylist(T), t / "train.parquet")
    Q.DATASETS = {"fake": dict(local="fake", images=True), "fake_synth": dict(local="fake", images=False, synthetic="test")}
    idx = Q.build_index()
    import numpy as np
    E = np.array([int(x) for x in idx["phash"]], np.uint64)
    rep = Q.check("fake", Q.DATASETS["fake"], idx, E, idx["phash_eid"])
    assert (rep["A"], rep["B"], rep["pending"], rep["img_pending"]) == (1, 0, 1, 1), rep
    assert rep["k"] == {"mmmu": 1, "pro": 1}, rep["k"]
    assert "판정 보류(이미지 후보 1건, 텍스트 후보 1건" in rep["line"], rep["line"]
    # a person looks at both candidates and says "same" -> B and C count, verdict is computed
    for name in ("text_candidates.csv", "image_candidates.csv"):
        f = work / "results" / "fake" / name
        rows = f.read_text(encoding="utf-8-sig").splitlines()
        assert len(rows) == 2, (name, rows)
        f.write_text(rows[0] + "\n" + "Y" + rows[1] + "\n", encoding="utf-8-sig")
    rep = Q.grade_one("fake", Q.DATASETS["fake"], idx)
    assert (rep["A"], rep["B"], rep["C"], rep["pending"]) == (1, 1, 1, 0), rep
    assert " · Risky (간이 검사" in rep["line"] or " · Use after removal (간이 검사" in rep["line"], rep["line"]
    assert rep["line"].startswith("exact 1 · near-dup 1 · 13-gram 2 · paraphrase - · A/B/C = 1/1/1"), rep["line"]
    rs = Q.check("fake_synth", Q.DATASETS["fake_synth"], idx, E, idx["phash_eid"])
    assert "이미지 검사 생략(합성: test)" in rs["line"] and rs["line"].startswith("exact - · near-dup -"), rs["line"]
    print("line:", rep["line"])
    print("image recall:", idx["recall_image"])
    shutil.rmtree(work, ignore_errors=True)
    print("PASS")


if __name__ == "__main__":
    main()

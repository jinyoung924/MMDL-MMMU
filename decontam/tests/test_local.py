"""End-to-end check without network or GPU: fake E and T, tiny/hash embedders, dummy judge.

    python decontam/tests/test_local.py        # prints PASS or the first failed expectation
"""
import io
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1]
PY = sys.executable


def pic(seed, w=320, h=240):
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for _ in range(12):
        x0, y0 = rng.randrange(w), rng.randrange(h)
        d.rectangle([x0, y0, x0 + rng.randrange(20, 120), y0 + rng.randrange(20, 90)],
                    fill=tuple(rng.randrange(256) for _ in range(3)))
    return im


def run(*args):
    r = subprocess.run([PY, *map(str, args)], cwd=HERE, capture_output=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-3000:])
        raise SystemExit(f"FAIL: {' '.join(map(str, args[:2]))} exited {r.returncode}")
    return r.stdout


def main():
    d = Path(tempfile.mkdtemp())
    (d / "e").mkdir()
    (d / "t").mkdir()
    eq = ["A uniform rod of length 2 m is pivoted at one end and released from rest at the horizontal position. "
          "Find the angular speed when it passes the vertical.",
          "Which composer wrote the piece shown in the score, judging from the key signature and the ornamentation?",
          "How many resistors are connected in parallel between nodes a and b in the circuit shown?"]
    E = []
    for i, q in enumerate(eq):
        pic(i).save(d / "e" / f"{i}.png")
        E.append({"id": f"mmmu:validation_X_{i}", "bench": "mmmu", "question": f"<image 1> {q}",
                  "options": ["1 rad/s", "2 rad/s", "3 rad/s"], "images": [f"e/{i}.png"]})
    E.append({"id": "pro:test_Y_0", "bench": "pro", "question": eq[0], "options": [], "images": ["e/0.png"]})
    with open(d / "e.jsonl", "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(x) for x in E))

    # T: 0 exact image + same text (A), 1 resized+jpeg image only (B), 2 13-gram copy (C via judge),
    #    3 clean, 4..15 template question on new images (must stay D), 16 template on E image (A: text counts with image)
    T = []
    pic(0).save(d / "t" / "0.png")
    buf = io.BytesIO()
    pic(1).resize((160, 120)).save(buf, "JPEG", quality=50)
    Image.open(buf).save(d / "t" / "1.jpg")
    for k in range(2, 16):
        pic(100 + k).save(d / "t" / f"{k}.png")
    pic(2).save(d / "t" / "16.png")
    T.append({"id": "t0", "question": eq[0], "images": ["t/0.png"]})
    T.append({"id": "t1", "question": "Name the musical period of this excerpt.", "images": ["t/1.jpg"]})
    T.append({"id": "t2", "question": "Consider this: " + eq[0].lower(), "images": ["t/2.png"]})
    T.append({"id": "t3", "question": "What is the boiling point of the compound drawn here at 1 atm?", "images": ["t/3.png"]})
    for k in range(4, 16):
        T.append({"id": f"t{k}", "question": eq[2], "images": [f"t/{k}.png"]})
    T.append({"id": "t16", "question": eq[2], "images": ["t/16.png"]})
    with open(d / "t.jsonl", "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(x) for x in T))

    idx, out = d / "idx", d / "out"
    run("build_eval_index.py", "--out", idx, "--local", d / "e.jsonl", "--image-embedder", "tiny",
        "--text-embedder", "hash", "--calib-images", "4")
    run("check.py", "detect", "--index", idx, "--out", out, "--json", d / "t.jsonl", "--image-root", d, "--batch", "4")
    run("judge.py", "--cands", out / "judge_candidates.jsonl", "--backend", "dummy")
    run("check.py", "grade", "--out", out, "--verdicts", out / "verdicts.jsonl")
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    removed = set((out / "removed_ids.txt").read_text(encoding="utf-8").split())
    exp = {"t0", "t1", "t2", "t16"}
    assert removed == exp, f"removed {sorted(removed)} != {sorted(exp)}"
    assert (rep["A"], rep["B"], rep["C"]) == (2, 1, 1), rep
    assert rep["k"] == {"mmmu": 3, "pro": 1}, rep["k"]
    assert rep["verdict"].startswith("pending"), rep["verdict"]

    # recall on the same fake E: image copies must be found by the tiny embedder, text copies by n-gram/judge
    R = d / "recall"
    run("recall.py", "make", "--out", R, "--local", d / "e.jsonl", "--backend", "dummy", "--n", "5",
        "--kinds", "image,text")
    run("check.py", "detect", "--index", idx, "--out", R, "--json", R / "records.jsonl", "--image-root", R)
    run("judge.py", "--cands", R / "judge_candidates.jsonl", "--backend", "dummy")
    run("recall.py", "score", "--out", R)
    rc = json.loads((R / "recall.json").read_text(encoding="utf-8"))
    assert rc["r_by_kind"]["text"] == 1.0, rc
    run("check.py", "grade", "--out", out, "--verdicts", out / "verdicts.jsonl", "--recall", R / "recall.json",
        "--recall-kinds", "text")
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["verdict"] == "Use after removal", rep["verdict"]
    print("line:", rep["line"])
    print("recall:", rc["r_by_kind"])
    print("PASS")


if __name__ == "__main__":
    main()

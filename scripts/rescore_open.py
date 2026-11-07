#!/usr/bin/env python
"""Re-score open questions of finished runs with the current run_eval.py scorer (no GPU).

python scripts/rescore_open.py RUN_DIR [RUN_DIR ...]   # dirs holding predictions.jsonl + scores.json
Rewrites predictions.jsonl `correct`, scores.json (per_subject, overall_*) and table.md in place.
Multiple-choice rows are untouched (their scorer did not change).
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_eval import ANSWER_TAG_OPEN, eval_open, parse_open_response

assert eval_open("['Tampa', 'Florida']", parse_open_response("Tampa"))  # the 2026-11-06 bug


def rescore(d):
    d = Path(d)
    rows = [json.loads(l) for l in open(d / "predictions.jsonl")]
    sc = json.loads((d / "scores.json").read_text())
    cot = sc["config"].get("prompt_style") == "cot"
    flips = []
    for r in rows:
        if r["question_type"] == "multiple-choice":
            continue
        hits = ANSWER_TAG_OPEN.findall(r["response"]) if cot else []
        new = bool(eval_open(r["gold"], parse_open_response(hits[-1].strip() if hits else r["response"])))
        if new != r["correct"]:
            flips.append(f"{r['id']} {r['correct']}->{new}")
            r["correct"] = new
    if not flips:
        return print(f"{d}: unchanged")
    old = sc["overall_macro"]
    per = {}
    for r in rows:
        c, n = per.get(r["subject"], (0, 0))
        per[r["subject"]] = (c + r["correct"], n + 1)
    subjects = [s for s in sc["config"]["subjects"] if s in per]
    sc["per_subject"] = {s: {"correct": per[s][0], "num": per[s][1], "acc": per[s][0] / per[s][1]} for s in subjects}
    sc["overall_macro"] = sum(v["acc"] for v in sc["per_subject"].values()) / len(subjects)
    sc["overall_micro"] = sum(c for c, _ in per.values()) / len(rows)
    with open(d / "predictions.jsonl", "w") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    (d / "scores.json").write_text(json.dumps(sc, indent=2))
    lines = ["| No. | Subject | Data Num | Acc |", "|---|---|---|---|"]
    lines += [f"| {i} | {s} | {per[s][1]} | {sc['per_subject'][s]['acc']*100:.1f} |" for i, s in enumerate(subjects, 1)]
    lines.append(f"| | **Overall (macro avg)** | **{len(rows)}** | **{sc['overall_macro']*100:.2f}** |")
    (d / "table.md").write_text("\n".join(lines) + "\n")
    print(f"{d}: {old*100:.2f} -> {sc['overall_macro']*100:.2f}  ({', '.join(flips)})")


if __name__ == "__main__":
    for d in sys.argv[1:]:
        rescore(d)

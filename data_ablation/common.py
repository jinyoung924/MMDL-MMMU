"""Shared bits for the data-ablation pipeline.

Record format (one JSON object per line, used by every stage after prepare_data.py):
  id             unique string, "<source>:<...>"
  source         cosyn | vwi | pmcvqa (| anything a new adapter adds)
  images         list of image paths, relative to the jsonl's directory
  question       question text (and, for multiple-choice, the options are in `options`)
  question_type  "multiple-choice" | "open"
  options        {"A": "...", ...} for multiple-choice, {} otherwise
  answer         gold: option letter for multiple-choice, short string for open
  prompt         the full user text, built with run_eval.build_prompt(style="cot") -> same wording as evaluation
  response       assistant text for SFT: explanation + "\n\nAnswer: <answer>" (empty until self_cot.py fills it)
  meta           free dict (subset, keyword hits, ...)
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from run_eval import build_prompt, ANSWER_TAG_MC, ANSWER_TAG_OPEN  # noqa: E402  (same prompt + parser as eval)

LETTERS = "ABCDEFGHIJ"


def mmmu_sample(question, options, question_type):
    """Shape a record like an MMMU row so run_eval.build_prompt() can be reused unchanged."""
    return {"question": question, "options": repr(list(options)), "question_type": question_type}


def make_prompt(question, options, question_type):
    text, index2ans, all_choices = build_prompt(mmmu_sample(question, options, question_type), style="cot")
    return text, index2ans


def make_response(explanation, answer):
    """Explanation + the machine-readable last line the evaluation regex looks for."""
    explanation = (explanation or "").strip()
    answer = str(answer).strip()
    last = explanation.splitlines()[-1] if explanation else ""
    if ANSWER_TAG_OPEN.search(last):
        return explanation  # already ends with an "Answer: ..." line
    return (explanation + "\n\n" if explanation else "") + f"Answer: {answer}"


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def norm_text(s):
    return re.sub(r"[^a-z0-9 ]+", " ", str(s).lower()).split()


def ngrams(tokens, n):
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def git_commit():
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:
        return ""

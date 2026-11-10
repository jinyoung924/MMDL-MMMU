#!/usr/bin/env python
"""LLM judge for text-only matches (grade C), and the paraphrase/translation generator for recall.py.

    python decontam/judge.py --cands OUT/x/judge_candidates.jsonl        # -> OUT/x/verdicts.jsonl
    python decontam/judge.py --cands ... --backend dummy                   # tests: word-overlap rule, no model

The judge sees only the two question texts (images are compared elsewhere) and must say whether they are the same
problem: same quantities, same thing asked, possibly reworded or translated. A shared template sentence with
different numbers or a different object is NOT the same problem.
"""
import argparse
import json
from pathlib import Path

MODEL = "Qwen/Qwen2.5-7B-Instruct"
PROMPT = """Two exam questions follow. Decide whether they are the SAME problem: the same task with the same given \
values and the same thing asked, even if reworded, reordered or translated into another language. Questions that only \
share a template sentence but differ in numbers, objects or what is asked are DIFFERENT.

Question 1:
{a}

Question 2:
{b}

Reply with exactly one word: SAME or DIFFERENT."""


class LLM:
    def __init__(self, model=MODEL, backend="vllm"):
        self.backend = backend
        if backend == "vllm":
            from vllm import LLM as V, SamplingParams
            self.llm = V(model=model, max_model_len=4096, gpu_memory_utilization=0.85)
            self.SP = SamplingParams

    def chat(self, prompts, max_tokens=8, temperature=0.0):
        if self.backend == "dummy":
            return [dummy(p) for p in prompts]
        sp = self.SP(temperature=temperature, max_tokens=max_tokens, seed=0)
        outs = self.llm.chat([[{"role": "user", "content": p}] for p in prompts], sp, use_tqdm=False)
        return [o.outputs[0].text.strip() for o in outs]


def dummy(prompt):
    """Test stand-in: SAME when the two questions share >= 60% of their words."""
    from common import norm_text
    if "Question 1:" not in prompt:
        return prompt.split("\n\n", 1)[-1]          # paraphrase request: echo the text
    a = prompt.split("Question 1:\n", 1)[1].split("\n\nQuestion 2:", 1)[0]
    b = prompt.split("Question 2:\n", 1)[1].split("\n\nReply", 1)[0]
    x, y = set(norm_text(a)), set(norm_text(b))
    return "SAME" if x and y and len(x & y) / max(len(x), len(y)) >= 0.6 else "DIFFERENT"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cands", required=True)
    ap.add_argument("--out", help="default: verdicts.jsonl next to --cands")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--backend", default="vllm", choices=["vllm", "dummy"])
    a = ap.parse_args()
    cands = [json.loads(l) for l in open(a.cands, encoding="utf-8")]
    out = Path(a.out or Path(a.cands).with_name("verdicts.jsonl"))
    if not cands:
        out.write_text("", encoding="utf-8")
        print("[judge] no candidates")
        return
    llm = LLM(a.model, a.backend)
    ans = llm.chat([PROMPT.format(a=c["t_question"][:1500], b=c["e_question"][:1500]) for c in cands])
    n_same = 0
    with open(out, "w", encoding="utf-8") as f:
        for c, x in zip(cands, ans):
            same = x.upper().startswith("SAME")
            n_same += same
            f.write(json.dumps({"tid": c["tid"], "eid": c["eid"], "same": same, "raw": x[:20]}, ensure_ascii=False) + "\n")
    print(f"[judge] {n_same}/{len(cands)} judged SAME -> {out}")


if __name__ == "__main__":
    main()

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


SMALL = "Qwen/Qwen2.5-3B-Instruct"   # GPUs under 20 GB (Colab T4/L4): the 7B does not fit in fp16


def pick(model=None, backend="auto"):
    """auto: vLLM when installed (RunPod), else plain transformers (Colab). model None: 7B, or 3B on a small GPU."""
    if backend == "auto":
        try:
            import vllm  # noqa: F401
            backend = "vllm"
        except ImportError:
            backend = "hf"
    if model is None:
        model = MODEL
        if backend == "hf":
            import torch
            if not torch.cuda.is_available() or torch.cuda.get_device_properties(0).total_memory < 20e9:
                model = SMALL
    return model, backend


class LLM:
    def __init__(self, model=None, backend="auto"):
        model, backend = pick(model, backend)
        self.backend, self.model = backend, model
        print(f"[llm] {backend} {model}", flush=True)
        if backend == "vllm":
            from vllm import LLM as V, SamplingParams
            self.llm = V(model=model, max_model_len=4096, gpu_memory_utilization=0.85)
            self.SP = SamplingParams
        elif backend == "hf":
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self.torch = torch
            self.tok = AutoTokenizer.from_pretrained(model, padding_side="left")
            bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
            self.m = AutoModelForCausalLM.from_pretrained(
                model, torch_dtype=torch.bfloat16 if bf16 else torch.float16,
                device_map="cuda" if torch.cuda.is_available() else None).eval()

    def chat(self, prompts, max_tokens=8, temperature=0.0):
        if self.backend == "dummy":
            return [dummy(p) for p in prompts]
        if self.backend == "hf":
            return self._hf(prompts, max_tokens, temperature)
        sp = self.SP(temperature=temperature, max_tokens=max_tokens, seed=0)
        outs = self.llm.chat([[{"role": "user", "content": p}] for p in prompts], sp, use_tqdm=False)
        return [o.outputs[0].text.strip() for o in outs]

    def _hf(self, prompts, max_tokens, temperature, batch=16):
        torch, out = self.torch, []
        torch.manual_seed(0)
        texts = [self.tok.apply_chat_template([{"role": "user", "content": p}], tokenize=False,
                                              add_generation_prompt=True) for p in prompts]
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))     # similar lengths per batch = less padding
        res = {}
        for b in range(0, len(order), batch):
            ids = order[b:b + batch]
            x = self.tok([texts[i] for i in ids], return_tensors="pt", padding=True).to(self.m.device)
            with torch.no_grad():
                y = self.m.generate(**x, max_new_tokens=max_tokens, do_sample=temperature > 0,
                                    temperature=temperature if temperature > 0 else None, top_p=None, top_k=None,
                                    pad_token_id=self.tok.eos_token_id)
            for i, row in zip(ids, y[:, x["input_ids"].shape[1]:]):
                res[i] = self.tok.decode(row, skip_special_tokens=True).strip()
            if (b // batch) % 50 == 0:
                print(f"[llm] {min(b + batch, len(order))}/{len(order)}", flush=True)
        return [res[i] for i in range(len(texts))]


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
    ap.add_argument("--model", default=None, help=f"default {MODEL}, or {SMALL} on a GPU under 20 GB without vLLM")
    ap.add_argument("--backend", default="auto", choices=["auto", "vllm", "hf", "dummy"])
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

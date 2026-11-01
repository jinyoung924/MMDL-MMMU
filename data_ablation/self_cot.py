#!/usr/bin/env python
"""Fill `response` by rejection sampling from the base model itself (RFT / STaR style).

python data_ablation/self_cot.py --data runs/abl_pmcvqa/data            # clean.jsonl -> sft.jsonl
python data_ablation/self_cot.py --data runs/abl_cosyn/data --overwrite  # replace dataset explanations too

For every record the base model answers the SAME prompt the evaluation would show (CoT instruction, eval sampling
recipe), --n-samples times. A sample counts as correct when the evaluation parser extracts the gold answer
(run_eval.py's regex + MMMU official parser). The shortest correct, non-truncated sample becomes the response.
Records with no correct sample are dropped (reported), so SFT only sees solutions in the model's own words and
format. Records that already have a response are left alone unless --overwrite.
"""
import argparse, json, os, sys, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, read_jsonl, write_jsonl  # noqa: E402
sys.path.insert(0, str(ROOT))
from run_eval import (ANSWER_TAG_MC, ANSWER_TAG_OPEN, MODEL_REV, eval_open, parse_multi_choice_response,  # noqa: E402
                      parse_open_response)


def is_correct(rec, text):
    if rec["question_type"] == "multiple-choice":
        hits = ANSWER_TAG_MC.findall(text)
        cand = hits[-1].upper() if hits else None
        if cand not in rec["options"]:
            cand, guessed = parse_multi_choice_response(text, list(rec["options"]), rec["options"])
            if guessed:
                return False
        return cand == rec["answer"]
    hits = ANSWER_TAG_OPEN.findall(text)
    pred = parse_open_response(hits[-1].strip() if hits else text)
    return bool(eval_open(rec["answer"], pred))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--inp", default="clean.jsonl")
    ap.add_argument("--out", default="sft.jsonl")
    ap.add_argument("--model", default="Qwen/Qwen3-VL-4B-Instruct")
    ap.add_argument("--model-revision", default=MODEL_REV)
    ap.add_argument("--n-samples", type=int, default=4)
    ap.add_argument("--max-new-tokens", type=int, default=4096)
    ap.add_argument("--max-pixels", type=int, default=1280 * 32 * 32)
    ap.add_argument("--min-pixels", type=int, default=4 * 32 * 32)
    ap.add_argument("--max-model-len", type=int, default=12288)
    ap.add_argument("--gpu-mem-util", type=float, default=0.90)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--overwrite", action="store_true", help="also re-generate records that already have a response")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    rows = read_jsonl(a.data / a.inp)
    if a.limit:
        rows = rows[:a.limit]
    todo = [r for r in rows if a.overwrite or not r["response"]]
    print(f"[self_cot] {len(rows)} records, generating for {len(todo)}", flush=True)
    if not todo:
        write_jsonl(a.data / a.out, rows)
        return

    from PIL import Image
    from transformers import AutoProcessor
    from vllm import LLM, SamplingParams
    is_local = os.path.isdir(a.model)
    rev = None if is_local else a.model_revision
    proc = AutoProcessor.from_pretrained(a.model, revision=rev, min_pixels=a.min_pixels, max_pixels=a.max_pixels)
    prompts = []
    for r in todo:
        content = [{"type": "image"} for _ in r["images"]] + [{"type": "text", "text": r["prompt"]}]
        chat = proc.apply_chat_template([{"role": "user", "content": content}], add_generation_prompt=True, tokenize=False)
        imgs = [Image.open(a.data / p).convert("RGB") for p in r["images"]]
        prompts.append({"prompt": chat, "multi_modal_data": {"image": imgs}})
    llm = LLM(model=a.model, revision=rev, dtype="auto", trust_remote_code=True, max_model_len=a.max_model_len,
              gpu_memory_utilization=a.gpu_mem_util, limit_mm_per_prompt={"image": 7}, seed=a.seed,
              mm_processor_kwargs={"min_pixels": a.min_pixels, "max_pixels": a.max_pixels})
    # eval recipe (reports/mmmu_baseline.md §3.1) + n samples per prompt
    sp = SamplingParams(n=a.n_samples, temperature=0.7, top_p=0.8, top_k=20, repetition_penalty=1.0,
                        presence_penalty=1.5, max_tokens=a.max_new_tokens, seed=a.seed)
    t0 = time.time()
    outs = llm.generate(prompts, sp)
    print(f"[self_cot] generated in {(time.time() - t0) / 60:.1f} min", flush=True)

    kept, pass_hist, dropped = [], Counter(), 0
    for r, o in zip(todo, outs):
        good = [c.text.strip() for c in o.outputs if c.finish_reason == "stop" and is_correct(r, c.text)]
        n_ok = sum(is_correct(r, c.text) for c in o.outputs)
        pass_hist[n_ok] += 1
        if not good:
            dropped += 1
            continue
        r = dict(r)
        r["response"] = min(good, key=len)
        r["meta"] = {**r.get("meta", {}), "self_cot": True, "pass_rate": n_ok / a.n_samples}
        kept.append(r)
    done_ids = {r["id"] for r in todo}
    final = [r for r in rows if r["id"] not in done_ids] + kept
    write_jsonl(a.data / a.out, final)
    stats = {"input": len(rows), "generated_for": len(todo), "kept": len(kept), "dropped_no_correct": dropped,
             "pass_count_hist": {str(k): v for k, v in sorted(pass_hist.items())}, "n_samples": a.n_samples,
             "max_new_tokens": a.max_new_tokens, "model": a.model, "elapsed_min": round((time.time() - t0) / 60, 1)}
    (a.data / "self_cot_report.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()

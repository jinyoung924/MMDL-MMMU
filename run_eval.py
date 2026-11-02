#!/usr/bin/env python
"""MMMU-val baseline evaluation for Qwen3-VL-4B-Instruct (vLLM offline batch).

One command, one file. Swap --model to re-run on a fine-tuned checkpoint later.
See reports/mmmu_baseline.md for every pipeline choice and its justification.
"""
import argparse, ast, json, os, random, re, sys, time
from collections import defaultdict
from pathlib import Path

MODEL_REV = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
DATA_REV = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"
SUBJECTS = """Accounting Agriculture Architecture_and_Engineering Art Art_Theory
Basic_Medical_Science Biology Chemistry Clinical_Medicine Computer_Science
Design Diagnostics_and_Laboratory_Medicine Economics Electronics
Energy_and_Power Finance Geography History Literature Manage
Marketing Materials Math Mechanical_Engineering Music Pharmacy
Physics Psychology Public_Health Sociology""".split()

# --- Prompt (MMMU official repo, mmmu/configs/llava1.5.yaml) ------------------
MC_SUFFIX = "Answer with the option's letter from the given choices directly."
OPEN_SUFFIX = "Answer the question using a single word or phrase."
# --- Prompt variant B: allow CoT but force a machine-readable final line (self-designed) ---
COT_MC_SUFFIX = ('Think step by step, then give your final answer on the last line in exactly '
                 'this format: "Answer: X"  (X = the letter of the correct option).')
COT_OPEN_SUFFIX = ('Think step by step, then give your final answer on the last line in exactly '
                   'this format: "Answer: <single word or phrase>".')
# (?![A-Za-z]) : the letter must stand alone, else "Final Answer:\nAnswer: C" captures the A of "Answer"
ANSWER_TAG_MC = re.compile(r"Answer:\s*\(?\s*([A-Za-z])(?![A-Za-z])", re.IGNORECASE)
ANSWER_TAG_OPEN = re.compile(r"Answer:\s*(.+)", re.IGNORECASE)
IMG_TAG = re.compile(r"<image (\d+)>")


def build_prompt(sample, style="mmmu"):
    """MMMU official construct_prompt(): question, '(A) opt' lines, then the suffix.

    style="cot" swaps only the trailing instruction; question/option assembly is identical,
    so the two variants differ by exactly one sentence.
    """
    cot = style == "cot"
    q = sample["question"].strip()
    if sample["question_type"] == "multiple-choice":
        options = ast.literal_eval(sample["options"])
        index2ans = {chr(65 + i): o for i, o in enumerate(options)}
        body = q + "\n" + "".join(f"({k}) {v}\n" for k, v in index2ans.items())
        return body + (COT_MC_SUFFIX if cot else MC_SUFFIX), index2ans, list(index2ans)
    return q + "\n" + (COT_OPEN_SUFFIX if cot else OPEN_SUFFIX), {}, []


def interleave(text, sample):
    """Split on <image N> placeholders, splice the PIL images in at those spots.

    Images present on the row but never referenced are appended at the end so
    they are never silently dropped.
    """
    imgs = {i: sample[f"image_{i}"] for i in range(1, 8) if sample.get(f"image_{i}")}
    content, used, pos = [], set(), 0
    for m in IMG_TAG.finditer(text):
        n = int(m.group(1))
        if n not in imgs:
            continue
        if text[pos:m.start()]:
            content.append({"type": "text", "text": text[pos:m.start()]})
        content.append({"type": "image"})
        used.add(n)
        pos = m.end()
    if text[pos:]:
        content.append({"type": "text", "text": text[pos:]})
    order = [int(m.group(1)) for m in IMG_TAG.finditer(text) if int(m.group(1)) in imgs]
    extra = [n for n in sorted(imgs) if n not in used]
    content += [{"type": "image"} for _ in extra]
    return content, [imgs[n] for n in order] + [imgs[n] for n in extra]


# --- Parsing (MMMU official repo, mmmu/utils/eval_utils.py, verbatim) ---------
def parse_multi_choice_response(response, all_choices, index2ans):
    for char in [",", ".", "!", "?", ";", ":", "'"]:
        response = response.strip(char)
    response = " " + response + " "
    index_ans, ans_with_brack, candidates = True, False, []
    for choice in all_choices:
        if f"({choice})" in response:
            candidates.append(choice)
            ans_with_brack = True
    if len(candidates) == 0:
        for choice in all_choices:
            if f" {choice} " in response:
                candidates.append(choice)
    if len(candidates) == 0 and len(response.split()) > 5:
        for index, ans in index2ans.items():
            if ans.lower() in response.lower():
                candidates.append(index)
                index_ans = False
    if len(candidates) == 0:
        return random.choice(all_choices), True  # guessed
    if len(candidates) > 1:
        starts = []
        for can in candidates:
            if index_ans:
                starts.append(response.rfind(f"({can})" if ans_with_brack else f" {can} "))
            else:
                starts.append(response.lower().rfind(index2ans[can].lower()))
        return candidates[starts.index(max(starts))], False
    return candidates[0], False


def check_is_number(string):
    try:
        float(string.replace(",", ""))
        return True
    except ValueError:
        return False


def normalize_str(string):
    string = string.strip()
    is_number = check_is_number(string)
    if is_number:
        string = string.replace(",", "")
        string = float(string)
        string = round(string, 2)
        return [string]
    return [string.lower(), " " + string.lower(), string.lower() + " "]


def extract_numbers(string):
    pattern_commas = r"-?\b\d{1,3}(?:,\d{3})+\b"
    pattern_scientific = r"-?\d+(?:\.\d+)?[eE][+-]?\d+"
    pattern_simple = r"-?(?:\d+\.\d+|\.\d+|\d+\b)(?![eE][+-]?\d+)(?![,\d])"
    return (re.findall(pattern_commas, string) + re.findall(pattern_scientific, string)
            + re.findall(pattern_simple, string))


def parse_open_response(response):
    def get_key_subresponses(response):
        response = response.strip().strip(".").lower()
        sub_responses = re.split(r"\.\s(?=[A-Z])|\n", response)
        indicators = ["could be ", "so ", "is ", "thus ", "therefore ", "final ", "answer ", "result "]
        key_responses = []
        for index, resp in enumerate(sub_responses):
            indic = indicators + ["="] if index == len(sub_responses) - 1 else indicators
            shortest = None
            for ind in indic:
                if ind in resp:
                    cand = resp.split(ind)[-1].strip()
                    if shortest is None or len(cand) < len(shortest):
                        shortest = cand
            if shortest and shortest.strip() not in [":", ",", ".", "!", "?", ";", "'"]:
                key_responses.append(shortest)
        return key_responses or [response]

    pred_list = get_key_subresponses(response)
    for resp in list(pred_list):
        pred_list.extend(extract_numbers(resp))
    out = []
    for p in pred_list:
        out.extend(normalize_str(p))
    return list(set(out))


def eval_open(gold_i, pred_i):
    norm_answers = []
    for answer in (gold_i if isinstance(gold_i, list) else [gold_i]):
        norm_answers.extend(normalize_str(answer))
    for pred in pred_i:
        if isinstance(pred, str):
            if any(isinstance(n, str) and n in pred for n in norm_answers):
                return True
        elif pred in norm_answers:
            return True
    return False


# --- Main --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-VL-4B-Instruct", help="HF repo id or local checkpoint dir")
    ap.add_argument("--model-revision", default=MODEL_REV, help="ignored for local dirs")
    ap.add_argument("--data", default="MMMU/MMMU")
    ap.add_argument("--data-revision", default=DATA_REV)
    ap.add_argument("--out", default="results")
    ap.add_argument("--subjects", nargs="*", default=SUBJECTS)
    ap.add_argument("--limit", type=int, default=0, help="per-subject cap, smoke test only")
    ap.add_argument("--prompt-style", choices=["mmmu", "cot"], default="cot",
                    help="mmmu = MMMU official 'answer directly'; cot = step-by-step + 'Answer: X' line")
    # generation budget / resolution: engineering knobs, see reports/mmmu_baseline.md §3.2
    ap.add_argument("--max-new-tokens", type=int, default=8192)
    ap.add_argument("--max-pixels", type=int, default=1280 * 32 * 32)
    ap.add_argument("--min-pixels", type=int, default=4 * 32 * 32)
    ap.add_argument("--max-model-len", type=int, default=24576)
    ap.add_argument("--gpu-mem-util", type=float, default=0.90)
    # Qwen official VL recipe (reports/mmmu_baseline.md §3.1)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--repetition-penalty", type=float, default=1.0)
    ap.add_argument("--presence-penalty", type=float, default=1.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--batch-invariant", type=int, default=1,
                    help="1 = VLLM_BATCH_INVARIANT: same seed -> identical output regardless of batching (~1.7x slower)")
    ap.add_argument("--ids-file", default="", help="only these question ids (one per line); ablations only")
    args = ap.parse_args()

    # Must be set before vLLM spawns its engine process. Without it, the same seed gives different
    # outputs run to run (batch composition changes bf16 reductions) — report §3.1.
    os.environ["VLLM_BATCH_INVARIANT"] = str(args.batch_invariant)
    random.seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from datasets import load_dataset
    from transformers import AutoProcessor
    from vllm import LLM, SamplingParams

    is_local = os.path.isdir(args.model)
    rev = None if is_local else args.model_revision
    proc = AutoProcessor.from_pretrained(args.model, revision=rev,
                                         min_pixels=args.min_pixels, max_pixels=args.max_pixels)

    print(f"[load] {len(args.subjects)} subject configs from {args.data}@{args.data_revision[:8]}", flush=True)
    keep = set(Path(args.ids_file).read_text().split()) if args.ids_file else None
    rows = []
    for s in args.subjects:
        ds = load_dataset(args.data, s, split="validation", revision=args.data_revision)
        if args.limit:
            ds = ds.select(range(min(args.limit, len(ds))))
        for r in ds:
            if keep is not None and r["id"] not in keep:
                continue
            r["__subject"] = s
            rows.append(r)
    print(f"[load] {len(rows)} questions", flush=True)

    prompts, meta = [], []
    for r in rows:
        text, index2ans, all_choices = build_prompt(r, args.prompt_style)
        content, images = interleave(text, r)
        chat = proc.apply_chat_template([{"role": "user", "content": content}],
                                        add_generation_prompt=True, tokenize=False)
        prompts.append({"prompt": chat, "multi_modal_data": {"image": images}} if images
                       else {"prompt": chat})
        meta.append((r, text, index2ans, all_choices))

    llm = LLM(model=args.model, revision=rev, dtype="auto", trust_remote_code=True,
              max_model_len=args.max_model_len, gpu_memory_utilization=args.gpu_mem_util,
              limit_mm_per_prompt={"image": 7}, seed=args.seed,
              mm_processor_kwargs={"min_pixels": args.min_pixels, "max_pixels": args.max_pixels})
    sp = SamplingParams(temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
                        repetition_penalty=args.repetition_penalty,
                        presence_penalty=args.presence_penalty,
                        max_tokens=args.max_new_tokens, seed=args.seed)

    t0 = time.time()
    outs = llm.generate(prompts, sp)
    elapsed = time.time() - t0

    per_subject = defaultdict(lambda: [0, 0])
    n_trunc = n_guess = n_tagged = 0
    with open(out / "predictions.jsonl", "w") as f:
        for o, (r, text, index2ans, all_choices) in zip(outs, meta):
            resp = o.outputs[0].text.strip()
            trunc = o.outputs[0].finish_reason == "length"
            n_trunc += trunc
            cot = args.prompt_style == "cot"
            tagged = False
            if r["question_type"] == "multiple-choice":
                hits = ANSWER_TAG_MC.findall(resp) if cot else []
                cand = hits[-1].upper() if hits else None
                if cand in all_choices:
                    pred, guessed, tagged = cand, False, True
                else:  # tag missing/invalid -> same official parser as the mmmu variant
                    pred, guessed = parse_multi_choice_response(resp, all_choices, index2ans)
                correct = pred == r["answer"]
            else:
                hits = ANSWER_TAG_OPEN.findall(resp) if cot else []
                tagged = bool(hits)
                pred, guessed = parse_open_response(hits[-1].strip() if hits else resp), False
                correct = eval_open(r["answer"], pred)
            n_tagged += tagged
            n_guess += guessed
            s = r["__subject"]
            per_subject[s][0] += correct
            per_subject[s][1] += 1
            f.write(json.dumps({"id": r["id"], "subject": s, "question_type": r["question_type"],
                                "subfield": r["subfield"], "img_type": ast.literal_eval(r["img_type"]),
                                "topic_difficulty": r["topic_difficulty"],
                                "prompt": text, "response": resp, "parsed": pred if isinstance(pred, str) else None,
                                "gold": r["answer"], "correct": bool(correct),
                                "truncated": trunc, "fallback_guess": guessed,
                                "answer_tag_found": tagged}, ensure_ascii=False) + "\n")

    accs = {s: per_subject[s][0] / per_subject[s][1] for s in args.subjects if per_subject[s][1]}
    overall = sum(accs.values()) / len(accs)
    micro = sum(v[0] for v in per_subject.values()) / sum(v[1] for v in per_subject.values())
    scores = {"per_subject": {s: {"correct": per_subject[s][0], "num": per_subject[s][1],
                                  "acc": accs[s]} for s in accs},
              "overall_macro": overall, "overall_micro": micro,
              "n_questions": len(rows), "elapsed_sec": round(elapsed, 1),
              "truncated": n_trunc, "fallback_guess": n_guess, "answer_tag_found": n_tagged,
              "config": vars(args)}
    (out / "scores.json").write_text(json.dumps(scores, indent=2))

    lines = ["| No. | Subject | Data Num | Acc |", "|---|---|---|---|"]
    for i, s in enumerate([s for s in args.subjects if s in accs], 1):
        lines.append(f"| {i} | {s} | {per_subject[s][1]} | {accs[s]*100:.1f} |")
    lines.append(f"| | **Overall (macro avg)** | **{len(rows)}** | **{overall*100:.2f}** |")
    table = "\n".join(lines)
    (out / "table.md").write_text(table + "\n")
    print(table)
    print(f"\nstyle={args.prompt_style}  macro={overall*100:.2f}  micro={micro*100:.2f}  "
          f"truncated={n_trunc}  fallback_guess={n_guess}  answer_tag={n_tagged}  "
          f"elapsed={elapsed/60:.1f}min")


if __name__ == "__main__":
    main()

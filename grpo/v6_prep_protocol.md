# v6 preparation checks — registered before any result (2026-11-05)

User decision (2026-11-05): check student / teacher / judge before designing v6. Using Qwen3-VL-8B-Thinking as a
teacher is allowed (user); only the submitted model must have no external layers or modules.
All runs below are diagnostics on MMMU val (evaluation only, never training data), seed 0, 900 questions,
run_eval.py defaults except where noted; --gpu-mem-util 0.80 (BI mode; leaves room for the user's GPU jobs).

| Check | Run | Adopt if |
|---|---|---|
| A. Student + ASD-STE100-style instruction | `grpo/ste_eval.py` (base model; CoT suffix replaced, text in `prompt_variant.txt`) -> `runs/diag_ste_base/seed0` | accuracy > base 5-seed mean 64.93 AND truncation < base 15.31 % -> STE style becomes a v6 ingredient (context distillation) |
| B1. Teacher 8B-Instruct-FP8 | run_eval.py `--model Qwen/Qwen3-VL-8B-Instruct-FP8` @9cdc6310 -> `runs/diag_teacher_8b_instruct_fp8/seed0` | accuracy >= 66.93 (base mean + 2, > 2 seed SD) -> teacher candidate |
| B2. Teacher 8B-Thinking-FP8 | run_eval.py `--model Qwen/Qwen3-VL-8B-Thinking-FP8` @a6638e84 -> `runs/diag_teacher_8b_thinking_fp8/seed0` | same; truncation reported (8,192-token budget may cut its thinking) |
| C. Judge | re-validate on STE-style answers only if A is adopted | the original judge gate |

Check A changes the prompt, so it is not a model comparison: it only asks whether the style can help this model.
Results are compared paired per question against the base 5-seed mean (analyze.py refuses differing settings).

## Result A (2026-11-05 15:41) — NOT adopted
STE instruction, base model, seed 0: accuracy 59.33 vs 64.93 (Δ −5.60 ± 1.40 paired SE); truncation 2.67 % vs
15.31 %; mean response 1,347 vs 7,664 chars; finished accuracy 59.9 %. Fails the accuracy condition -> STE style is
not a v6 ingredient and check C is not run. Descriptive: by base truncation rate, never truncated (676 q) 72.3 -> 64.2,
1-2/5 (95 q) 49.7 -> 44.2, >=3/5 (129 q) 37.5 -> 45.0 (bins are defined on the base runs themselves, so the base
accuracy in the >=3/5 bin is biased low; the gain there is suggestive only).

## Result B1 (2026-11-05 16:37) — PASSES (teacher candidate)
8B-Instruct-FP8, seed 0: accuracy 68.33 vs 64.93 (Δ +3.40 ± 1.22 paired SE) >= 66.93 -> teacher candidate.
Truncation 8.11 %; finished accuracy 71.6 %; mean response 5,786 chars. Teacher accuracy by student 5-seed group
(teacher run independent of the grouping): 5/5 (430 q) 95.6 %, 4/5 (88 q) 69.3 %, 1-3/5 (216 q) 52.8 %,
0/5 (166 q) 17.5 % (29 q). Lower teacher accuracy on 4/5-5/5 is partly selection (groups chosen on student successes).

## Result B2 (2026-11-05 18:24) — NOT adopted (registered rule)
8B-Thinking-FP8, seed 0: accuracy 65.78 vs 64.93 (Δ +0.84 ± 1.31 paired SE) < 66.93 -> not a teacher candidate.
Truncation 18.78 % (169 q; truncated accuracy 30.2 %) at the 8,192-token budget; finished accuracy 74.0 % (highest of
all runs); mean response 11,725 chars. By student group: 5/5 94.0 %, 4/5 61.4 %, 1-3/5 47.2 %, 0/5 19.3 % (32 q).
Descriptive only: either teacher (B1 or B2, one sample each) is correct on 151/216 of the 1-3/5 group and 48/166 of the
0/5 group (two samples, so this is a pass@2-style upper figure). A larger budget for B2 would be a new check, not a
change to this one.

# GRPO v6 protocol — on-policy distillation from 8B-Instruct + outcome reward, domain-matched data

Registered 2026-11-05, before any v6 rollout or teacher screen. Nothing below changes after results are seen
without the user's decision; any change is recorded as a numbered amendment.

User decisions (2026-11-05): teacher signal = on-policy distillation + outcome reward; Sonnet fully removed
(no judge, no hints); the data-only ablation runs only if v6 gives a dev candidate.

## Why (causes this run targets)
- v1-v5 gave no full-900 gain (v5 r007 dev 63.44 vs base 64.93). Two diagnosed causes:
  1. Domain mismatch: pool_v4 is ~50 % geometry/math, while 32 % of the maj@5 headroom is Business and 31 % Tech & Eng.
  2. Sparse signal: only groups with outcome spread train (v5: 22 of 38 finished groups); an all-wrong group teaches nothing.
- The teacher knows what the student does not: Qwen3-VL-8B-Instruct-FP8 scores 68.33 (+3.40 ± 1.22) on MMMU val and
  solves 52.8 % of the student's 1-3/5 questions and 17.5 % of its 0/5 questions (v6_prep_protocol.md B1).
- Target origin: the student is trained on its own samples; the teacher only scores them (self-generated target,
  low forgetting risk under the user's principle). The submitted model is the merged 4B LoRA; no teacher inside.

## Data (MMMU val is never training data)
1. `prepare_vwi.py v6` -> `data/pool_v6_all.jsonl`: VisualWebInstruct-verified with the v3 filters (one image, English,
   strict single-number gold <= 40 chars, difficulty >= 2, no options, MMMU-val text/image overlap removed) plus a
   Business / Tech & Eng keyword filter on the question. Result: 3,795 items (tech_eng 2,248, business 1,547),
   shuffled with seed 0.
2. Teacher screen: the first 1,200 items, teacher 1 sample (T=1, 8,192 tokens, the frozen open-answer CoT suffix),
   `grpo.py screen --screen-model Qwen/Qwen3-VL-8B-Instruct-FP8 --samples 1`. Keep the items the teacher answers
   correctly, in pool order -> `data/pool_v6.jsonl`. This replaces the judge's suspect-gold rule and makes the
   teacher signal point at a solvable problem. If fewer than 496 items are kept (31 rounds x 16), screen the next 1,200.
3. No student screening: easy and hard items both stay.

## One round (rounds 0-29; round 0 = base model)
- rollout: 16 questions from pool_v6 (offset 0), 8 samples each, T=1, 8,192 tokens, no top-up, no hints.
- teacher-score: the teacher's logprob of every token of each finished response (vLLM prompt logprobs on the exact
  student tokens; a token mismatch aborts the round).
- train: reward = rule-graded correctness (0/1); truncated responses dropped (v5). Per-token advantage =
  group outcome advantage (0 when the group has no spread) + 1.0 x (log p_teacher - log p_student_behaviour).
  Clipped surrogate 0.2, k3 KL to the frozen base beta 0.01, LoRA r16/alpha32, LR 1e-4, 4 groups per step,
  token-mean loss. The coefficient 1.0 is the standard on-policy distillation weight, fixed here.
- Command: `bash grpo/chain_v6.sh` (from MMMU-val/), unit `grpo-v6`.

## Stop rules (chain stops itself)
- Accuracy guard: 4-round mean stage-1 accuracy < 0.7 x round 0.
- Truncation: last round stage-1 truncation > 0.35.
- KL to base: max step KL > 0.1.
- Length collapse: 2-round mean stage-1 tokens < 0.6 x round 0.
- Dev floor: after r009 or r019, dev accuracy <= 62.93 (delta <= -2.0 vs base mean 64.93).

## Dev evaluation (§5.5, replaces the 216 diagnostic that misled v2 and v5)
- At r009, r019, r029: merge the checkpoint, `SEEDS=0 bash eval.sh <merged> runs/grpo_v6_rNNN_full` (frozen defaults,
  gpu-mem 0.90), then `analyze.py compare results/seed* vs runs/grpo_v6_rNNN_full/seed0 --base-mean 1` (on a copy
  without the no-op LoRA keys if it refuses, as in v5 Amendment 1).
- Verdict: strong candidate = CI low > 0; candidate = point > 0 and no forgetting signal (stable-correct CI high
  not < 0); else inconclusive.
- After the chain: report all dev results. Candidates go to the 5-seed final only after the user agrees; the
  checkpoint is the candidate with the highest dev delta (a max over at most 3 noisy values, so the final 5 seeds
  are the real test).
- If there is a candidate: data-only ablation (same pool and rounds, teacher-coef 0) to attribute the gain.

## Reported every round
Stage-1 accuracy, truncation, mean tokens, teacher reverse KL (`rkl`, teacher phase and per train step), KL to base.

## Pre-launch smoke test (2026-11-06 02:50, before any v6 rollout; engineering only, no rule changed)
On 32 copied v5 r007 stage-1 rows (4 questions, 21 finished), `runs/v6_smoke`:
- Bug 1: the teacher engine hung 7 h at start-up (fork after the image processor's torch thread pool ran) ->
  the engine is now created first.
- Bug 2: pre-expanded image tokens were expanded again by vLLM; the token check caught it -> the prompt now carries
  one image pad and vLLM expands it; the check (length and exact student tokens) passes.
- Teacher scoring: 21 responses, 89k tokens, 78 s including engine load. Reverse KL 0.106 nats/token; per-token
  gap (teacher - student) median 0.00, 1st/99th percentile -2.23/+1.00, |gap| > 2 on 1.4 % of tokens, min -16.6.
- Train: 4 groups (3 without outcome spread, trained on the teacher term only), 1 step, 92 s, peak 12.2 GB.
  Clip rate 5.2 % (v5 ~0.5 %) because the copied rows were sampled by the v5 r007 adapter while the smoke run starts
  from a fresh adapter; a real v6 round samples from the current policy.
- Operations: the one-off teacher screen runs at gpu-mem 0.80 (GPU otherwise free); the loop keeps 0.68 as in v5.

## Stop (2026-11-06 04:26, after round 2) — length guard; no rule changed
- Teacher screen: 1,200 screened, 858 kept (tech_eng 484, business 374).
- Rounds (stage-1): acc 0.875 / 0.844 / 0.820; truncation 0.094 / 0.063 / 0.016; mean tokens 2215 / 1450 / 1170;
  teacher rkl 0.125 / 0.118 / 0.110; max step KL 0.016. Guard: 2-round mean 1310 < 0.6 x 2215 = 1329 -> length_collapse.
  Accuracy guard 0.846 vs 0.7 x 0.875 (passed). No checkpoint; the adapter after round 2 is `runs/v6/adapter`.
- Unregistered diagnostic (seen after the stop): the mean includes truncated responses at 8,192 tokens, so falling
  truncation alone lowers it. Finished-only mean tokens 1597 / 1001 / 1059; the teacher's screen length on the same
  questions 1847 / 1448 / 867 (median student/teacher ratio 1.14 / 0.96 / 1.18), so most of the drop is question mix.
  Finished accuracy 0.966 / 0.900 / 0.833; in round 2 the shorter half is less accurate (0.746 vs 0.921).
- Paired check running (`runs/v6_paired.sh`): the round-2 adapter vs the base on the round-0 and round-2 questions.
  Whether to amend the length rule and resume is the user's decision.
- Paired check result (2026-11-06 15:27; both question sets were trained on in their round, so this is in-sample):
  | questions | model | acc | truncation | mean tokens | finished tokens |
  |---|---|---|---|---|---|
  | round 0 (seed 0) | base | 0.875 | 0.094 | 2215 | 1597 |
  | round 0 (seed 0) | round-2 adapter | 0.906 | 0.016 | 1784 | 1682 |
  | round 2 (seed 2) | base | 0.797 | 0.031 | 1136 | 908 |
  | round 2 (seed 2) | round-2 adapter | 0.898 | 0.008 | 1119 | 1064 |
  On the same questions the adapter's finished responses are not shorter (+5 %, +17 %); the guard fired because
  truncation fell (9.4 % -> 1.6 %) and the later rounds' questions are shorter. Not the v4 collapse pattern.

## Amendment 1 (2026-11-06 15:29, user decision after the paired check) — length guard
- Old rule: 2-round mean stage-1 tokens < 0.6 x round 0. It counts truncated responses at 8,192 tokens and ignores
  that each round has different questions, so it fired on falling truncation plus shorter questions.
- New rule: per round, the median over questions of (mean finished stage-1 tokens / the teacher's screen tokens on
  that question); stop if the 2-round mean < 0.6 x round 0 (`--length-ref data/screen_v6.jsonl`). Threshold unchanged.
- On rounds 0-2: round 0 1.136, last 2 rounds 1.066 (passes). All other rules, the dev schedule (r009/r019/r029) and the
  floor are unchanged. The chain resumes at round 3 with the round-2 adapter and optimizer state.

## Dev result r009 (2026-11-06 17:52)
- seed 0, 900 q: 63.67 vs base 5-seed mean 64.93 -> -1.27 pts, 95 % CI [-3.33, +0.80]; base stable-correct (452,
  held-out seeds) +0.44 [-1.77, +2.65] (no forgetting signal); truncation 14.1 -> 14.0 %, mean response 7479 -> 7061
  chars. Compare on a copy without the no-op LoRA keys: `runs/grpo_v6_r009_full/compare_base_mean.txt`.
- Verdict: inconclusive (point <= 0). Above the floor 62.93 -> the chain continues to r019 (rules unchanged).
- By discipline (vs base 5-seed mean): Business 74.8 -> 74.7, Tech & Eng 55.0 -> 54.8, other 66.1 -> 64.1. The trained
  domains did not move, and the training-pool truncation drop (9.4 % -> ~1-3 %) did not transfer to MMMU.

## Dev result r019 (2026-11-06 20:53)
- seed 0, 900 q: 63.89 -> -1.04 pts, 95 % CI [-3.07, +1.11]; base stable-correct -0.44 [-2.88, +1.99] (no forgetting
  signal); truncation 14.1 -> 14.4 %. Compare: `runs/grpo_v6_r019_full/compare_base_mean.txt`.
- Verdict: inconclusive (point <= 0). Above the floor -> the chain continues to r029 (rules unchanged).
- By discipline: Business 74.8 -> 78.0, Tech & Eng 55.0 -> 50.5, other 66.1 -> 65.2 (subsets of 150/210 q; within noise).

## Rescoring (2026-11-06 22:20, user decision)

A scorer bug was fixed in `run_eval.py`: three open questions whose gold is a list (stored by HF as a string
like "['Tampa', 'Florida']") could never be scored correct. All saved runs were re-scored with
`scripts/rescore_open.py` (multiple-choice unchanged). The r029 dev run uses the fixed scorer.

| | before | after |
|---|---:|---:|
| base 5-seed mean | 64.93 | 65.16 ± 0.93 |
| r009 dev | 63.67 (−1.27, CI [−3.33, +0.80]) | 63.78 (−1.38, CI [−3.42, +0.76]) |
| r019 dev | 63.89 (−1.04, CI [−3.07, +1.11]) | 64.11 (−1.04, CI [−3.04, +1.09]) |

Verdicts are unchanged (both inconclusive). The registered floor stays at 62.93 as written; r029 is the
last dev evaluation, so the floor no longer affects any decision.

## Dev result r029 and end of v6 (2026-11-06 23:35)
- seed 0, 900 q (fixed scorer; `rescore_open.py` reports unchanged): 65.11 vs base 5-seed mean 65.16 -> -0.04 pts,
  95 % CI [-2.20, +1.96]; base stable-correct (453) +0.44 [-1.99, +2.87] (no forgetting signal); truncation
  14.1 -> 12.1 %, mean response 7479 -> 6454 chars. Compare: `runs/grpo_v6_r029_full/compare_base_mean.txt`.
- Verdict: inconclusive (point <= 0). No v6 checkpoint is a candidate (r009 -1.38, r019 -1.04, r029 -0.04), so by
  the registered rules there is no 5-seed final and no data-only ablation. The chain finished all 30 rounds.
- By discipline: Business 74.8 -> 74.7, Tech & Eng 55.0 -> 52.9, other 66.4 -> 67.2. The trained domains did not move.
- Truncation groups (selected on held-out base seeds 1-4, compared on seed 0; >= 2/4 truncated, n=160): truncation
  70.6 -> 60.0 %, accuracy 39.4 -> 37.5 %. The fewer truncations did not become correct answers. Rest (n=740):
  70.1 -> 71.1 %.
- Next: the held-out pool test (`heldout_protocol.md`) uses the r029 adapter.

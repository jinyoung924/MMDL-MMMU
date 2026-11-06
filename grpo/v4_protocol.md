# GRPO v4 — registered before any v4 run (2026-11-04)

Fixes the limits diagnosed in v3 (v3_protocol.md "Stop") and adds teacher hints for problems the student
cannot solve. Rules carried over unchanged: shared `main` untouched, no commits; MMMU val never in training;
no MMMU-Pro / test split / Chinese data; thresholds below are not changed after results without the user.

## Data: model-screened hard pool
Source = v3 strict VWI pool (8,091). Screening with the base model (2 samples per item, training sampler T=1,
8192 tokens) on ~3,000 items not seen in v3: all difficulty >= 4, then difficulty 2-3 by longest reference.
Keep items with <= 1 of 2 correct. Add v3-seen items whose round stage-1 had <= 3 of 4 correct.
Symbolic gold strings (π, √, \frac) are evaluated to their value; unevaluable golds are dropped.

## Rollout
8 samples per question (no non-hinted top-up), 32 questions per round. Questions with 0 of 8 correct get one
Sonnet 5.5 hint (headless CLI, effort low, Read tool): at most two sentences pointing to the key visual fact
or first step, never the answer. A hint whose numbers match the gold (grading tolerance) is discarded. Hinted
questions get 8 more samples with the hint inserted before the answer instruction; they form their own group.

## Reward
`r = correct + 0.5 * reasoning_ok * correct + 0.25 * w_t * image_ok`, truncated -> 0, with
w_t = 1 - round/30 (the ungated image credit fades out). Judge = validated low-effort headless Sonnet
(v3 Amendment 5); hinted responses are judged with the hint shown. Suspect-gold rule (v3 Amendment 6) kept.
Grading adds: simple expressions (√, π, fractions, products, degree-minute marks) are evaluated; a written
decimal answer is accepted within half a unit of the coarser of the two printed decimal places (decimal golds
only), plus the existing 1 % and x10^±3 unit-prefix rules.

## Training
From base. GRPO as v2/v3 except KL β = 0.001 (was 0.04). LR 1e-4, 4 groups per optimizer step, LoRA r16.

## Stop rules (after every round)
v3 rules (stage-1 accuracy < 0.7 x round 0, truncation > 0.35, KL > 0.1, judge-score hacking rule).

## Decision
- r009, r019: 216-group diagnostic (merged, seeds 5 and 6) vs v1 r009 (37.5 %). Informational.
- r029: 216 (seeds 5, 6) and 166 (seeds 5, 6; reference = leave-one-seed-out base estimate ~6-8 %).
  216 delta >= +2 -> §5.5 full evaluation (seed 0); else stop and report negative.
- 2026-11-04: screening ids = data/screen_ids_v4.txt (3,000: all difficulty>=4, then longest references; v3-seen excluded).

## Amendment 1 (2026-11-04, user decision before any training-effect result; only round-0 timing/cost seen)
Round 0 (32 questions): stage-1 accuracy 0.336, truncation 0.30, 5,000 tokens mean, 12/32 questions 0-of-8,
12 hints (no leak), hinted accuracy 0.25, 29/44 informative groups; rollout 53 min, train 11 min, judge ≈ $7.3.
To bound time (~19 h) and judge use (~$110 list-price equivalent), rounds 1-29 use 16 questions each
(pool slice offset 16, so no question repeats round 0's 32). Everything else unchanged.

## Pause (2026-11-04 19:40, after the r009 diagnostic; resumable)
r009 216-group diagnostic (merged, seeds 5/6): 30.56 / 35.65, mean 33.1 % vs v1 near-base 37.5 % -> -4.4 ± 2.9.
Truncation 139/432 (v1 152), completed-response accuracy 36.2 % (v1 44.3 %), median length -25 %.
Training stage-1: truncation 26 % -> 14 % (rounds 1-5 -> 6-10) turned into wrong completed answers (38 % -> 50 %);
correct stayed 36 %; KL 0.0107 at r009. Chain paused by the assistant to stop further drift and judge spend;
continuation is the user's decision.

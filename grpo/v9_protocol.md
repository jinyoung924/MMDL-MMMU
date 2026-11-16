# v9 protocol — SFT on the student's own solutions written with the reference in view (SDFT-style)

Registered 2026-11-09 03:11, before any v9 generation (launched 03:12). Nothing below changes after results are seen without the
user's decision; any change is recorded as a numbered amendment.

User decisions (2026-11-09):
- "몇 점 올리냐가 중요한 게 아니라 그냥 성능 개선을 조금이라도 보고 싶어."
- v9 approved as presented, **with the MMMU 5-seed evaluation pre-approved** if gate 1 passes ("진행, 5 seed도 미리
  승인").

## Why
- External-target SFT collapsed the output format (diagram SFT: responses −78 % / −99.7 % shorter, MMMU −9.6 / −14.4).
- Own-correct RFT (v7, v8) kept the format and caused no forgetting, but barely moved the model (loss 0.46 → 0.42)
  and gave no significant in-distribution gain. It only reinforces what the model already knows.
- SDFT (Yang et al., ACL 2024, arXiv 2402.13669) lets the model rewrite the target in its own words. That reduces the
  distribution gap that causes forgetting, while the task is still learned. Here, the model reads the VWI reference
  solution, which carries the method it lacks, and writes its own solution. Training then uses the normal prompt
  without the reference.

## Data (MMMU val is never training data)
`python grpo/rft.py prep v9` → `data/pool_v9_ref.jsonl`, `data/v9_ids.txt`: the v8 training items
(`v8_num_train` 520, `v8_mc_train` 821) with ≤ 3 of 8 correct in the v8 base samples. That is **749 items** (numeric
325, MC 424). The reference prompt inserts
"Reference solution (to help you understand the method; do not mention it): … Now solve the problem yourself, step
by step, in your own words." before the usual CoT suffix.
Known issue: VWI references are model-written, and some say the problem is flawed and assume an intent. They are kept
as they are; only responses that reach the gold are used.

## Steps
1. **Generate** (base, no adapter, reference prompt, T=1, top_p 1, 8,192 tokens, engine seed 3, 4 samples) →
   `runs/heldout/v9_ref.jsonl` + rows.
2. **Select** (`rft.py select v9`): per item, up to 2 random responses (seed 0) that are finished, graded correct, and
   do not contain the word "reference" (case-insensitive). Stop if fewer than 300 items qualify.
3. **Train** (`rft.py train v9`): identical to v7/v8 (LoRA r16, α32, dropout 0, q/k/v/o/gate/up/down; loss on the
   response + `<|im_end|>`; prompt = the normal prompt without the reference; AdamW LR 1e-4, warmup 20 then constant,
   micro-batch 1 × accumulation 16, clip 1.0, 2 epochs, seed 0). The epoch-2 adapter is registered.
4. **Gate 1** (same as v8 gate 1): the 300 held-out numeric items (`data/heldout/v8_unseen.txt`, never trained in v8 or
   v9), 8 samples, engine seed 2 → `runs/heldout/v8_sdft.jsonl`, against the same v8 base samples.
   `heldout_compare.py v8 sdft`. **Pass** if the Δ accuracy 95 % CI lower bound > 0. Otherwise stop and report.
   This held-out set was already used for the v8 decision. It was never trained on, so it stays unbiased for v9.
5. **MMMU, 5 seeds** (pre-approved, only if gate 1 passes): merge, `SEEDS="0 1 2 3 4" bash eval.sh` →
   `runs/grpo_v9_sdft_5seed`, `analyze.py compare results/seed* vs <copies without the LoRA keys>` (paired by seed and
   question).
   - **Improvement confirmed:** Δacc (all 900) 95 % CI lower bound > 0.
   - **Improvement in the point estimate only:** Δacc > 0, CI includes 0, and no format collapse (truncation and
     Answer-tag rates each within 2 points of the base).
   - Otherwise: no improvement.
   With 5 paired seeds there is no spare base seed for the stable-correct group, so forgetting is judged by Δacc,
   truncation, Answer tag and response length.

Runs as `grpo/chain_v9.sh` in systemd unit `v9-chain` with the RAM guard.

## Expected cost
Generation 2,996 responses ≈ 3 h; training ≈ 1.5 h; gate 1 ≈ 3 h; MMMU 5 seeds ≈ 6 h.

## Run log
- Step 1 done 2026-11-09 04:27 (2,996 responses, 1.2 h). With the reference in view: 93.0 % correct, 2.6 % truncated.
  843 of the correct responses mention "reference" and are excluded by the step-2 rule.
- Step 2: **606 items** qualify (≥ 300), 1,145 responses → 71 updates per epoch, 142 in total.
- Step 3 (from 04:27): mean loss per 10 updates ~0.44–0.49 in epoch 1, ~0.35–0.41 in epoch 2 (RFT v7/v8 stayed ~0.42–0.44).
  The session that launched the chain ended ~04:30; the systemd unit kept running.
- Step 3 done ~04:53 (142 updates). Mean loss per 24 updates: 0.495 → 0.383.
- **Gate 1 (06:26): FAILED.** Held-out 300: 30.8 → 31.2 %, Δ **+0.50 [−2.46, +3.50]**. Truncation **17.4 → 7.0 %**,
  mean tokens 3,944 → 2,356, finished-response chars 9,994 → 6,061; finished-response accuracy 37.2 → 33.6 %.
  By rule the chain stopped; MMMU was not run.
- Exploratory (same unbiased split as v8: group chosen on base samples 1–4, base scored on samples 5–8, v9 on its 8):
  0/4 n=132 Δ **+9.85 [+6.44, +13.45]**; 1–3/4 n=138 Δ −3.17 [−8.51, +2.17]; 4/4 n=30 Δ **−21.25 [−31.25, −10.83]**.
  For comparison v8: +3.31 / +0.72 / −5.42. Reading: v9 learned to solve items the base could not, but its shorter,
  more direct style (learned from reference-guided targets) lost items the base solved by long, careful reasoning.
  The two cancel.

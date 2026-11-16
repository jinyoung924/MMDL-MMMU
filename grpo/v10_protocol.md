# v10 protocol — v9 data plus replay of the base's own solutions on items it already solves

Registered 2026-11-09 13:29, before any v10 training (launched 13:30). Nothing below changes after results are seen without the user's
decision; any change is recorded as a numbered amendment.

User decisions (2026-11-09):
- Goal: "모델이 못 풀던 문항들만 지금 오른 부분 습득하게 하는 게 목표 … 핵심은 맞추던 문제들을 최대한 성능을 유지하는 거".
- The user chose "고친 v10, 5 seed 미리 승인": replay from items the base already solves (not from the 1–7/8 items
  first proposed). The MMMU 5-seed evaluation is pre-approved if gate 1 passes.

## Why
v9 (`v9_protocol.md`) trained only on reference-guided solutions to items the base could not solve.
- In the exploratory split it gained **+9.85 [+6.44, +13.45]** on items the base could not solve, and lost
  **−21.25 [−31.25, −10.83]** on items it always solved. Overall: +0.50.
- Responses became 40 % shorter (truncation 17.4 → 7.0 %): the model learned the short, confident style of solutions
  written with the answer known.
- Replay (rehearsal) of the model's own outputs on what it already does well is the standard guard against this kind
  of forgetting. The replayed responses teach nothing new; they anchor the original solving style.

## Data (`rft.py select v10` → `runs/v10/rft_train.jsonl`)
- **New knowledge:** the v9 training set as is (1,145 responses, 606 items).
- **Replay, the same count (1,145):** the base's own correct responses on items it already solves.
  - Numeric v8 training items with ≥ 7 of 8 correct in the v8 base samples: 4 random correct responses each
    (≈ 268).
  - The rest: one random response each from random v7 MC training items with 4 of 4 correct in v7 step 1.
  - Replay items that share a source id or an exact image (SHA-256) with the v8 held-out set are skipped.
  - Built 13:29, before training: 1,145 replay (numeric 268–269), mean 3,882 chars vs 2,355 for the v9 responses.
- MMMU val is never training data.

## Steps
3. **Train** (`rft.py train v10`): identical settings to v7–v9 (LoRA r16, α32, dropout 0; response + `<|im_end|>`
   loss; AdamW LR 1e-4, warmup 20 then constant, micro-batch 1 × accumulation 16, clip 1.0, 2 epochs, seed 0; the
   order is shuffled per epoch). The epoch-2 adapter is registered.
4. **Gate 1** (same as v8/v9): the 300 held-out numeric items, 8 samples, engine seed 2 → `runs/heldout/v8_sdftmix.jsonl`,
   against the v8 base samples. **Pass** if the Δ accuracy 95 % CI lower bound > 0. Otherwise stop and report.
   Reported descriptively alongside: the same 0/4 · 1–3/4 · 4/4 split as v8/v9 (the user's question is whether the
   solved items are kept), truncation and length.
5. **MMMU, 5 seeds** (pre-approved, only if gate 1 passes) → `runs/grpo_v10_5seed`, the same labels as `v9_protocol.md`
   step 5 (confirmed = CI low > 0; point-only = Δ > 0 with truncation and Answer tag within 2 points of base).

Runs as `grpo/chain_v10.sh` in systemd unit `v10-chain` with the RAM guard.

## Expected cost
Training ≈ 2 h (286 updates); gate 1 ≈ 2.5 h; MMMU 5 seeds ≈ 6 h.

## Run log
- Step 2 (13:30): 2,290 responses (1,145 v9 + 1,145 replay) → 143 updates per epoch, 286 in total.
- Step 3 done 14:18 (286 updates, 48 min). Mean loss per sixth of training: 0.382 → 0.326.
- **Gate 1 (16:06): FAILED.** Held-out 300: 30.8 → 31.5 %, Δ **+0.71 [−2.00, +3.46]**. Truncation 17.4 → 8.8 %,
  mean tokens 3,944 → 2,540, finished-response chars 9,994 → 6,190; finished-response accuracy 37.2 → 34.5 %.
  By rule the chain stopped; MMMU was not run.
- Split (same unbiased method; v8 / v9 / v10):
  - 0/4 n=132: +3.31 / +9.85 / **+6.91 [+4.17, +9.75]**
  - 1–3/4 n=138: +0.72 / −3.17 / −1.09 [−6.52, +4.26]
  - 4/4 n=30: −5.42 / −21.25 / **−15.83 [−25.83, −5.83]**
  Replay recovered about a quarter of the loss on solved items (−21 → −16) and gave up about a third of the gain on
  unsolved items (+9.9 → +6.9); the two still cancel. On the 4/4 items the loss is wrong answers, not truncation
  (finished accuracy 87.9 → 72.8 %, truncation 3.3 → 5.0 %, finished chars 9,532 → 6,793).
- Diagnosis (descriptive): the replay did not restore length. Most replay responses (877 of 1,145) came from easy MC
  items (mean 3,882 chars), so they do not show the long, careful style the base uses on hard numeric items. The
  v9 targets themselves are short: the median correct reference-guided response is **0.21×** the base's median
  finished length on the same item; 23 % of them reach ≥ 0.7×, on 147 of 569 items.
- Style check (11/09, after the run, descriptive): on the 375 v9 training items where the base had ≥ 1 correct
  response, base own-correct vs the trained reference-guided responses: median 11,541 vs 1,857 chars; "wait" 10.3
  vs 0.35 per response; "but/however" 34.7 vs 1.7; wait+check per 1k chars 0.97 vs 0.21. Base NLL per token on the
  targets at step 1: v8 own 0.40–0.45, v9 0.54–0.61. The words are the model's own, but the structure is not: the
  targets commit at once to the interpretation the reference gives and never check. The v10 replay was short as well
  (median 1,832 chars, wait 2.8), so it could not hold the length.

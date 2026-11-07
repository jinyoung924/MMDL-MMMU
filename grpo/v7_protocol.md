# v7 protocol — RFT on the student's own correct answers (VWI letter-MC pool)

Registered 2026-11-07 22:18, before any v7 sampling (step 1 launched 22:19). Nothing below changes after results are seen without the user's
decision; any change is recorded as a numbered amendment.

User decisions (2026-11-07):
- Use RFT, not SFT. External-target SFT caused heavy forgetting (diagram SFT −9.6).
- The goal is to beat the base under the same evaluation. On our pipeline the base is 65.16 ± 0.93 (5 seeds); the
  official 67.4 uses Qwen's settings.
- The stronger-teacher direction stopped (v7_prep T2 failed), so v7 uses no teacher.

## Why
- Held-out test (`heldout_protocol.md`): GRPO v2 / v6 changed only length and truncation. Accuracy did not rise
  even in-distribution, on trained or unseen items. Each round's gain on its own questions (+6.4 for v2) did not
  persist to the final checkpoint.
- RFT targets the user's original goal directly: items the student sometimes solves (1–3 of 4) become always-solved.
  It trains on the student's own correct responses (self-generated targets, low forgetting risk). Compared with GRPO,
  it uses one sampling pass over thousands of items and a fixed dataset for 2 epochs, instead of small per-round updates.

## Data (MMMU val is never training data)
- `prepare_vwi_mc.py` → `data/pool_v7.jsonl`: 3,924 VWI-verified letter-MC items. Each has one image, is English, and
  has no MMMU-val text or image overlap. The prompt is rendered like MMMU MC (stem, "(A) option" lines, CoT MC suffix).
  The pool is shuffled with seed 0.
- Held-out: the first 300 (`data/heldout/v7_unseen.txt`), never trained on. Training candidates: the other 3,624
  (`data/v7_train_ids.txt`).

## Steps
1. **Sample** (base, no adapter): `grpo.py screen --pool data/pool_v7.jsonl --ids data/v7_all_ids.txt --samples 4`
   (T=1, top_p 1, 8,192 tokens, engine seed 0, training-time pixels) → `runs/heldout/v7_base.jsonl` + `.rows.jsonl`.
2. **Select** (`rft.py select`): among the training candidates, the items with 1–3 of 4 correct. From each, up to 2
   correct responses at random (seed 0). A correct response is finished (not truncated) and its tagged letter equals
   the gold (`grpo.correct`). If fewer than 500 items qualify, stop and report.
   `data/heldout/v7_seen.txt` = 100 random selected items (seed 0), for the in-sample check.
3. **Train** (`rft.py train`):
   - LoRA r16, α32, dropout 0 on the language model's q/k/v/o/gate/up/down, the same as GRPO (`grpo.py train`).
     Corrected 22:25, before any result; the first draft said 0.05, the forgetting pilot's value.
   - Loss on the response tokens plus `<|im_end|>` only.
   - AdamW, LR 1e-4, linear warmup over 20 steps then constant, micro-batch 1 × accumulation 16, grad clip 1.0,
     2 epochs, seed 0.
   - The epoch-2 adapter is the registered checkpoint. The epoch-1 adapter is saved but not evaluated unless the user
     asks.
4. **Gate 1 (in-distribution):** screen with the adapter on unseen 300 + seen 100 (same settings, 4 samples) →
   `runs/heldout/v7_rft.jsonl`. Then `heldout_compare.py v7 rft`.
   - **Pass** if the unseen Δ accuracy 95 % CI lower bound > 0. Otherwise stop and report: RFT on this pool does not
     raise in-distribution accuracy for this model.
   - Truncation, tokens and the seen set are reported descriptively. The seen set is biased by selection, because
     its items were chosen on the same base samples.
5. **Gate 2 (MMMU dev, only if gate 1 passes):**
   - Merge, then run `SEEDS=0 bash eval.sh <merged> runs/grpo_v7_rft_full` and
     `analyze.py compare results/seed* vs runs/grpo_v7_rft_full/seed0 --base-mean 1`. Compare on a copy without the
     no-op LoRA keys.
   - Strong candidate = CI low > 0. Candidate = point > 0 and no forgetting signal (stable-correct CI high not < 0).
     Otherwise inconclusive.
6. **5-seed final** only after the user agrees.

## Expected cost
Sampling 15,696 responses ≈ 7 h; training ≈ 1 h; gate 1 ≈ 45 min; gate 2 ≈ 70 min. Runs as a systemd chain with the
RAM guard (`ram_watch.sh`).

## Known data issues (found 2026-11-07 23:15 during sampling, before any result; no rule changed)
- 60 golds (1.5 %; 4 in the held-out set) come from the loose "option text contained in short_answer" rule. A
  spot check of 4 was correct each time (e.g. "30 cm (option c)" → C).
- 17 items (0.4 %; 1 held-out) lose text after the last option's first line in `render()`: a trailing question
  sentence, a multi-line last option, or an image alt tag. Kept as registered. They can add at most 34 of the RFT
  responses, and restarting step 1 would cost ~1 h of sampling.

## BMMR-English check (side task, 2026-11-07, scratchpad `bmmr_en/`)
BMMR-Eval's English half yields only 123 clean letter-MC items (84 % Science, mostly math; 99.4 % of English items
are open-ended). It is not a source of MMMU's missing disciplines and is not used. Its contamination checks found
0 text overlaps with MMMU val/dev/test and 2 image near-matches, both dropped.

## Run log
- Step 1 done 2026-11-08 04:58 (15,696 responses, 6.6 h). Step 2: **596 items** qualify (≥ 500), 1,024 responses.
- Step 3 first attempt (04:59): CUDA OOM. The HF loss materialises full fp32 logits (152k vocab × up to 9k tokens)
  plus their gradient. Engineering fix, no rule changed: the loss is computed the way `grpo.py train` computes
  log-probs, i.e. hidden states, then the LM head in 1,024-token checkpointed chunks. LoRA weights are kept in fp32
  with bf16 autocast, also as in GRPO. The loss is the same quantity (mean NLL over the response tokens and
  `<|im_end|>`). Checked on the longest response (7,494 tokens): peak 12.2 GiB. Chain relaunched 05:01.
- Step 3 done ~05:55 (128 updates, 53 min). Mean loss per 16 updates: 0.462 → 0.425.
- **Gate 1 (06:52): FAILED.** Unseen 300: 85.8 → 84.2 %, Δ **−1.58 [−3.58, +0.42]**; truncation 3.9 → 4.2 %, mean tokens
  1,630 → 1,604. Seen 100 (selection-biased): 53.5 → 61.0, Δ +7.50 [+1.25, +14.00]. By rule the chain stopped; MMMU
  (gate 2) was not run. Epoch 1 not evaluated.
- Exploratory, unseen only, unbiased split (group chosen on base samples 1–2, base scored on samples 3–4, RFT on all 4):
  mixed 1/2 n=32 Δ +3.12 [−10.94, +17.19]; both right n=244 Δ −0.72 [−2.77, +1.23]; both wrong n=24 Δ −6.25 [−22.92, +8.33].
  No group moves detectably. Conclusion: RFT on this pool does not raise in-distribution accuracy for this model.

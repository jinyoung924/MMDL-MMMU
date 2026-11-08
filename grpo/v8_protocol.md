# v8 protocol — larger, harder RFT on the student's own correct answers

Registered 2026-11-08 07:36, before any v8 sampling (launched 07:37). Nothing below changes after results are seen without the user's
decision; any change is recorded as a numbered amendment.

User decision (2026-11-08, after v7 gate 1 failed): "더 크고 어려운 RFT (v8)", plan approved as presented (8 samples
per item, ~3,000 training responses, gate 1 on 300 hard numeric items).

## Why
- v7 (`v7_protocol.md`) trained on 1,024 own-correct responses from an easy pool (base 86 %). The training loss barely
  moved (0.46 → 0.42), so the model hardly changed. Unseen Δ was −1.58 [−3.58, +0.42].
- On hard items, the student's correct responses are ones it produces with low probability. They carry a larger
  learning signal. More samples per item (8) find more items it sometimes solves and more distinct correct paths.

## Data (MMMU val is never training data; both pools were built with the MMMU-val text/image overlap filter)
`python grpo/rft.py ids v8` writes the lists; they were fixed before any v8 sampling.
- **Numeric** (`data/pool_v3.jsonl`, VWI-verified open numeric answers): items of the 11/04 base screen
  (`data/screen_v4.jsonl`, 2 samples) with < 2 correct and < 2 truncated. That is 883 items; 2 that also appear in
  the MC pool are dropped, leaving 881. These are shuffled with seed 0.
  - The first 300 are held out (`data/heldout/v8_unseen.txt`). Their mean accuracy on the old screen is 21 %.
  - VWI sub-questions can share a source id ("838101.4") or an image. The 61 remaining items that share a source id
    or an exact image (SHA-256) with a held-out item are removed from training. That leaves 520 training items
    (`data/v8_num_train.txt`).
- **MC** (`data/pool_v7.jsonl`): the v7 training candidates with < 4 of 4 correct in v7 step 1, 821 items
  (`data/v8_mc_train.txt`). None are in the v7 or v8 held-out sets.

## Steps
1. **Sample** (base, no adapter, T=1, top_p 1, 8,192 tokens, training-time pixels, engine seed 1 so that the samples
   are not repeats of the seed-0 screens):
   - Numeric held-out + training (820): 8 samples → `runs/heldout/v8_base.jsonl`.
   - MC (821): 4 more samples → `runs/heldout/v8mc_base.jsonl`. Together with the 4 v7 step-1 samples, each MC item
     has 8.
2. **Select** (`rft.py select v8`): items with 1–7 of 8 correct. From each, up to **4** correct responses at random
   (seed 0). A correct response is finished and graded correct (`grpo.correct`). If fewer than 500 items qualify, stop
   and report.
3. **Train** (`rft.py train v8`): identical to v7 step 3 (LoRA r16, α32, dropout 0, q/k/v/o/gate/up/down; loss on the
   response tokens + `<|im_end|>`; AdamW LR 1e-4, warmup 20 then constant, micro-batch 1 × accumulation 16, clip
   1.0, 2 epochs, seed 0). The epoch-2 adapter is the registered checkpoint.
4. **Gate 1 (in-distribution, hard items):** the adapter on the 300 held-out numeric items, 8 samples, engine seed 2
   → `runs/heldout/v8_rft.jsonl`. The base side is the 8 fresh step-1 samples. The old 11/04 samples that chose these
   items are not used for scoring, so there is no selection bias. `heldout_compare.py v8 rft`.
   - **Pass** if the Δ accuracy 95 % CI lower bound > 0 (paired per item, bootstrap 10,000, seed 0). Otherwise stop
     and report.
   - No seen set (in v7 it was selection-biased and uninformative).
5. **Gate 2 (MMMU dev, only if gate 1 passes):** merge, `SEEDS=0 bash eval.sh` → `runs/grpo_v8_rft_full`, compare
   against the 5-seed base mean on a copy without the no-op LoRA keys. Strong candidate = CI low > 0. Candidate =
   point > 0 and stable-correct CI high not < 0. Otherwise inconclusive.
6. **5-seed final** only after the user agrees.

Runs as `grpo/chain_v8.sh` in systemd unit `v8-chain` with the RAM guard (`ram_watch.sh`).

## Expected cost
Step 1 ≈ 9,844 responses at ~1,000/h (11/04 screen rate on similar items) ≈ 10 h. Training ≈ 3 h. Gate 1 ≈ 2.5 h.
Gate 2 ≈ 1.2 h.

## Run log
- Step 1 done 2026-11-08 19:51. Numeric 6,560 responses in 8.1 h, MC 3,284 in 4.2 h (about 810 and 790 per hour,
  slower than the 1,000/h estimate).
- Step 2, first attempt (19:52): AssertionError. The code read all sample files into one table by qid. 3 numeric
  training qids also exist in `pool_v7` (the MC rendering of the same VWI item, not in the v8 MC list), so their v7 MC
  samples were mixed in. Engineering fix, no rule changed: numeric items now read only the v8 numeric samples, and MC
  items read the v7 + v8 MC samples, as step 2 states. None of the 3 is in the held-out set. Chain relaunched.
- Step 2 (19:55): **1,009 items** qualify (≥ 500), 3,101 responses (numeric 977, MC 2,124; mean 10.5k chars).
  Base accuracy on 8 fresh samples, descriptive: held-out 30.8 % (174 of 300 items have 1–7 of 8 correct; v7's
  held-out had 60), numeric train 34.9 %. Step 3 started 19:55, ~25 s per update, 387 updates.
- Step 3 done ~22:40 (386 updates, 2.8 h). Mean loss per 48 updates: 0.442 → 0.417.
- **Gate 1 (01:46 11/09): FAILED.** Held-out 300: 30.8 → 31.8 %, Δ **+1.00 [−1.25, +3.33]**; truncation 17.4 → 16.3 %,
  mean tokens 3,944 → 3,884; finished-response accuracy 37.2 → 37.9 %. By rule the chain stopped; MMMU not run.
- Exploratory (not a gate; 3 subgroups, so one CI excluding 0 is weak evidence): group chosen on base samples 1–4,
  base scored on samples 5–8, RFT on its 8: 0/4 n=132 Δ +3.31 [+0.85, +5.87]; 1–3/4 n=138 Δ +0.72 [−3.99, +5.53];
  4/4 n=30 Δ −5.42 [−12.92, +1.67].

## Amendment 1 (2026-11-09 01:48, user decision after gate 1 failed; run launched 01:49)
The user chose to evaluate the epoch-2 checkpoint on MMMU anyway ("v8을 MMMU로 참고 평가"). Step 5 runs unchanged
(merge, seed 0, the same comparison and labels), but the result is **exploratory**: gate 1 failed, so even a
"candidate" label does not by itself justify the 5-seed final. The 5-seed final still needs the user's agreement.
- **MMMU seed 0 (exploratory, Amendment 1; 03:01 11/09): 64.78**, Δ vs base 5-seed mean **−0.38 [−2.31, +1.69]**.
  Base stable-correct (453) +1.32 [−0.88, +3.53], so no forgetting signal. Truncation 14.1 → 14.1 %, Answer tag
  85.9 → 85.8 %. Label: inconclusive (point ≤ 0), not a candidate. No 5-seed final.

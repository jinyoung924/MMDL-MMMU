# v12 protocol — v11 data plus long own-correct MC anchors

Registered 2026-11-10 20:19, before any v12 training. Data built 20:18, before registration (selection only, no
results). Nothing below changes after results are seen without the user's decision; any change is recorded as a
numbered amendment.

User decision (2026-11-10, after the v11 5-seed report): "어 진행해" to the recommended next step, i.e. add the
base's own long, correct MC solutions to the v11 anchors. The MMMU 5-seed run is **not** pre-approved.

## Why
- v11 on MMMU, 5 seeds: 62.04, Δ **−3.11 [−4.64, −1.51]**. Unbiased split (group on base seeds 0–1, score seeds
  2–4): unsolved n=225 **+7.11** (sig), solved n=508 **−6.96** (sig).
- Length barely changed (finished median −8 %). The checking habit dropped: wait+check per 1k chars 0.78 → 0.48.
  Losses were mostly MC in non-numeric subjects (Pharmacy, Clinical Medicine, Materials, Public Health).
- v11's anchor came only from hard numeric items, while MMMU is 94 % MC. v12 adds an anchor from hard MC items, so
  the style is held on MC too, and keeps the v9 new-knowledge targets.

## Data (`rft.py select v12` → `runs/v12/rft_train.jsonl`, 4,362 responses)
- **v11 training data as is:** v9 targets 1,145 + numeric anchors 1,093.
- **MC anchors:** the base's own correct, finished responses in its 8 samples (v7 step 1 + v8 top-up) on the 821
  hard MC v8 training items (`data/v8_mc_train.txt`). Any item with ≥ 1 correct, up to 4 per item (seed 0).
  Built: **2,124 responses on 670 items**, median 8,768 chars.
  - No item shares a source id or image with the v8 held-out set (checked in the code).
- New knowledge : anchor ≈ 1 : 2.8. MMMU val is never training data.

## Steps
3. **Train** (`rft.py train v12`): identical to v7–v11 (LoRA r16, α32, LR 1e-4, 2 epochs, seed 0). 273 updates per
   epoch, 546 in total. The epoch-2 adapter is registered.
4. **Gate 1** (same as v8–v11): held-out 300, 8 samples, engine seed 2 → `runs/heldout/v8_mcanchor.jsonl`.
   - **Pass** if the Δ accuracy 95 % CI lower bound > 0.
   - Also reported, descriptively: the 0/4 · 1–3/4 · 4/4 split, truncation and length.
5. **MC check (descriptive, not a gate):** the v7 MC held-out set minus the 11 items that share a source id or image
   with any v12 training item → `data/heldout/v7_unseen_v12.txt` (289 items).
   - Settings as in v7 gate 1: 4 samples, engine seed 0, against `runs/heldout/v7_base.jsonl` → `runs/heldout/v7_v12.jsonl`.
   - The v11 adapter is run on the same items (`runs/heldout/v7_v11.jsonl`) as a reference: does this check show
     the MC loss that v11 had on MMMU?
   - Reported: Δ accuracy with a paired bootstrap CI (items, 10,000, seed 0), truncation, finished chars, wait+check
     per 1k chars.
6. **MMMU dev (only if gate 1 passes):** merge, `SEEDS=0 bash eval.sh` → `runs/grpo_v12_full`, compared against the
   5-seed base mean on a copy without the no-op LoRA keys.
   - **Strong candidate:** CI low > 0.
   - **Candidate:** point > 0 and stable-correct CI high not < 0.
   - Otherwise: inconclusive.
7. **5-seed final** only after the user agrees.

Runs as `grpo/chain_v12.sh` in systemd unit `v12-chain` with the RAM guard.

## Expected cost
Training ≈ 3–3.5 h (546 updates, three quarters long responses); gate 1 ≈ 2.5 h; MC check ≈ 1–1.5 h for both
adapters; MMMU seed 0 ≈ 1.2 h.

## Run log
- Launched 2026-11-10 20:19 as `grpo/chain_v12.sh` (unit `v12-chain`, RAM guard `v12-ramwatch`).
- Step 3 done 23:15 (546 updates, 2 h 55 min).
- **Gate 1 (11/11 01:45): FAILED.** Held-out 300: 30.8 → 30.9 %, Δ **+0.12 [−2.25, +2.50]** (v11 +2.21). Truncation
  17.4 → 13.9 %, mean tokens 3,944 → 3,129, finished chars 9,994 → 7,380; finished accuracy 37.2 → 35.8 %.
- Split (same unbiased method; v11 / **v12**):
  - 0/4 n=132: +5.87 / **+3.98 [+1.70, +6.25]**
  - 1–3/4 n=138: +1.09 / **−1.00 [−5.98, +3.80]**
  - 4/4 n=30: −6.25 / **−9.17 [−20.00, +2.08]**
- **MC check (02:32), 289 items, base 86.8 %:**
  - v12: 85.5 %, Δ **−1.30 [−3.63, +0.95]**; truncation 3.9 → 3.5 %; finished chars 4,254 → 3,703; wait+check per
    1k 0.90 → 0.79.
  - v11 (reference): 81.4 %, Δ **−5.36 [−7.87, −2.94]**; finished chars 3,499; wait+check per 1k 0.56.
  - Unbiased split (group on base samples 1–2, base scored on 3–4): base-solved 2/2 items (n=239) v11 **−4.92
    [−7.53, −2.51]**, v12 −1.36 [−3.35, +0.52]. The 0/2 and 1/2 groups are small (20, 30) and uninformative.
- Reading: the MC check shows the MC loss that v11 had on MMMU (v11 MMMU −3.11), so it works as an early check. The
  MC anchor cut that loss to about a quarter and kept most of the checking habit. But the gain on unsolved numeric
  items shrank (+5.9 → +4.0) and the numeric solved items fell further (−6 → −9, n.s.): the numeric anchor is now
  25 % of the data instead of 49 %, and the v9 targets are 26 % instead of 51 %. Each anchor holds its own domain;
  the more anchor, the less new learning. By rule the chain stopped; MMMU not run. The held-out 300 has now been
  used for five tests (v8–v12).

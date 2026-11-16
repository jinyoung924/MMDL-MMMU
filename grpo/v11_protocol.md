# v11 protocol — part 0: pilot for new-knowledge targets shaped like the model's own solutions

Registered 2026-11-09 17:00, before any v11 generation. Nothing below changes after results are seen without the
user's decision; any change is recorded as a numbered amendment. Part 0 is generation only: no training, no
evaluation, and MMMU is not touched. The training run (part 1) is registered after the pilot, with the user.

User decision (2026-11-09): "어 가자" to the plan "try a hint instead of the full reference, keep only targets that
look like the base's own solutions, and check the target style on ~100 items before training".

## Why
- v9 and v10 raised items the base could not solve (+9.9 / +6.9, both significant) but lost items it always solved
  (−21 / −16, both significant). The loss is wrong answers, not truncation.
- On the same 375 items, the base's own correct solutions and the v9 targets differ in shape: median 11,541 vs
  1,857 chars; "wait" 10.3 vs 0.35 per response; wait+check per 1k chars 0.97 vs 0.21. With the full reference in
  view, the model commits to the reference's reading at once and never checks. Training on that taught the habit.
- Goal for the targets: carry the method the model lacks, but keep its usual length and checking.

## Items
100 items drawn at random (seed 0) from `data/v9_ids.txt` (the 749 v8 training items with ≤ 3 of 8 base correct)
→ `data/v11_pilot_ids.txt`. Held-out sets are not touched.

## Variants (base model, no adapter, T=1, top_p 1, 8,192 tokens, 4 samples per item, engine seed 5)
- **A — full reference, own-way instruction.** The v9 reference block, followed by: "Now solve the problem yourself
  as you normally would, without relying on the reference: work it out step by step, check your reading of the
  figure and each step, and accept a fact only if you can verify it from the problem itself."
- **B — hint only.** Step B1: the base writes one hint per item (engine seed 4, 512 tokens) from the problem and the
  reference: "Write a hint for a student who is stuck on this problem, in at most two sentences. Name the key idea or
  method only. Do not give any numbers, intermediate results, or the final answer." A hint is dropped if it is not
  finished, is longer than 600 characters, contains a number equal to the gold, or (MC) names the gold letter as an
  option or contains the gold option's text. Step B2: the problem with "Hint: …", then: "Solve the problem yourself as
  you normally would (do not mention the hint): work it out step by step and check your reading of the figure and
  each step." Items without a valid hint count as having no usable response.
- **Control:** the existing v9 samples (`runs/heldout/v9_ref.rows.jsonl`, 4 per item) on the same 100 items.

## Measures (`grpo/v11_pilot.py report`)
- A response is **usable** if it is finished, graded correct, does not contain "reference" or "hint"
  (case-insensitive), and its length is ≥ 0.6 × the base's median finished length on that item (v8 numeric samples;
  v7 + v8 MC samples). If the base has no finished response on the item, the median over all pilot items is used.
- Reported per variant: accuracy, truncation, median length ratio over correct finished responses,
  wait+check per 1k chars, items with ≥ 1 usable response.

## Pilot rule
A variant **passes** if all three hold: median length ratio ≥ 0.6; wait+check per 1k chars ≥ 0.5 (base 0.97, v9
0.21); ≥ 40 of the 100 items have ≥ 1 usable response. If both pass, the one with more usable items is chosen.
If neither passes, stop and report.

## Expected cost
Hints ≈ 5 min; A and B 800 responses, longer than v9's, ≈ 1–1.5 h.

## Run log
- Launched 2026-11-09 17:00 as `grpo/chain_v11p.sh` in systemd unit `v11p-chain` with the RAM guard.
- B1 hints done 17:01 (43 s). The hint filter crashed on MC items whose options are stored as a dict rather than a
  string. Engineering fix, no rule changed; relaunched 17:01. **97 valid hints**, 3 dropped for a gold leak (median
  210 chars). A spot check of 6 hints: each names a method, with no numbers or answers.
- A done 17:20 (400 responses, 19 min); B done 18:05 (388 responses, 45 min). Report 18:05 (`runs/v11p/report.txt`):

  | Variant | Accuracy | Trunc. | Length ratio (median) | wait+check / 1k | Items with usable | Rule |
  |---|---|---|---|---|---|---|
  | v9 control | 95.0 % | 2.8 % | 0.27 | 0.66 | 17 | fail |
  | A own-way | 89.8 % | 5.5 % | 0.51 | 0.60 | 22 | fail |
  | B hint | 30.2 % | 31.2 % | **1.07** | **0.86** | 32 | fail |

  **No variant passes; by rule the pilot stops here.**
- Descriptive split by base correct (of 8) on the item: base 12.2 % on the pilot items; 46 items 0/8.
  - B: 0/8 items 11.0 % accuracy, 2 items with a usable response; 1–3/8 items 45.4 %, 30 items.
  - A: 0/8 85.3 %, 7 items; 1–3/8 93.5 %, 15 items. v9: 0/8 94.0 %, 5 items; 1–3/8 95.8 %, 12 items.
  - 144 of 388 B responses mention the hint.
  Reading: the trade-off is sharp. A method-only hint keeps the base's own shape but does not unlock items the base
  never solves. The full reference unlocks them (85–94 %) but the solutions come out short (the length rule removes
  most of them), because with the answer path in view the model does not need to explore.

# v11 part 1 — v9 data plus long own-style anchors from the same hard distribution

Registered 2026-11-09 18:16, before any part-1 training (launched 18:16). Data built 18:15, before registration (selection only, no
results).

User decision (2026-11-09, after the 18:05 pilot report): "1번으로 ㄱㄱ", i.e. option 1 of the pilot report. MMMU 5 seeds were **not**
pre-approved this time: if gate 1 passes, only the seed-0 dev evaluation runs, and the 5-seed run needs the user's OK.

## Why
- v10's replay was mostly easy MC (median 1,832 chars), so it could not hold the long, careful style that the base
  uses on hard numeric items. Solved items still dropped −16 (wrong answers, ~30 % shorter).
- The pilot showed that new knowledge comes only with the full reference, and those targets are short. So keep the
  v9 targets, and change the anchor: long own-correct solutions from the same hard numeric distribution.
- Own-correct responses on these items did not cause forgetting in v8 (4/4 group −5.4, CI includes 0).
- Note (the user's earlier point on v10): these anchor items are ones the base *sometimes* solves. The anchor's job here is
  to hold the solving style, not to rehearse already-solved answers.

## Data (`rft.py select v11` → `runs/v11/rft_train.jsonl`, 2,238 responses)
- **New knowledge:** the v9 training set as is (1,145 responses, 606 items).
- **Anchor:** the base's own correct, finished responses in the v8 base samples (8 per item, engine seed 1) on the 520
  numeric v8 training items. Any item with ≥ 1 correct, up to 4 per item (seed 0), shuffled and cut to the v9 count.
  Built: **1,093 responses on 368 items** (all of them; fewer than 1,145), median 8,922 chars.
  - `v8_num_train` already excludes items sharing a source id or an image with the held-out set; the check is repeated.
- MMMU val is never training data.

## Steps
3. **Train** (`rft.py train v11`): identical to v7–v10. The epoch-2 adapter is registered.
4. **Gate 1** (same as v8–v10): held-out 300, 8 samples, engine seed 2 → `runs/heldout/v8_sdftlong.jsonl`.
   - **Pass** if the Δ accuracy 95 % CI lower bound > 0. Otherwise stop and report.
   - Also reported, descriptively: the 0/4 · 1–3/4 · 4/4 split, truncation and length.
5. **MMMU dev (only if gate 1 passes):** merge, `SEEDS=0 bash eval.sh` → `runs/grpo_v11_full`. Compare against the
   5-seed base mean on a copy without the no-op LoRA keys, as in `v8_protocol.md` step 5.
   - **Strong candidate:** CI low > 0.
   - **Candidate:** point > 0 and stable-correct CI high not < 0.
   - Otherwise: inconclusive.
6. **5-seed final** only after the user agrees.

Runs as `grpo/chain_v11.sh` in systemd unit `v11-chain` with the RAM guard.

## Expected cost
Training ≈ 1.5–2 h (278 updates; half the responses are long); gate 1 ≈ 2–2.5 h; MMMU seed 0 ≈ 1.2 h.

## Run log (part 1)
- Launched 18:16 as `grpo/chain_v11.sh` (unit `v11-chain`, RAM guard).
- Step 3 done 19:37 (278 updates, 80 min). Mean loss per sixth: 0.446 → 0.389 (v10 0.382 → 0.326; the long own
  responses keep the loss near their entropy).
- **Gate 1 (22:08): FAILED, narrowly.** Held-out 300: 30.8 → 33.0 %, Δ **+2.21 [−0.17, +4.67]**. Truncation
  17.4 → 14.0 %, mean tokens 3,944 → 3,227, finished-response chars 9,994 → 7,660; finished-response accuracy
  37.2 → **38.3 %** (the first run above base; v8 37.9, v9 33.6, v10 34.5). By rule the chain stopped; MMMU not run.
- Split (same unbiased method; v8 / v9 / v10 / **v11**):
  - 0/4 n=132: +3.31 / +9.85 / +6.91 / **+5.87 [+3.03, +8.90]**
  - 1–3/4 n=138: +0.72 / −3.17 / −1.09 / **+1.09 [−3.53, +5.71]**
  - 4/4 n=30: −5.42 / −21.25 / −15.83 / **−6.25 [−15.00, +2.92]**
  4/4 group: finished accuracy 87.9 → 81.1 % (v10 72.8), finished chars 9,532 → 8,237 (v10 6,793).
  Reading: the long same-distribution anchor kept the solving style. The loss on solved items fell to the level of
  plain RFT (v8), which is not significant, while most of the gain on unsolved items stayed. Best result so far,
  but the gate rule is not met.

## Amendment 1 (2026-11-09 23:44, user decision after gate 1 failed narrowly; run launched 23:44)
The user chose "MMMU 5 seed 참고 평가" for the epoch-2 adapter. Merge, `SEEDS="0 1 2 3 4" bash eval.sh` →
`runs/grpo_v11_5seed`, `analyze.py compare results/seed* vs <copies without the LoRA keys>` (paired by seed and
question), the same labels as `v9_protocol.md` step 5:
- **Improvement confirmed:** Δacc (all 900) 95 % CI lower bound > 0.
- **Point estimate only:** Δacc > 0, the CI includes 0, and no format collapse (truncation and Answer-tag rates each
  within 2 points of the base).
- Otherwise: no improvement.

Because gate 1 failed, the result is **exploratory**, whatever the label. It also comes after four tests on the same
held-out set (v8–v11), and should be read with that in mind. Runs as `grpo/chain_v11_mmmu.sh` in systemd unit
`v11-mmmu` with the RAM guard.
- Amendment 1 run: seed 0 done 00:40 (11/10). Descriptive check by me of seed 0 alone, same `--base-mean 1` comparison as v8:
  63.67, Δ vs base 5-seed mean **−1.49 [−3.93, +0.98]**; base stable-correct (453) **−3.53 [−6.84, −0.44]** (v8: +1.32).
  Truncation 14.1 → 9.6 %, Answer tag 85.9 → 90.4 %, mean response 7,479 → 5,449 chars (−27 %). Seeds 1–4 continue.
  Correction (02:59): the −27 % mean is mostly fewer truncations. Per question the length ratio is 0.96 (MC 0.97, open
  0.78), and finished responses have median 2,194 → 2,038 chars (−7 %). What changed more is the checking habit:
  wait+check per 1k chars 0.77 → 0.46 (lost stable-correct items 0.52 → 0.31). The 33 lost stable-correct items
  spread over 19 subjects (Clinical Medicine 5, Public Health 4, …), outside the numeric anchor's domain. Against
  base seed 0: 97 gained, 106 lost.
- **Amendment 1 result (04:24, 11/10): no improvement** (exploratory). MMMU 5 seeds **62.04 ± 1.02** (per seed 63.67, 61.33,
  61.78, 61.11, 62.33) vs base 65.16 ± 0.93. Paired Δ **−3.11 [−4.64, −1.51]**. Truncation 15.3 → 11.2 %, Answer tag
  84.8 → 88.8 %, mean response 7,664 → 5,749 chars. MC (847) 66.78 → 63.78; open (53) 39.25 → 34.34.
  Descriptive, after the result:
  - Split chosen on base seeds 0–1, scored on seeds 2–4 for both (unbiased): unsolved 0/2 (n=225) **+7.11 [+3.41, +10.81]**;
    1/2 (n=167) −4.79 [−10.58, +0.80]; solved 2/2 (n=508) **−6.96 [−8.86, −5.05]**. Same shape as gate 1: gain on items
    the base cannot solve, loss on items it solves, and solved items are the majority on MMMU.
  - Finished responses median 2,224 → 2,039 chars (−8 %); wait+check per 1k 0.78 → 0.48. 18 subjects down, 8 up
    (worst Pharmacy −14.7, Clinical Medicine −13.3, Materials −12.7, Public Health −10.0; best Biology +8.0).

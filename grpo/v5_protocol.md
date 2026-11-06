# GRPO v5 — registered before any v5 training (2026-11-05)

v4 (v4_protocol.md, "Pause") collapsed response length: truncations became quick wrong answers and the
216-group diagnostic fell to 33.1 % (-4.4 vs v1). v5 = v4 with three fixes and one extra stop rule;
everything else (rules carried over, hard pool, 8 samples, Sonnet hints, judge, decision rule) is unchanged.

## Changes vs v4
1. Truncated responses are excluded from the loss and from their group's advantage statistics
   (DAPO-style overlong filtering): groups compare correct vs wrong *finished* answers only.
2. Reward `r = correct * (1 + 0.5 * reasoning_ok)` — no image credit (wrong answers get 0).
3. KL β = 0.01 (v3 0.04, v4 0.001).
4. Extra stop rule: 2-round mean stage-1 response length < 0.6 x round 0.

## Data order and round 0
Same pool and order as v4 (round 0 = pool[0:32], round r >= 1 = pool[16+16r : 32+16r]) so rounds pair with v4.
Round 0 reuses v4's round-0 base-model rollouts and judge verdicts (same model, same questions); only the v5
reward and loss rules are applied to them.

## Decision
As v4: r009 / r019 216-group diagnostics (seeds 5, 6) informational; r029 216 + 166; 216 delta >= +2 vs v1
(37.5 %) -> §5.5 full evaluation, else stop. A diagnostic below v1 by more than 2 SE (-5.8 pts) at r009 or
r019 also stops the run.

## Stop record (2026-11-05 04:10)
The guard stopped the chain after round 7 (8 rounds trained): stage-1 accuracy 2-round mean 0.234 (rounds 6-7:
0.250, 0.219) < 0.7 x round 0 = 0.235, missed by 0.0008 (less than one response of 256). Other guards fine:
truncation 0.18, KL 0.0056, length 2-round mean 4,087 tokens (0.82 x round 0). Paired v4 on the same questions:
0.328, 0.242 (mean 0.285), truncation 0.18, 0.09. No threshold is changed without the user's decision.
The round-7 adapter is kept as ckpt/r007; an informational 216 diagnostic (seeds 5, 6) is run on it while the
decision is pending (not a registered decision point).

## Amendment 1 (user decision, 2026-11-05 13:38; after seeing the r007 216 diagnostic)
r007 216 diagnostic: 40.97 % (seeds 5/6: 39.35, 42.59) vs v1 37.50 -> +3.47 +- 2.78 (paired SE). Correct answers
162 -> 177, but finished responses 124 -> 126; the rest come from truncated responses parsed by the official
fallback (v1 25 % vs base 5-seed 34.5 %), so the gain is weakly supported.
The user chose: run the §5.5 dev evaluation on r007 now (`SEEDS=0 bash eval.sh merged_r007 runs/grpo_v5_r007_full`,
frozen defaults incl. gpu-mem 0.90; `analyze.py compare results/seed* vs runs/grpo_v5_r007_full/seed0 --base-mean 1`).
Above the 5-seed base mean (64.93) -> continue v5 training; otherwise -> v6 (domain-matched data).
Run alongside the user's MASCOT jobs only while MemAvailable stays high; our eval is stopped if it drops below 5 GB.

## Amendment 1 outcome (2026-11-05 14:57)
§5.5 dev run, r007, seed 0, 900 questions: 63.44 vs base 5-seed mean 64.93 -> -1.49 pts, 95 % CI [-3.51, +0.56];
base stable-correct (452, held-out seeds) +0.66 [-1.55, +2.88] (no forgetting signal); truncation 14.1 -> 16.0 %.
analyze.py refused the raw dirs only because the new run_eval config carries no-op keys absent from the base
configs (enable_lora False, lora_adapter '', max_lora_rank 16); compared on a copy with those keys removed.
Below the base mean -> per Amendment 1, v5 ends here; next step v6 (domain-matched data), plan to the user first.
The 216 two-seed diagnostic (+3.47) did not hold on the full set: its gain came from truncated-response parsing.

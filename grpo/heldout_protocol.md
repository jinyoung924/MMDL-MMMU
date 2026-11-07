# Held-out pool test — do the v2 / v6 gains survive on untrained items of the same distribution?

Registered 2026-11-06 23:50, before any run of this test. User OK 2026-11-06 ("어 그러자"). Nothing below changes
after results are seen without the user's decision; any change is recorded as a numbered amendment.

## Why
- No version (v1–v6) improved MMMU val. Training-time gains were measured on trained items only (v6 Amendment 1
  paired check: 87.5 → 90.6 % and 79.7 → 89.8 %, same questions).
- MMMU val is never training data, so every version relied on transfer. This test splits the possible causes:
  does training improve (a) the trained items, (b) unseen items of the same pool, (c) MMMU val (already known: no).

## Items (fixed before any run; `random.Random(0)`, see `data/heldout/`)
| pool | seen = rolled out in training | unseen = never rolled out |
|---|---|---|
| v2 `data/pool.jsonl` (ViRL39K MC) | 100 of pool[0:1280] | 300 of pool[1280:] (2,390) |
| v6 `data/pool_v6.jsonl` (VWI Business/Tech, teacher-correct) | 100 of pool[0:480] | all 378 of pool[480:] |

Pool order was checked against `runs/v2|v6/rounds/r*.jsonl` (each round = the next 64 / 16 pool items).

## Models and sampling
- base (no adapter), v2 `runs/v2/ckpt/r019`, v6 `runs/v6/ckpt/r029` (LoRA on the base engine, as in training rollouts).
- `grpo.py screen` with `--samples 4`, T=1, top_p 1, 8,192 tokens, engine seed 0, training-time image pixels and
  prompts (the training rollout setting, so numbers are comparable to the training logs).
- 4 runs: v2 pool × {base, r019}, v6 pool × {base, r029} → `runs/heldout/{v2,v6}_{base,r019,r029}.jsonl`
  (+ `.rows.jsonl` with texts for loop analysis).

## Metrics and rule
- Per set (seen / unseen) and pool: mean per-item accuracy (correct / 4), paired by item; 95 % CI by bootstrap over
  items (10,000 resamples, seed 0). Also truncation rate and mean tokens (finished responses).
- **Gain** if the CI lower bound > 0, **loss** if the upper bound < 0, otherwise **no detectable change**
  (expected resolution about ±2.5 points for v6 unseen, ±4 for v2 unseen, ±5 for the seen sets).

## Reading (decided now)
| seen | unseen | reading → v7 direction |
|---|---|---|
| gain | gain | learning generalises inside the pool; MMMU flat → the pool is the wrong distribution (data problem) |
| gain | none | item-specific fitting; the update does not generalise even in-distribution (method / data amount) |
| none | none | training barely changed behaviour (amount / signal strength problem) |
| any | loss | training hurts even in-distribution (method problem) |

## Engineering note (2026-11-07 12:45, no rule changed)
`screen` split the ids file on whitespace; one ViRL qid contains a space, so the v2 base run stopped with a KeyError
before generating. Fixed to one id per line (`splitlines`); v6 ids have no spaces (478/478 found either way), so the
finished v6 runs are unaffected. The v2 runs were relaunched unchanged otherwise.

## Result v6 (2026-11-07 12:43; `grpo/heldout_compare.py v6 r029`, `runs/heldout/v6_r029_compare.txt`)
| set | n | base → r029 acc | Δ (95 % CI) | truncation | mean tokens |
|---|---|---|---|---|---|
| seen | 100 | 84.2 → 86.8 | +2.50 [−2.75, +8.00] | 7.8 → 2.2 % | 1804 → 1453 |
| unseen | 378 | 81.5 → 83.1 | +1.65 [−0.66, +4.03] | 5.4 → 2.2 % | 1755 → 1408 |

- Accuracy: no detectable change on either set (reading row "none / none"). Base is already 81–84 % on this
  teacher-filtered pool, so the room is small.
- Behaviour did change and it generalises to unseen items: truncation −3.11 [−4.63, −1.72] pts. On the 47 unseen
  items the base truncated at least once, truncation 43.1 → 12.8 % but accuracy only 42.6 → 46.3 (+3.7 [−6.9, +14.9]):
  responses that now finish are mostly not correct, the same pattern as MMMU (often-truncated 160 q: truncation
  70.6 → 60.0 %, accuracy flat). On MMMU the drop was much smaller (14.1 → 12.1 %).

## Result v2 (2026-11-07 15:34; `grpo/heldout_compare.py v2 r019`, `runs/heldout/v2_r019_compare.txt`)
| set | n | base → r019 acc | Δ (95 % CI) | truncation | mean tokens |
|---|---|---|---|---|---|
| seen | 100 | 66.8 → 68.2 | +1.50 [−2.25, +5.25] | 13.8 → 12.5 % | 2782 → 2634 |
| unseen | 300 | 61.7 → 61.8 | +0.17 [−2.58, +2.83] | 12.2 → 9.5 % | 2986 → 2800 |

- Accuracy: no detectable change on either set, even on trained items (the training-time "+6.4 ± 1.5" was measured
  right after each update on that round's questions; it did not persist to r019). Truncation on unseen items:
  −2.67 [−4.58, −0.75].

## Exploratory (not registered): do the avoided truncations become correct?
Selecting items by base truncation and scoring the same base samples is biased (regression to the mean: with the
same samples the selected group showed +8.1 [+2.2, +14.0] for v2). Unbiased version: select on base samples 1–2,
score base samples 3–4 against all 4 tuned samples (unseen items).

| pool | group | n | base acc / trunc | tuned acc / trunc | Δacc (95 % CI) |
|---|---|---|---|---|---|
| v2 | base truncated in samples 1–2 | 55 | 25.5 / 53.6 % | 31.8 / 40.5 % | +6.36 [−1.82, +14.55] |
| v2 | rest | 245 | 70.4 / 2.9 % | 68.6 / 2.6 % | −1.84 [−5.51, +1.73] |
| v6 | base truncated in samples 1–2 | 36 | 50.0 / 33.3 % | 45.1 / 11.8 % | −4.86 [−17.36, +8.33] |
| v6 | rest | 342 | 85.2 / 2.0 % | 87.1 / 1.2 % | +1.90 [−0.73, +4.53] |

## Conclusion (reading row "none / none" for both v2 and v6)
Neither recipe raised accuracy even inside its own training distribution, on trained or untrained items. What
training did change, and what generalises to unseen items, is length and termination (fewer truncations, shorter
answers). The avoided truncations do not reliably become correct answers (here, on MMMU r029, and at 32k tokens).
So the MMMU null is not only a transfer / data-distribution problem: the update itself does not improve solving.

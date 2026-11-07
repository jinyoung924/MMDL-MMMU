# v7 prep — is Qwen3-VL-30B-A3B-Instruct (4-bit AWQ) a stronger teacher?

Registered 2026-11-07 16:10, before any download or run. User OK 2026-11-07 ("그러자. 그럼 30B 모델을 양자화 해서 진행?").
Nothing below changes after results are seen without the user's decision; changes are numbered amendments.

## Why
- Held-out pool test (`heldout_protocol.md`): v2 and v6 did not raise accuracy even inside their own training
  distribution; only length and truncation changed. The v6 teacher (8B-Instruct-FP8, 68.56 on our eval) is only
  +3.4 above the base, so its signal may be too weak to teach solving.
- Qwen3-VL-30B-A3B-Instruct reports MMMU 74.2 (official). The official FP8 checkpoint (~31 GB) does not fit the
  24 GB GPU, so a 4-bit checkpoint is needed.

## Teacher checkpoint
- `QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ` @ `a5ea10732e2c9330957864ece3ec66d806a4b00d` (most downloaded 4-bit
  version, 17.9 GB): AWQ 4-bit, group 128; the vision tower and MoE router (`mlp.gate`) are not quantised.
  Third-party quantisation of the official Qwen checkpoint; used only as a teacher, never inside the submitted model.
- Checked before download: tokenizer.json, vocab, merges, tokenizer_config and preprocessor_config are byte-identical
  to the 4B student @ebb281ec; the chat template is the same after JSON parsing (whitespace only). So the teacher can
  score the student's exact tokens (needed for on-policy distillation).

## Checks
| check | run | rule |
|---|---|---|
| T1 engineering | loads in vLLM 0.24 on the 24 GB GPU with run_eval defaults | if batch-invariant mode does not support the AWQ MoE kernels, run T2 with `--batch-invariant 0` and record it |
| T2 strength | `run_eval.py --model QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ --model-revision a5ea107…` seed 0, 900 q, frozen defaults → `runs/diag_teacher_30b_a3b_awq/seed0` | **teacher candidate** if both: (a) accuracy ≥ 70.56 (= 8B teacher 68.56 + 2.0), (b) correct on ≥ 60 % of the student's 1–3/5 group (`grpo/data/ids_216.txt`; 8B: 52.8 %). Otherwise the stronger-teacher direction stops and is reported |
| T3 cost (only if T2 passes) | `grpo.py teacher-score` with the 30B teacher on a copy of v6 round r000 (128 student samples) | no rule; memory, time and reverse KL vs the 8B teacher on the same samples, for the v7 budget |

Also reported for T2 (descriptive): 0/5 group solve rate (`ids_166.txt`; 8B: 17.5 %), truncation, discipline scores.
Diagnostic evaluation on MMMU val only; MMMU val is never training data.

## T1 result (2026-11-07 19:00, engineering)
- Batch-invariant mode: vLLM 0.24's only usable 4-bit MoE kernel (Marlin) does not support it ("kernel does not
  support batch invariance"). By the T1 rule, T2 runs with `--batch-invariant 0` (outputs not bit-reproducible;
  teacher diagnostics only).
- Memory: weights 17.0 GiB; at the default `--gpu-mem-util 0.90` only 1.95 GiB KV is left (< 2.25 GiB for one
  24,576-token request). T2 uses 0.935 (2.51 GiB, 27,376 KV tokens); the GPU has 23.51 GiB, the display uses ~1 GiB.
  Neither setting changes the prompt, decoding or scoring.
- 8-question smoke test (first 8 of `ids_216`): loads with the Marlin backend, ~310 output tok/s, 2.8 min.
- T2 launched 19:02 as systemd unit `v7-t2` (+ `v7-t2-watch` RAM guard).

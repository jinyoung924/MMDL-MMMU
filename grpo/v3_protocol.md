# GRPO v3 — registered before any v3 run (2026-11-03)

Change vs v2: training data and reward. Loop settings unchanged (LR 1e-4, 64 q/round, 4 samples + 4 more
if none correct, 4 groups/step, KL β 0.04, clip 0.2). Thresholds below are fixed; they are not changed
after seeing results.

## Rules carried over
- Shared team `main` is never touched; no commit/push. MMMU val never enters training (text + image
  overlap check below). No MMMU-Pro, no MMMU test split, no Chinese-language data.
- Geometry3K DEV reviews (120 teacher-judged responses) are used only to validate the judge, never as
  training data. CONF stays closed.
- Evaluation = frozen `run_eval.py` defaults on a LoRA-merged full checkpoint (submission form: no added
  layers). Final verdict = improvement_strategy.md §5.5: `SEEDS=0 bash eval.sh <merged> runs/grpo_v3_final`
  then `analyze.py compare results/seed* vs runs/grpo_v3_final/seed0 --base-mean 1`.

## Data
TIGER-Lab/VisualWebInstruct-verified @0e54d116 (answers verified by Gemini 2.5 Pro, step-by-step
reference solution per item). Keep: one image, no CJK, numeric short answer. Exclude every item flagged by
the BMMR-audit overlap rules against MMMU val (normalized exact, 5-gram >= 8 and >= 80 %, image pixel
SHA-256, dHash <= 4).

## Reward
`r = 1.0 * correct + 0.5 * image_ok + 0.5 * reasoning_ok`; truncated response -> r = 0.
correct = last `Answer:` number within 1 % (relative) of the gold number. image_ok / reasoning_ok =
verdicts of a frozen judge (base weights, adapter off, greedy) given image, question, reference solution
and the student response.

## Judge gate (on the 120 teacher-judged Geometry3K DEV responses)
Pass iff all three hold; unparseable verdicts count as disagreement.
1. IMAGE verdict vs teacher `stage_status.image_facts` (pass/fail): agreement >= 80 %.
2. REASONING verdict vs teacher `final_proof_valid` (True/False; None excluded): agreement >= 80 %.
3. False pass (judge VALID where teacher False) <= 10 %.
Try Qwen3-VL-4B-Instruct first, then Qwen3-VL-8B-Instruct. If neither passes, v3 runs with
`r = correct` only (data change alone).
Domain check: 30 VWI judgments re-judged by Claude subagents before training; reported, not a gate.

## Stop rules (checked after every round)
- stage-1 correctness, 2-round mean < 0.7 x round 0
- stage-1 truncation > 0.35, or KL > 0.1 per token
- reward hacking: 2-round mean judge score (image_ok + reasoning_ok) >= round 0 + 0.3 while 2-round
  mean correctness <= round 0

## Decision
- r009, r019: 216-group diagnostic (merged, seeds 5 and 6) vs v1 r009 (near-base, same seeds, 37.5 %).
  Informational only.
- r029: same diagnostic. Delta >= +2 pts -> §5.5 full evaluation (seed 0); its candidate rules decide
  whether the 5-seed final runs. Delta < +2 -> stop, report negative.

## Gate outcome (recorded 2026-11-03, before any v3 training)
| judge | IMAGE agree | REASONING agree | false pass | gate |
|---|---:|---:|---:|---|
| Qwen3-VL-4B-Instruct | 0.812 | 0.856 | 0.333 (14/42) | fail |
| Qwen3-VL-8B-Instruct-FP8 @9cdc6310 | 0.838 | 0.901 | 0.214 (9/42) | fail |
Neither passes -> as registered, v3 runs with `r = correct` (VWI data change alone). The subagent domain
check was for the judge and is not run. Details: judge_validation_*.json.

## Amendment 1 (2026-11-03, before any judge result for this configuration)
User decision: judge = **Claude Haiku 4.5 via Claude Code subagents** (Agent tool, `model: haiku`); no API key.
- Data fix first: round 0 of the aborted run showed the one-number gold rule admitting non-numeric answers
  ("R1 is the input resistor.", "B) 3 L", "a_n < 0"). Gold is now `[var =] number [short unit]` only and
  multiple-choice-style questions are dropped (`prepare_vwi.py`); pool rebuilt, 8,091 items. The aborted
  run is kept in `runs/v3_aborted_badgold/` (no training step ran).
- Format: one subagent grades the finished responses of 4 questions (packet file: image path, problem,
  reference solution, responses). Instructions are frozen in `judge_instructions.md`; the grading criteria
  are the JUDGE text used for the Qwen judges, verbatim. The subagent returns only a JSON verdict list.
- Gate: the same 120 responses (24 questions x 5) in the same format (6 subagents), same three thresholds,
  run once. If it fails: stop and ask the user (no automatic fallback).
- Subagent verdicts are not deterministic; the gate measures this configuration as a whole.
- Loop: rollout -> packets -> loop waits for `judge/rNNN/DONE` -> rewards applied -> train -> guard.

## Gate outcome, Amendment 1 (Haiku 4.5 subagents)
IMAGE 0.812, REASONING 0.847, false pass 0.381 (16/42; 14 of the 19 "correct letter, invalid reasoning")
-> fail; stopped and asked the user. Manual audit of the 5 items all three judges passed: 4 genuinely invalid
(false similarity, misread parallel arrows, wrong segment labels), 1 borderline (R011). Thresholds unchanged.

## Amendment 2 (2026-11-03, user decision, before any result)
Judge = Claude Sonnet 5.5 via subagents (`model: sonnet`, verified to resolve to claude-sonnet-5-5).
Identical packets, identical instructions, identical thresholds; run once. If it fails: stop and ask.

## Gate outcome, Amendment 2 (Sonnet 5.5 subagents, session effort)
IMAGE 0.863, REASONING 0.910, registered false pass 0.143 (6/42) -> fail under the registered rule.
All 6 carry IMAGE = INCORRECT (Terra also failed image_facts in 5 of them); 0 of the 42 teacher-invalid
responses received full process credit. Full-credit counts for the other judges: 4B 14/42, 8B 9/42, Haiku 9/42.

## Amendment 3 (2026-11-03, AFTER seeing the Amendment 2 result; user decision, post hoc)
The registered false-pass metric compares REASONING alone with the teacher's whole-proof validity, which
also counts image misreadings, while the reward scores image and reasoning separately. Replacement
criterion, approved by the user after seeing results: no teacher-invalid response may receive full process
credit (image_ok = reasoning_ok = 1). IMAGE >= 80 % and REASONING >= 80 % unchanged. Both criteria are
reported for every judge. Under it: Sonnet 5.5 (session effort) passes; 4B, 8B, Haiku fail.

## Amendment 4 (2026-11-03, before any result; user decision)
User asked for the lowest effort. Subagent effort is set only by an agent definition file
(`.claude/agents/sonnet-judge.md`: model sonnet, effort low, tools Read), which needs a session restart to
load. A low-effort judge is a different configuration, so it gets one gate run (same packets and
instructions, Amendment 3 criterion). Pass -> train with it. Fail -> train with the validated
session-effort Sonnet judge (Amendment 2/3), no further variants.

## Amendment 4b (2026-11-03, before any result; replaces the agent-file mechanism of Amendment 4)
The agent file cannot load without a session restart. Same intent (judge session at the lowest effort)
via headless Claude Code: one `claude -p --model sonnet --effort low --tools Read --strict-mcp-config
--system-prompt <short grader prompt>` session per packet (verified: resolves to claude-sonnet-5-5; MCP
off cuts per-call overhead from ~94k to ~4k tokens). Instructions = judge_instructions.md verbatim.
A reply counts only if its ids equal the packet's ids in order (one retry; otherwise unparsed). The loop
calls it directly (JUDGE_MODEL=cli). Gate: one run on the 120, Amendment 3 criterion; fail -> session-effort
Sonnet via Agent-tool subagents (validated), no further variants.

## Gate outcome, Amendment 4b (low-effort headless Sonnet 5.5)
IMAGE 0.829, REASONING 0.946, registered false pass 0.024 (1/42, R011) -> passes the original rule;
full-credit false pass 1/42 (R011) -> fails the Amendment 3 rule. Cost $1.40, 79 s for the 120.
Correct answers: valid-proof mean reward 1.86 vs invalid-proof 1.11 (session-effort Sonnet: 1.85 / 1.16).

## Amendment 5 (2026-11-03, AFTER seeing the 4b result; user decision, post hoc)
The user chose to train with the low-effort headless Sonnet judge. Reasons recorded: it passes the
originally registered criterion; its single full-credit case is R011, which a manual audit rated borderline
(wrong description of angle 2's rays, correct core relation); the "0 cases" threshold of Amendment 3 was
fit to the previous result rather than set like the original 10 % rate. Both criteria stay reported.
v3 = VWI strict pool + reward `correct + 0.5 image_ok + 0.5 reasoning_ok` from this judge (JUDGE_MODEL=cli).

## Amendment 6 (2026-11-03, round-0 check, before any training step)
Round 0 (64 q, 274 finished responses) showed 21 "wrong by grading, judged fully valid" responses, all from
3 questions: number words ("zero" for 0), unit prefixes (31384 VAR for 31.4 kVAR) and one wrong VWI gold
(inscribed angle ABC: gold 110°, correct 70° since angle AOC = 360 - 100 - 120 = 140°; 7/7 students and the
judge said 70). Fixes: number words zero..twenty are parsed; a value within 1 % of gold x 10^±3 counts as
correct; a group whose finished responses are >= 50 % "graded wrong but judged image_ok = reasoning_ok = 1"
is treated as suspect gold and skipped (logged). Grading is recomputed from the response text at judge-apply.
- 2026-11-03 23:15 engineering: rollout vLLM max_num_seqs=64 after a round-1 sampler OOM next to other GPU jobs (no effect on the method).
- 23:20 restart after the round-1 OOM: MEM 0.68 + max_num_seqs=64; resumes at round 1 (round 0 trained).

## Stop (2026-11-04 04:25, user decision)
v3 stopped during round 10 (rounds 0-9 trained). r009 216-group diagnostic (merged, seeds 5/6): 37.50 / 39.81,
mean 38.7 % vs v1 near-base 37.5 % -> +1.2 ± 2.8 pts; truncations 155/432 (v1 152). Training-question stage-1
accuracy 76.8 % (rounds 0-2) -> 78.5 % (rounds 7-9), within noise. Recorded as "stopped at round 10,
improvement not confirmed" (no r029 verdict). Diagnosed limits: 67 % of pool items are 4/4 for the base,
process credit is given to wrong answers, KL 0.04.

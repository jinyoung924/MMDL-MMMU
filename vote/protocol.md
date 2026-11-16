# Majority vote (self-consistency) on the frozen pipeline

Registered 2026-11-14 03:55, before the confirmation runs. Nothing below changes after results are seen without the
user's decision; any change is recorded as a numbered amendment.

User decision (2026-11-14, after the Music line was stopped): "그래. 진행해. 우선 점수 조금이라도 올리기를 목표로 계속
해보자" — use the majority vote as the improvement that is measured, and write up the training attempts.

## What it is
The base model answers each question k times with the frozen pipeline (same prompt, sampling recipe and token
budget, k different seeds) and the most frequent answer is scored. No weight changes. Cost: k times the inference.

## Rule (`python analyze.py vote RUN...`, functions `answer_key` and `voted`)
- A multiple-choice response votes for the letter the frozen pipeline scored, unless that letter was the parser's
  random guess (`fallback_guess`), which does not vote.
- An open response votes for the last number in its "Answer:" line, else for the text of that line. Without such a
  line (for example a response cut off at the token limit) it does not vote.
- The most frequent answer wins; a tie goes to the answer of the earliest run; if no response votes, the first
  run's stored result stands.

## What is already known (exploratory)
On the official seeds 0–4 (`results/seed*`): single run 65.16 ± 0.93, majority of 5 **67.89**, paired gain +2.73
[+1.42, +4.09]; majority of 3, mean over the 10 subsets, 66.63. These seeds were looked at while the rule was
written (a stricter variant in which only responses with an "Answer:" line vote gave 67.67), so they do not confirm
the rule.

## Confirmation
- Runs: the base model on five new seeds, `SEEDS="5 6 7 8 9" bash eval.sh Qwen/Qwen3-VL-4B-Instruct runs/base_vote`
  (frozen pipeline, batch-invariant mode, same machine as the official seeds).
- **Primary:** the majority of seeds 5–9 against the single-run mean of seeds 5–9, paired by question, bootstrap
  over questions. Confirmed if the 95 % CI lower bound of the gain is > 0.
- Also reported: the majority score against the official single-run mean 65.16; the majority of all ten runs;
  the mean over all 252 five-run subsets of the ten (the best estimate of what a vote of 5 gives); majority of 3.

## Limits
- This changes the inference procedure, not the model. A fine-tuned model must be compared with the base under the
  same procedure on both sides. Whether the course accepts it as the improvement is the user's to check.
- Cost is k times the frozen pipeline (about 75 minutes per run on this machine).

## Run log
- 2026-11-14 03:55: confirmation runs launched (unit `basevote`, RAM guard `basevote-watch`, log
  `runs/base_vote/run.out`).
- 2026-11-14 10:17: the five runs finished without errors (seeds 5–9: 64.11, 63.67, 63.33, 63.78, 66.56).
  - **Primary: confirmed.** Single run 64.29 ± 1.30, majority of seeds 5–9 **67.33**, paired gain **+3.04
    [+1.76, +4.36]** (`runs/base_vote/vote_5to9.txt`). Majority of 3 over the 10 subsets: 65.90.
  - Against the official single-run mean 65.16: +2.17 (different seeds, not paired).
  - All ten runs (`runs/base_vote/vote_all10.txt`): single run 64.72 ± 1.16, majority of 10 67.56, paired gain
    +2.83 [+1.50, +4.12]. Majority of 5 over the 252 subsets: mean **66.94** (SD 0.68, min 64.89, max 68.78);
    each subset against its own single-run mean: +2.21 on average (min +0.84, max +3.89). Majority of 3 over the
    120 subsets: 66.20.
  - The new seeds' single-run mean is 0.87 below the official one; this is inside the seed spread (SD about 1.2),
    and the base re-run of seed 0 on Music (`runs/base_music_check`) reproduces the official responses 30/30, so
    the environment has not drifted.
  - Order of the runs (tie rule): reversing it gives 67.44 for seeds 0–4 and 67.00 for seeds 5–9.
  - Where the gain of seeds 5–9 sits: questions solved in 3 or 4 of the 5 runs become correct (158 of 159);
    questions solved in 1 of 5 become wrong (1 of 83 correct); 2 of 5: 23 of 63.
- 2026-11-14 10:20, tooling note: the all-ten step of the unit stopped at the config guard of `analyze.py`
  (`check_comparable`): the official runs were recorded before `run_eval.py` had its LoRA options, so their
  `scores.json` lacks the three keys that the new runs record at their off values. The guard now reads missing
  LoRA keys as off (it still refuses a different model or subject list); the all-ten numbers come from the same
  command, run by hand. No file under `results/` was written.
- 2026-11-14 11:10, exploratory (no new runs): the same vote on the three fine-tuned models that have five full
  seeds (seeds 0–4), against the base vote 67.89, paired by question: reading SFT round 2 68.00 (+0.11
  [−2.00, +2.22]), round 1 66.22 (−1.67 [−3.89, +0.56]), SDFT v11 65.22 (−2.67 [−5.44, +0.11]). None beats the
  base under the vote. Noise floor: two votes of 5 from the same base model (126 disjoint splits of the ten
  runs) differ by 0.94 on average, 2.33 at the 95th percentile, with about 98 questions voted differently;
  base vote of seeds 0–4 against seeds 5–9: −0.56 [−2.78, +1.67].
- 2026-11-14 11:15, reading of the course handout (`assignment_guidance.md` §0): a comparison is meaningless if
  the scoring or generation procedure differs between the two runs. The vote is therefore not a before/after
  improvement over the single-run baseline 65.16; it is compared only vote against vote. Whether a voted score
  is accepted as a separate result is for the instructor to say.

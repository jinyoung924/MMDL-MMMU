# StructReward replication

Registered 2026-11-14 17:43, before any training. Nothing below changes after results are seen without the user's
decision; any change is recorded as a numbered amendment.

User decision (2026-11-14): "StructReward 방식을 그럼 그대로 해보고, 그 이상을 노려보자 그럼" — reproduce the method as
published first, then try to go beyond it.

## Why
- StructReward (Sun, Zhao, Li; arXiv 2608.08326 v2) is the only study found that reports an MMMU gain on our exact
  model without training on evaluation data: Qwen3-VL-4B-Instruct 67.4 → 70.3 (their evaluation, one checkpoint,
  no seeds or confidence intervals; without the strong-LLM rewriting 69.4, without judgment/choice tasks 68.9).
- Three of its parts are things we have not tried: a reward that matches the steps of a response to the steps of a
  reference solution by rule, an SFT warm-up before the RL, and training data that mixes many domains.
- Parts that conflict with our own results: SFT on solutions written by another model lost points on questions the
  base already solved (v9–v11), and no GRPO run improved unseen questions (v2, v6 held-out tests).

## What the paper fixes, and we follow
- Data: VisualPRM400K-v1.1. Cold-start SFT on 5,000 examples with 3–12 steps; selection balances source subsets and
  ranks by reasoning length 0.42, number of steps 0.23, visual dependence 0.20, label quality 0.10, format validity
  0.05. RL on 1,000 prompt groups disjoint from the SFT set, one reference trajectory each, correct steps only.
- Format: one `<think>…</think>` block, `Step i:` markers from 1, a `\boxed{}` local result in every step, then a
  separate final answer.
- Reward: `R = 0.10·fmt + 0.25·right + 0.75·right·rule·(1 + 0.15·cons)`; `rule` = share of generated steps whose
  result matches a reference result, in order, each reference result used once.
- GRPO: 8 responses per question, groups without reward spread skipped, clip 0.2, KL coefficient 0.001 against the
  frozen cold-start policy.
- Auxiliary tasks from the same rollouts: pointwise Correct / Incorrect and pairwise A / B (stage B); single-step
  rewrites by a strong LLM for error detection (stage C).

## Our choices where the paper is silent (`structreward/sr.py`)
1. **Data version.** `OpenGVLab/VisualPRM400K-v1.1-Raw` (the same trajectories with the ground-truth answer and the
   per-step Monte-Carlo score). Only trajectories labelled to the end, whose last step is `Final answer: …` with
   score 1 and whose answer passes our own answer check, are used. A step is correct if its score is > 0.
2. **Sources.** The domains the paper names (science, geometry, functions, physics, biology): ScienceQA, M3CoT,
   AI2D, Geometry3K, GEOS, Geo170K, GeomVerse, MAVIS-Geometry, MAVIS-Function — nine subsets. Left out: the Chinese
   sources (UniGeo, GeoQA+; project rule) and the counting, chart, document and photo sources.
3. **Question kinds.** Lettered multiple choice, AI2D's unlettered options (letters assigned), and open questions
   with a numeric answer. Prompts are written exactly as `run_eval.build_prompt` writes MMMU prompts, CoT suffix
   included, so that what is learned is tied to the prompt of the frozen evaluation.
4. **Local result of a step** (`local_result`): right-hand side of the last formula that contains an equation or a
   digit; else the last plain `= value`; else an option letter; else yes / no / true / false; else the last number.
   A step without any of these joins the next step.
5. **Selection features.** Length = characters of the original steps; steps = number of normalized steps (both as
   rank within the subset); visual dependence = share of steps that mention the image; label quality = mean step
   score; format validity = share of original steps with a local result. Questions are taken subset by subset in
   turn, one per image; a subset that runs out passes its share on.
6. **Matching** (`match`): numbers within 1 % (`grpo.close`, the tolerance of our earlier runs); everything else
   equal after removing spacing, `\text{}`, `\left`/`\right` and equivalent LaTeX spellings.
7. **Training settings.** LoRA r 16, α 32 on the language-model linear layers (merged before evaluation, so the
   evaluated model has no added modules). SFT: LR 1e-4, 2 epochs, 16 examples per update, seed 0 (`grpo/rft.py`).
   RL: LR 1e-4, 20 questions × 8 responses per round, 50 rounds, 4 groups per update (`grpo/grpo.py`).
8. **Splits** (seed 0): held-out 300 questions and the RL pool 1,000 are drawn at random first, the SFT 5,000 from
   the remaining images; no image is shared between or within splits.

## Deviations forced by our setup
- **D1, answer line.** The final answer is our pipeline's `Answer: X` line after the reasoning block instead of a
  boxed answer; the frozen parser reads that line. `right` is our pipeline's answer check.
- **D2, MMMU overlap.** Items that hit MMMU by question text or image are dropped (`grpo/prepare_virl.mmmu_overlap`:
  exact and 5-gram text overlap with the 900 val questions; pixel hash and dHash distance ≤ 4 against MMMU dev,
  val and test images).
- **D3, existing GRPO code.** Advantages use the sample standard deviation with ε 1e-4 and no clipping at ±3 (with
  8 responses the clip cannot bind); the loss is averaged over all tokens of an update rather than per response;
  responses cut at the token limit are left out of training (our v5 lesson).
- **D4, stage C.** The paper rewrites steps with a strong LLM. Which model does this here is the user's decision
  and is taken before stage C; stages A and B do not need it (the paper's 69.4 variant).

## Stages and registered rules
**Stage A — cold-start SFT** (`structreward/chain_a.sh`). Checks after training:
1. Held-out 300, 4 samples each: at least 80 % of the responses have the valid format (else the reward has nothing
   to read and the run stops). Accuracy against the base on the same questions is reported.
2. MMMU dev: 900 questions, seed 0, frozen pipeline. If the score is ≤ 63.06 (2.1 below the base mean 65.16, the
   single-seed detection limit of improvement_strategy.md §5.5), the as-published line stops here and the next
   step is the user's decision. Otherwise stage B runs.
3. MC check (289 held-out multiple-choice items, as in v12): reported, not a gate.

**Stage B — structured-reward GRPO + judgment/choice tasks**, on top of the merged stage A model. MMMU dev (seed 0)
after rounds 24 and 49; ≤ 63.06 at round 24 stops the run. The length and accuracy guards of v6 stay on.

Stage B details (added 2026-11-14 17:48, while the stage A SFT was at its first steps and before any stage A result;
`structreward/chain_b.sh`):
- Each round: rollout (`grpo.py rollout`, temperature 1.0) → `sr.py reward` → `sr.py aux` → `grpo.py train` → guard.
- Judgment/choice examples per round, from finished responses only: one pointwise example per question (a random
  response; target `Correct` or `Incorrect`) and one pairwise example per question that has both outcomes (one
  right and one wrong response in random order; target `A` or `B`). The question is shown without the CoT
  instruction, each response cut at 6,000 characters. Trained after the GRPO updates of the round with plain
  cross-entropy, 8 examples per update, same optimizer and learning rate.
- Guards (`grpo.py guard`): accuracy of the last 4 rounds below 0.7 × round 0; more than 35 % of responses cut at
  the token limit; KL above 0.1; finished length relative to the reference solution of the same question below
  0.6 × its round-0 value.
- Checkpoints after rounds 24 and 49 (`--ckpt-every 25`), merged into the stage A model for evaluation.

**Stage C — strong-LLM rewriting** (see D4), only if stage B ends above the stage A model.

**Final.** A stage B or C model with dev score above the base mean goes to 5 seeds, with the user's agreement.
Adopted if the paired difference to the base (5 seeds) is ≥ 0 overall; a gain is claimed only if its 95 % CI lower
bound is > 0.

## Beyond the paper (candidates, not started; each needs the user's decision)
- Cold start on the base model's own correct solutions written in the structured format (own-target principle),
  instead of another model's solutions.
- Own long solutions as anchors in the SFT stage (v11–v12, reading-SFT rounds 1–2).
- The same vote at inference on both sides (`vote/protocol.md`).

## Amendment 1 (2026-11-14 20:45) — stage A2: cold start on the base model's own solutions
User decision (2026-11-14, before the MMMU result of stage A was in, after I had pointed out that the SFT targets are
about half as long as the base's own solutions): "어 이어서 진행. 그럼 일단 structreward 를 따라서 해보고 이게 안되면
base 자기 풀이로 준비 SFT 로 해보자". Stage A then failed gate 2 (run log), so A2 starts. This amendment was written
after the stage A results were seen and before any A2 data existed.

One thing changes against stage A: **who wrote the SFT targets.** Everything else (the 5,000 questions, the format,
the training settings, the three checks and their thresholds, stage B on top) stays.
- The base model solves the 5,000 SFT questions itself, 2 samples each at temperature 1.0 (`grpo.py screen`), with
  one instruction added before the CoT suffix that asks for the structured format (`FORMAT` in `sr.py`).
- Kept: finished responses that are correct and pass the format parser; one at random per question (seed 0).
  Training uses the normal prompt without the format instruction (as in v9).
- If fewer than 3,000 questions have a usable response, the questions without one get 2 more samples (seed 1); if
  still fewer than 3,000, the run stops.
- Script `structreward/chain_a2.sh`; names `sr_sft2`, stage B run `sr_rl2`. Stage B starts by itself if both gates
  pass.

## Amendment 2 (2026-11-15 02:57) — stage A3: own solutions formatted by rule, with a target check before training
User decision (2026-11-15, after the stage A failure analysis and the target measurements in the run log, 02:26 and
02:29): "어 그니까 진행해보자", on my proposal to run the own-solution cold start with a check of the targets before
training and with boxes on derived values only. Written before any target was built with the final rule. Known
beforehand from the saved responses: about 4,600 questions have a usable own solution under the earlier rule (run
log 00:14, 01:41).

Changes against Amendment 1 (the questions, the training settings, the three checks with their thresholds and stage B
stay):
- Targets: the base's own finished, correct responses to the format instruction, already collected for A2 (no new
  generation). The base wrote the numbered steps; the tags and the boxes are added by rule (`sr.py own_target`): the
  text is cut at the base's own "Step n:" lines, the result of a step is found by `local_result`, a step without one
  joins the next. Responses in which the base wrote part of the markup itself are left out. At least 3 steps, no
  upper limit.
- Box rule: a step before the last one whose result only restates a number of the question text has no result of
  its own (`givens`, `restated`). The same filter is applied to the reference results when responses are scored
  (`load_pool`: held-out report and stage B reward), so restating given numbers earns no process reward.
- Selection: per question the longest usable solution. Fewer than 3,000 questions with one: stop.
- Gate 0, before training (`sr.py check_targets`): "=" signs per solution and the share of solutions with a
  self-check word, weighted to the targets' mix of subsets, against the base's own finished solutions on the
  held-out questions (no instruction) and against the stage A targets. Pass: both above the midpoint of those two.
  Fail: no training. Reported with it: length, share of boxes that restate a given number, share of boxes without
  a digit or option. I also read a sample of the targets before the launch and note what I see in the run log.
- Names `sr_sft3`, stage B `sr_rl3`; script `structreward/chain_a3.sh`. Stage B starts by itself if gates 1 and 2 pass.

Limits known before the run: the gate 0 thresholds were set after rough values of the own solutions were known (run
log 02:29); two things change at once against stage A (who wrote the solutions, the box rule), so the outcome cannot
be attributed to one of them; the SFT strength is unchanged; values read off the image are not in the question text,
so a step that only reads one off still gets a box.

## Amendment 3 (2026-11-15 03:01) — stage A3 on the base's solutions as written (no tags, no boxes)
Why: the Amendment 2 targets passed gate 0, but the boxes our rule adds are wrong too often (run log 03:00: the last
box agrees with the answer line in 68.1 % of the targets). The user's go ("어 그니까 진행해보자") was given on the
understanding that such defects are removed before training; the sure way to train in no wrong box is to add none.
Written after seeing the Amendment 2 targets and before any training.

Changes against Amendment 2:
- Targets: the selected own responses exactly as the base wrote them: plain numbered steps ("Step n:" lines, at
  least 3, then the answer line). Nothing is added by rule. Selection (longest per question), the 3,000 rule, gate 0
  and the SFT settings stay.
- Gate 1 reads the plain numbered-step format (`sr.py numbered`; `sr.py heldout sft3 steps`), at least 80 % on the
  held-out questions. Gate 2 (MMMU dev seed 0 above 63.06) and the MC check stay.
- Stage B does not start by itself. Its reward reads boxed results, which this model will not write; how step
  results are read, and whether that reading is reliable, is settled with the user and registered before stage B.
- What this stage can show: whether an SFT on the base's own solutions keeps the MMMU score (the prompted
  reference is 64.67, run log 01:41). A cold start is not expected to raise the score by itself.
- Script `structreward/chain_a3.sh`.

## Amendment 4 (2026-11-15 15:18) — stage B on the stage A3 model: step results read by rule from plain steps
Why: the user's go ("진행해 보자 그럼") after the stage A3 report and the offline reading analysis (run log 07:26).
The stage A3 model writes plain numbered steps and no boxes, so the registered reward has nothing to read. Written
before any stage B rollout.

Changes against the registered stage B:
- Cold start `grpo/runs/sr_sft3/merged` (rollouts, training and the KL reference); run name `sr_rl3`.
- Reading (`sr.py read_steps`; `sr.py reward RUN ROUND steps`): the format is valid if the response is plain numbered
  steps (`numbered`, gate 1 of Amendment 3); the result of a step is `local_result` of its text; a step without a
  readable result stays in the denominator of the rule term as an unmatched step; consistency = the last readable
  result agrees with the answer line. Reference results as in `load_pool` (restated question numbers left out).
- Unchanged: the reward formula and weights (eq. 10), the judgment/choice tasks, 50 rounds × 20 questions × 8
  responses, the guards, dev evaluations after rounds 24 and 49, and the floor (dev ≤ 63.06 at round 24 stops).
  The floor lies 0.38 below the cold start (63.44), so seed noise alone can trigger it; it is not moved.

Known before the run (saved responses of the stage A3 model on the held-out 300, 4 each, scored with this reading):
- Format 97.3 %, right 92.3 %, rule 0.334 (0.354 for right and 0.100 for wrong responses), consistency 0.678,
  4.9 steps per response.
- 255 of the 300 questions have all four responses right, and in 237 of those the reward still differs between the
  responses (mean spread 0.216). Most of the training signal is therefore the process term among correct solutions,
  not right against wrong.
- Among correct solutions of the same question the longer one tends to score lower on the process term (mean
  within-question correlation of length and rule −0.15, negative in 60 % of 259 questions): the reward leans towards
  shorter solutions. The registered length guard (finished length relative to the reference below 0.6 × its round-0
  value stops the run) is the protection; steps per response are logged every round (`runs/reward_sr_rl3.log`).
- What a result can show: dev after rounds 24 and 49 against the base mean (65.16; one seed, detection limit 2.1)
  and against the cold start on the same seed (63.44). A gain is claimed only under the rule of "Final".

Launch: `COLD=sr_sft3 RUN_NAME=sr_rl3 STEPS=steps bash structreward/chain_b.sh` (unit `sr-b3`, log
`structreward/runs/chain_b3.out`).

## Amendment 5 (2026-11-15 17:31) — stage B again with the step-merging hole closed
Why: the first stage B run raised its reward by merging the solution into one step (run log 16:38) and was stopped
by the KL guard. The user's decision: "보상의 허점은 막아야지." Written before any rollout of the new run; the
result of diagnostic 3 (MMMU dev of the stopped adapter) is not known yet.

Changes against Amendment 4:
- Rule term (`sr.py rule(..., over)`; `sr.py reward RUN ROUND recall`): matched results divided by the number of
  *reference* results instead of the number of generated steps. The alignment (in order, a reference result used
  once), the reading of step results, the reference filter and every other term and weight of eq. (10) stay. This
  departs from the paper's eq. (7).
- Why this form and not a two-sided one (matches over the larger of the two counts, or F1): any share over the
  generated steps counts a step without a counterpart in the reference as a loss, and that includes the model's own
  checking steps, whose loss went with the MMMU losses of stage A and v11. Measured on saved responses (stage A3
  model, held-out; first and last rounds of the stopped run), among right responses of the same question:

  | rule term | one-step minus multi-step | corr(length, rule) | corr(steps, rule) | right minus wrong |
  |---|---|---|---|---|
  | paper, z / generated | +0.17 … +0.27 | −0.10 … −0.25 | −0.34 … −0.37 | +0.16 … +0.33 |
  | z / max(generated, reference) | −0.07 … −0.17 | −0.03 … −0.11 | −0.21 … +0.29 | +0.15 … +0.19 |
  | F1 | −0.04 … −0.16 | −0.08 … −0.13 | −0.21 … +0.08 | +0.18 … +0.24 |
  | **z / reference (this amendment)** | −0.13 … −0.35 | −0.00 … +0.02 | +0.28 … +0.45 | +0.20 … +0.24 |

- New guard (`chain_b.sh`, after the reward of each round): steps per response, mean of the last two rounds, outside
  0.5–2 × the round-0 value stops the run. It covers the path this rule term opens (more, smaller steps) and the one
  the first run took; on the first run's log it fires at round 13. The other guards and the dev floor stay.
- New run from the same cold start (`grpo/runs/sr_sft3/merged`), name `sr_rl4`, same pool from its first question.

Known before the run (stage A3 model, held-out 300, 4 responses each, scored with this rule term):
- Rule among right responses 0.471; against the reference of another question of the same subset 0.065 (chance
  matches), rising with the number of steps from 0.040 (1–3 steps) to 0.097 (9 or more). Writing more steps can
  therefore buy a few hundredths by chance; the step guard bounds it.
- 255 of the 300 questions have all four responses right; the rule term differs inside 171 of them (mean spread
  0.256), so there is a signal among correct solutions.
- The highest- against the lowest-scoring right response of the same question (171 questions): length median −19
  characters (mean −383: very long solutions score lower), steps +0.80, "=" signs −1.4, share with a self-check
  word −5.8 points. The lean towards more steps is the expected one; the small leans against very long solutions
  and against self-check words are known and watched (length guard; checking expressions reported with the result).
- What a result can show: as in Amendment 4.

Launch: `COLD=sr_sft3 RUN_NAME=sr_rl4 STEPS=recall bash structreward/chain_b.sh` (unit `sr-b4`, log
`structreward/runs/chain_b4.out`), after diagnostic 3 has released the GPU.

## Amendment 6 (2026-11-15 22:17) — stage B with the rule term closed on both sides
Why: Amendment 5 closed the merging hole and opened the opposite one. Its run was stopped by the step guard, and on
MMMU the stopped adapter loops in ever more steps until the token limit (run log 21:51: 61.89, truncation 18.9 %,
the whole loss from added truncation). The user's decision stands ("보상의 허점은 막아야지"); this amendment applies
it to the second hole. Written after diagnostic 4 and before any rollout of the new run.

Changes against Amendment 5:
- Rule term (`sr.py reward RUN ROUND both`): matched results divided by the larger of the number of generated steps
  and the number of reference results. Fewer steps than the reference cannot raise the share (Amendment 5's
  property) and more steps cannot either (the paper's property). Everything else as in Amendment 5, including the
  step guard, the other guards and the dev floor.
- New run from the same cold start, name `sr_rl5`.

Checked before the run, on saved responses:
- Same question, right responses, far fewer steps than the reference (≤ N − 2) against about as many (within 1):
  −0.07 (cold start, held-out), −0.15 (run 1, merged rounds), −0.12 (run 2, split rounds). Far more steps (≥ N + 3)
  against about as many: −0.13, −0.10, −0.13. Both directions lose. (F1 was the other candidate: −0.03 / −0.09 on
  the cold start, too weak against merging.)
- The two drifts under this term: run 1 rounds 0–3 → 12–15 reward 0.553 → 0.523 (as trained 0.579 → 0.765); run 2
  rounds 0–3 → 18–21 0.554 → 0.573 (as trained 0.697 → 0.777). Neither would have been paid.
- Cold start, held-out 300: rule among right responses 0.312, against another question of the same subset 0.043;
  right minus wrong on the same question +0.150 [+0.100, +0.201]; 255 questions all right, the rule term differs
  inside 222 (mean spread 0.213); 61 % of right responses have more steps than the reference has results, 13 % as
  many, 26 % fewer.
- Known lean, not removed: the highest- against the lowest-scoring right response of a question is shorter (median
  −39 characters, mean −487), has 0.26 fewer steps, 2.7 fewer "=" signs and a self-check word 5.4 points less often.
  A step with no counterpart in the reference counts as a loss, which includes checking steps (the reason
  Amendment 5 avoided this form). Shorter solutions went with MMMU losses in earlier runs; the length guard, the
  step guard and the dev floor are the registered protections, and length, "=" and checking expressions are
  reported with the result.
- If a guard stops the run before round 24, the stopped adapter is evaluated as diagnostics 3 and 4 were
  (exploratory, MMMU dev seed 0 and the held-out 300).

Launch: `COLD=sr_sft3 RUN_NAME=sr_rl5 STEPS=both bash structreward/chain_b.sh` (unit `sr-b5`, log
`structreward/runs/chain_b5.out`).

## Amendment 7 (2026-11-16 03:45) — stage B with the audited defects fixed
Why: the user's decision ("이런 식으로 계속 해보고 결함들 더 찾아서 다음 학습 계획을 제대로 해보자") and the defect audit
(run log 2026-11-16 02:34). Three runs raised MMMU truncation over the cold start whatever the rule term; the audit
names what they had in common. Written after run 3 ended and after the probe check below, before any rollout.

Changes against Amendment 6 (rule term over the larger of the two counts, step guard: kept):
1. Responses cut at the token limit stay in training with reward 0 (`TRUNC=`; no `--drop-truncated`). In the
   plain-step reading a cut response has no valid format, so it earns nothing; a finished wrong answer earns the
   format term 0.10. This removes deviation D3's first part and is what the paper does.
2. The loss is averaged over the tokens of each response and then over the responses of the update
   (`grpo.py --per-response`, paper eq. 12), instead of one mean over all tokens. Without it a cut response of 8,192
   tokens would weigh about 37 times a typical one. Removes D3's second part.
3. Judgment examples (`sr.py aux RUN ROUND balanced`): pointwise examples only from questions with both outcomes,
   one right and one wrong response each; pairwise as before.
4. Reference results (`sr.py reward RUN ROUND both clean`, `clean_ref`): a result equal to the one before it is
   dropped, a literal \boxed wrapper is removed, formulas our result rule cut off are dropped (never the last one).
5. Probe guard (`PROBE=8`, `PROBE_MAX=8`): after rounds 7, 15, 23, ... the adapter answers 100 hard questions that
   are in no StructReward split (`structreward/data/probe_ids.txt`, numeric questions of `grpo/data/pool_v4.jsonl`,
   one response each, rollout sampling, 8,192 tokens). The run stops if the share of cut responses is more than
   8 points above the cold start's on the same questions (15 %).
New run from the same cold start, name `sr_rl6`. Everything else as before: 50 rounds × 20 questions × 8, reward
weights, KL coefficient, LR, the other guards, dev after rounds 24 and 49 with the floor 63.06 at round 24.

Probe check before registering it (one response per question, about 9 minutes per model):

| model | probe: cut | probe: right | MMMU truncation |
|---|---|---|---|
| cold start | 15 % | 47 % | 12.0 % |
| run 1, stopped at round 15 | 16 % | 40 % | 14.9 % |
| run 2, stopped at round 21 | 18 % | 45 % | 18.9 % |
| run 3, round 24 | 25 % | 36 % | 20.6 % |

The order of the four models is the same on the probe and on MMMU. The paired standard error of a difference to the
cold start is about 4 points, so the probe only tells a large rise: of the three, only run 3 (+10) is beyond noise
and would have been stopped by this rule (at round 23 at the latest); runs 1 and 2 (+1, +3) would not. A false stop
by noise alone has about 2.5 % chance per probe. The probe is an early warning for the size of defect run 3 had,
not a replacement for the dev evaluation.

Known before the run (run 3's saved rollouts scored with this amendment):
- 61 of 4,320 responses are cut (1.4 %); all get reward 0. Of 540 groups, 26 contain a cut response, 77 mix right
  and wrong, 405 are all right, 32 have no spread. The signal against never finishing is therefore small per
  round (about one group in twenty); whether it is enough is what the run tests.
- Reference results per question 3.77 → 3.00. Rule term among right responses 0.319 → 0.306; right minus wrong on
  the same question +0.142 → +0.129 [+0.095, +0.167] (the repeats had given right responses free matches).
- Judgment examples per round about 24 → 12 (e.g. round 5: 4 "Correct", 4 "Incorrect", 4 pairwise).
- Risk on the other side: with cut = 0 and a wrong finished answer = 0.10 the reward prefers finishing early over
  thinking long; v4 (cut = 0, one mean over all tokens, other reward) collapsed in length. Protections: the length
  guard (finished length below 0.6 × round 0), the step guard, the dev floor.
- Not fixed in this run: most groups are all right, so most of the signal is the process term (audit item 5); the
  rollout sampling differs from the evaluation's (item 7). A harder pool is the candidate for the run after this.
- What the run can show: probe truncation at rounds 7 / 15 / 23 against 15 %; MMMU truncation at round 24 against
  12.0 % (cold start) and 20.6 % (run 3); the dev score against 63.44 (cold start) and 65.16 (base mean).

Launch: `COLD=sr_sft3 RUN_NAME=sr_rl6 STEPS="both clean" TRUNC= NORM=--per-response AUX=balanced PROBE=8 PROBE_MAX=8
bash structreward/chain_b.sh` (unit `sr-b6`, log `structreward/runs/chain_b6.out`).

## Amendment 8 (2026-11-16 07:15) — stage B with a KL coefficient that can hold the policy
Why: diagnostic 5 (run log 07:14) and audit item 8. Run 4 fixed the audited reward defects and was still stopped
by the KL guard before its first checkpoint; its stopped adapter again cuts more MMMU responses than the cold start
(17.0 against 12.0 %) and solves fewer hard probe questions, and the probe shows that loss growing with the rounds
(right: −2 at round 7, −3 at round 15, −11 at round 19, while the KL max went 0.02 → 0.06 → 0.15). What the four
runs share is not a reward detail but how far the policy moves from the cold start on a pool it already solves.
The user's standing decision: keep going this way, find the defects, plan the next training properly.

One change against Amendment 7: the KL coefficient is 0.01 instead of the paper's 0.001 (`BETA=0.01`; the value of
our v5 and v6 runs, which stayed at KL ≤ 0.006 over 8 rounds and ≤ 0.041 over 30). Everything else as in Amendment
7: two-sided rule term on cleaned reference results, cut responses in training with reward 0, loss per response,
balanced judgment examples, probe guard after rounds 7, 15, 23, ..., step guard, the other guards, dev after rounds
24 and 49 with the floor 63.06 at round 24. New run from the same cold start, name `sr_rl7`.

Not changed on purpose (one cause at a time): the rule term. The term that ignores step marks (`sr.py` mode
`values`, run log 05:40) is ready and stays a candidate; so does a pool with hard questions.

What the run tests:
- Does the stronger anchor keep the KL max under 0.1 to round 24 (and 49)?
- Does the probe stay at the cold start's level (cut 15 %, right 47 %) at rounds 7, 15, 23 where run 4 fell?
- MMMU at round 24: truncation against 12.0 % (cold start) and 17.0–20.6 % (runs 2–4); score against 63.44 and 65.16.
Known risk: a policy held this close may also learn nothing; the pool reward and accuracy per round tell.
The two-sided term still pulls the step count towards the reference count (run 4: 5.0 → 2.7 in 20 rounds); with
slower movement the step guard's limit (2.5) is expected to hold to round 24, not guaranteed.

Launch: `COLD=sr_sft3 RUN_NAME=sr_rl7 STEPS="both clean" TRUNC= NORM=--per-response AUX=balanced PROBE=8 PROBE_MAX=8
BETA=0.01 bash structreward/chain_b.sh` (unit `sr-b7`, log `structreward/runs/chain_b7.out`).

## Amendment 9 (2026-11-16 14:19) — outcome reward on a hard pool, from the base model
Why: the user's decision after the five stage B runs ("1번이 맞을 듯": mix hard questions into the training, so that
there is something to learn about getting more answers right). On the StructReward pool the model is right 90 % of
the time: 16 % of the groups mix right and wrong answers, and four of five trained groups are trained on the
process term alone; all five runs ended at or below the cold start with more MMMU truncation. Written while
diagnostic 6 is still running; this design does not depend on its result (it will say whether the process term may
come back later).

What changes (script `structreward/chain_hard.sh`; pool `sr.py build_hard`):
- Pool `structreward/data/pool_hard.jsonl`, questions the *base* answers right only some of the time, none of them
  from MMMU (overlap re-checked: 0 hits), none of them probe or MC-check questions:
  - 440 multiple-choice questions (VWI, `grpo/data/pool_v7.jsonl`): at most 3 of 4 right in the base's first screen
    and 1–3 of 4 in its second (base on these: right 47.8 %, cut at the token limit 16.9 %);
  - 220 numeric questions of `grpo/data/pool_v4.jsonl` (base-like policies in v4/v5: right about 28–35 %, cut 17–30 %).
  Rounds of 12 questions = 8 multiple choice + 4 numeric, 8 responses each; 55 rounds available.
- Reward: 1 for a finished response whose answer line is right, else 0 (`sr.py reward RUN ROUND right`). No format
  term, no process term, no judgment tasks. A response cut at the token limit gets 0 and stays in its group.
- Start: the base model itself (no cold start: without a process term nothing needs the step format, and the cold
  start is 1.7 below the base). Run name `hard1`.
- Kept from Amendment 7/8: loss averaged per response, KL coefficient 0.01, LR 1e-4, 4 groups per update, LoRA as
  before, MMMU dev (seed 0) after rounds 24 and 49, floor 63.06 at round 24, 5 seeds only with the user's agreement.
- Guards, re-set for rounds of 12 hard questions and checked on the base's saved responses (400 random question
  orders, unchanged policy, 25 rounds): accuracy of the last 4 rounds below 0.5 × round 0 (false stop 0 %; the old
  0.7 gives 1.5 %); more than 50 % of a round cut (0 %; the old 35 % would stop an unchanged policy in 18.5 %);
  finished length relative to the base's length on the same question below 0.6 × round 0 (1.0 %); KL above 0.1.
  The step guard is dropped (the base rarely writes step marks and nothing rewards them).
- Probe guard after rounds 7, 15, 23, ...: the 100 probe questions (hard numeric, in no pool), one response each,
  against the base on the same questions (measured at the start of the run): stop if the share of cut responses is
  more than 8 points above the base's or the share of right answers more than 12 points below. Unlike in stage B the
  probe is now of the kind trained on, so it can also show a gain.

What is different from the earlier outcome runs on hard pools (v4–v6, no gain): v4 gave cut responses 0 but
averaged the loss over all tokens and paid for wrong quick answers (it collapsed in length); v5 and v6 left cut
responses out; v4/v5 had numeric questions only and v6 a pool the base solved 87 % of the time. Here: cut = 0 with a
per-response loss, and multiple-choice questions at the base's point of uncertainty.

Known before the run:
- Informative groups: the multiple-choice questions were selected on mixed outcomes, so with 8 fresh responses most
  groups should carry a signal (expected 6–7 of 8 a round); numeric about half. About 8 trained groups, 2 updates
  a round, 50 updates by round 24.
- A lucky multiple-choice answer is rewarded like a reasoned one (chance 25 %).
- Subject mix: the VWI multiple-choice pool is about half mathematics and geometry; the MMMU headroom is mostly in
  Business, Tech & Engineering and Music (v5 analysis). Transfer is the open question, as in every run so far.
- Time: a round takes about 17 minutes (long responses), so round 24 is about 7 hours after the start.
- What the run can show: probe (right, cut) against the base at rounds 7 / 15 / 23; MMMU dev at round 24 against
  the base mean 65.16 (one seed, detection limit 2.1) with truncation against 14.1 %; afterwards the held-out 300 and
  the MC check for forgetting on easy questions.

Added 15:31, before the run has started (user: "잘린 응답이 없도록 해야함. 응답이 잘리면 추론이 중간에서 끊기니까, 의미가
없음"): fewer cut responses is a registered aim of this run, not only a side measure.
- How the run acts on it: a cut response never earns the reward (it has no answer line), it stays in its group, and
  in every group with at least one right answer it is pushed down exactly like a wrong answer. It is not a training
  example to imitate. Rollouts keep the evaluation's limit of 8,192 tokens, because that is where the frozen
  evaluation cuts; a longer limit in training would hide the responses the evaluation will cut.
- Not done: a bonus for a finished wrong answer over a cut one. It would act in the groups without any right
  answer and pay for answering quickly whatever the answer (v4 collapsed in length with cut = 0 next to credit for
  wrong answers). It is the stronger setting if the user wants it.
- Measures: the share of cut responses on the probe at rounds 7 / 15 / 23 against the base, per round in the pool
  (about 17 % expected at the start), and on MMMU at round 24 against the base (14.1 % on seed 0).
- Acceptance: a checkpoint is put forward for the 5-seed evaluation only if its dev score is above the base mean
  **and** its MMMU truncation is not above the base's on the same seed (14.1 %).

Launch: `bash structreward/chain_hard.sh` (unit `sr-hard1`, log `structreward/runs/chain_hard1.out`), after
diagnostic 6 has released the GPU.

## Limits known before the run
- The paper's number is a single reported checkpoint under its own evaluation; our base is 65.16 ± 0.93 under the
  frozen pipeline, and one dev seed cannot tell differences below about 2.1 points.
- Learning rate, epochs, LoRA or full fine-tuning, loss weights and prompts are not in the paper; ours are above.
- The local-result rule is a heuristic: a step's "result" can be a quoted given value rather than a derived one.
- SFT targets are short (median 1,222 characters) next to the base's own MMMU solutions; a change of solution
  style is the risk our v9 run showed.

## Data as built (2026-11-14 17:41, `structreward/data/build_summary.json`)
- SFT 5,000 (multiple choice 3,297, numeric 1,703; 5.8 steps on average; target length p10 697 / median 1,222 /
  p90 2,092 characters). Per subset: ScienceQA 778, M3CoT 778, Geometry3K 778, MAVIS-Geometry 778, MAVIS-Function
  777, GeomVerse 578, Geo170K 429, AI2D 104, GEOS 0.
- RL pool 1,000 (multiple choice 709, numeric 291; 4.3 reference results on average); held-out 300.
- 60 items dropped for an MMMU image hit, none for a text hit.
- Every written target reads back through our parser and receives format = right = rule = 1 (asserted in `build`).

## Run log
- 2026-11-14 17:43: stage A launched (unit `sr-a`, RAM guard `sr-a-watch`, log `structreward/runs/chain_a.out`).
  First steps: 10.5 s per update, so the SFT takes about 1.8 h; the three checks follow.
- 2026-11-14 19:43: SFT finished (624 updates, loss 1.03 → 0.38, 2.0 h). 19:49: the first check (held-out, base model)
  died with a CUDA out-of-memory error at 30 %: two other GPU jobs of this machine (about 1 GB each) had started
  during the SFT, and vLLM held its usual 0.85 share. No result had been produced.
- 2026-11-14 19:52: relaunched with a GPU share of 0.75 for every vLLM step (`MEM` in `chain_a.sh`, `chain_b.sh`).
  The MMMU dev run therefore calls `run_eval.py --gpu-mem-util 0.75` instead of `eval.sh` (default 0.90); all other
  settings are the frozen ones. Before it, the base model is run on Music with seed 0 at the same share and its
  responses are compared with the official ones (`structreward/runs/check_mem.txt`), to show that the share does not
  change what the pipeline generates.
- 2026-11-14 20:43: **stage A results (as-published cold start).**
  - Gate 1, held-out 300: format valid 99.3 % (pass). Accuracy on these in-distribution questions 93.0 → 80.2,
    Δ −12.83 [−15.92, −9.83]. Finished length 2,494 → 1,246 characters; mean process reward 0.597 (rule 0.397).
  - MC check: 86.8 → 64.6, Δ −22.15 [−26.12, −18.25]; finished length 4,254 → 1,571 characters; checking
    expressions 0.90 → 0.05 per 1,000 characters.
  - Gate 2, MMMU dev (seed 0): **52.33**, Δ −12.82 [−15.67, −9.89] against the base mean; questions the base
    reliably solves −17.88 [−22.08, −13.91]; mean response 7,479 → 1,687 characters, truncation 14.1 → 0.3 %.
    **Fail (≤ 63.06): the as-published line stops at the cold start.** Stage B was not run on this model.
  - GPU share check: base seed 0 on Music at 0.75 gives the official responses 30/30.
  - Tooling: the held-out report crashed on numeric questions (`options` is null in the pool rows; fixed, a check
    added to `selfcheck`; the gate file was regenerated from the saved responses). `analyze.py compare` refused the
    0.75 run because of `gpu_mem_util` and the LoRA keys; both checks of `analyze.py` now share `settings()`, which
    leaves the GPU share out and reads missing LoRA keys as off; the comparison was then run by hand.
- 2026-11-14 20:45: stage A2 launched (unit `sr-a2`, RAM guard `sr-a2-watch`, log `structreward/runs/chain_a2.out`).
- 2026-11-14 20:52: stage A2 stopped by the RAM guard two minutes into the own-solution screen (available memory
  3 GB). Cause: `grpo.py sample_rows` handed all 5,000 questions to vLLM at once, so every image was decoded and
  preprocessed up front (earlier screens had at most about 1,300 questions). Fix: more than 1,500 questions are now
  sampled 500 at a time. No response had been written. Relaunched 20:53.
- 2026-11-15 00:10: **stage A2 stopped by its registered rule: 0 usable own solutions** (`runs/select_own.txt`).
  19,984 responses (2 + 2 samples per question), 19,771 finished, 18,576 correct (93.0 %, the same as the base
  without the instruction on the held-out questions), format valid 0. The base model follows only part of the
  instruction: a line-start "Step 1:" in 19,983 responses, `\boxed` in 470 (2.4 %), `<think>` in 0 and `</think>`
  in 15. No SFT, no check and no stage B were run.
- 2026-11-15 00:13: **diagnostic registered before its result** (no training, no rule changed; the next step stays
  the user's decision). Question: does the step format itself cost MMMU accuracy when the base model follows it by
  instruction? `structreward/diag_format_eval.py` runs the frozen pipeline (seed 0, 900 questions, GPU share 0.75)
  with the A2 format instruction before the CoT suffix → `runs/diag_base_format/seed0`. Reading: against the base
  mean 65.16 with the single-seed bar 63.06. At or below the bar: a cold start that teaches this format starts
  below the base whoever wrote the targets. Above the bar: the instruction is not shown to cost accuracy. Limit: a
  prompted model is not a fine-tuned one, and the base writes neither the tags nor the boxes, so this measures the
  numbered-step style only.
- 2026-11-15 00:14: analysis of the saved responses (no new run).
  - **Correction of the length comparison** used in Amendment 1 ("targets about half as long as the base's own
    solutions"): that set a median (targets, 1,222) against a mean (base, 2,494). Like for like, finished responses,
    characters as p10 / median / p90 / mean:
    base on the held-out questions 547 / 1,061 / 5,359 / 2,494; paper-style targets 697 / 1,222 / 2,091 / 1,321;
    stage A model 717 / 1,160 / 1,877 / 1,246; base with the format instruction (SFT questions) 408 / 773 / 2,006 /
    1,529. The typical target is not shorter than the base's typical solution. What the targets lack is the long
    tail: one base solution in ten is longer than 5,359 characters and no target is, and the stage A model lost
    exactly that tail.
  - The format instruction removes the same tail from the base's own solutions (p90 5,359 → 2,006).
  - Own solutions formatted by rule (the base's "Step n:" text, results boxed by `local_result`, tags added, 3–12
    steps): usable for 4,641 of the 5,000 questions; 464 / 827 / 1,643 / 1,235 characters, 4.6 steps. Not a
    registered procedure; using it would be Amendment 2 and is the user's decision.
- 2026-11-15 01:41: **diagnostic result: base with the format instruction, MMMU dev seed 0 = 64.67**
  (`runs/diag_base_format/`, 84.5 min), Δ −0.49 [−2.84, +1.96] against the base mean; the base's own seed 0 is also
  64.67. **Above the bar 63.06: the numbered-step style is not shown to cost accuracy.**
  - The model follows the step style in 900/900 responses (294/900 without the instruction), `\boxed` in 17,
    `<think>` in 0.
  - It keeps its long solutions on MMMU: 126 truncated (base 127; 91 the same questions). Finished responses are
    shorter, p10 / median / p90 / mean 714 / 1,342 / 7,244 / 2,779 characters against 1,059 / 2,194 / 13,003 / 4,663.
  - Questions the base reliably solves: −2.87 [−5.52, −0.22] (wrong in the paired seed 35 against the base's 22).
  - Reading: the stage A loss (−12.82) does not come from writing numbered steps. What is left as the cause is the
    training targets themselves (another model's solutions, none of them long).
  - Analysis after the result, saved responses only: picking the longest usable own solution per question, with no
    upper limit on steps, gives 4,648 targets of 554 / 992 / 3,844 / 1,950 characters (one at random: 472 / 854 /
    1,911 / 1,439). No run was started; Amendment 2 waits for the user's decision.
- 2026-11-15 02:24: **second diagnostic registered before its result** (no training, no rule changed). Question:
  did the stage A SFT damage what the model knows and sees, or how it reasons at length? The base and the stage A
  model (`grpo/runs/sr_sft/merged`) are run on MMMU dev, seed 0, with the pipeline's official direct-answer prompt
  (`run_eval.py --prompt-style mmmu`, GPU share 0.75) → `runs/diag_direct/{base,sr_sft}/seed0`. Reading: paired
  difference with a bootstrap interval. Close to zero: knowledge and perception are intact and the −12.82 under
  the CoT pipeline is a loss in the reasoning itself. Clearly negative as well: the SFT damaged the model more
  broadly. Limits: one seed each; the stage A model may still write its reasoning block under this prompt (the
  share is reported); these runs use another prompt and are never compared with the CoT scores as a result.
- 2026-11-15 02:26: analysis of the stage A model's saved MMMU responses (`runs/sr_sft_full/seed0`, no new run).
  **The loss is not a loss of long solutions** (this corrects the cause given in the 00:14 and 01:41 entries).
  - By how long the base writes on the question (quarters of the 900, base 5-seed mean → stage A): shortest
    89.2 → 78.7, second 68.5 → 55.6, third 58.3 → 44.4, longest 44.5 → 30.7. The drop is 10 to 14 points in every
    quarter; in the shortest quarter both models write about 1,220 characters.
  - By subject: largest drops Finance −40.0, Physics −30.7, Architecture and Engineering −29.3, Accounting −28.0,
    Math −26.0, Computer Science −23.3; near zero for Literature, Design, Sociology, Diagnostics. Open questions
    39.2 → 17.0, multiple choice 66.8 → 54.5.
  - In the calculation subjects the responses hold 13.2 "=" signs against the base's 75.9 and 131 digits against
    663; self-check words 0.19 against 0.91 per 1,000 characters.
  - In distribution (held-out, base → stage A): Geometry3K 84.1 → 62.9, GEOS 87.1 → 59.1, MAVIS-Function
    99.2 → 79.5, Geo170K 97.7 → 80.3, ScienceQA 92.6 → 89.0, MAVIS-Geometry 99.2 → 97.0.
  - Examples among the 95 questions the base solves in 5/5 seeds and stage A misses: an arithmetic slip
    (1.15^3 written as 1.4238), a formula applied against the stated condition, boxes holding a formula or a stray
    number (`\boxed{4}`), a step boundary in the middle of a sentence.
  - Reading: the SFT replaced the base's way of working a problem (writing the calculation out, checking) with the
    targets' way: another model's terse steps, cut and boxed by our rule. Which of the three (source solutions, our
    step and box rule, SFT strength) carries the damage is not separated.
- 2026-11-15 02:29: the stage A training targets measured after the fact (`grpo/runs/sr_sft/rft_train.jsonl`). All
  of this could have been measured before the SFT; only format validity was checked then (parser round trip,
  reward = 1).
  - Against the base's own finished solutions on held-out questions of the same sources: "=" per solution 11.0
    against 17.1; a self-check word in 6.8 % of the targets against 35.8 % (0.05 against 0.53 per 1,000 characters).
  - Boxes (28,925): the first box of a target repeats a value that already stands in the question text in 34.4 % of
    the targets (rough: a derived value can coincide with a given one); 3.7 % of the boxes hold symbols or words only.
  - Lesson for any later SFT in this line: compare the targets with the base's own solutions on the same questions
    (calculation written out, self-checks, what the boxes hold) before training, and box derived values only.
- 2026-11-15 02:57: Amendment 2 targets built: 4,426 questions. Gate 0 on the registered measures: pass ("=" per
  solution 18.5 against the base's own 18.2 and the stage A targets' 11.7; a self-check word in 31.4 % against
  35.6 % and 7.0 %; boxes restating a given number 0 % against 13.1 % in stage A).
- 2026-11-15 03:00: sample of six targets read. The text is the base's own and reads well; the boxes added by rule
  are wrong in about half of the six: `\boxed{2}` taken out of "21 / √2", `\boxed{B}` on steps that conclude A,
  `\boxed{no}` from the word "no", a last box 3 under the answer 18. Measured on all 4,426: the last box agrees
  with the answer line in 68.1 % (M3CoT 43.0 %, ScienceQA 54.0 %); the stage A targets, same measure, 66.1 %.
  **Not launched with these targets** (Amendment 3).
- 2026-11-15 03:01: Amendment 3 targets built (`runs/select_own3.txt`, `runs/check_targets3.txt`): 4,835 questions,
  5.3 steps, 491 / 919 / 3,554 characters (p10 / median / p90; base own 547 / 1,061 / 5,387), no tag and no box in
  any target, training prompt without the format instruction. **Gate 0: pass** ("=" per solution 18.0 against the
  base's own 17.6 and the stage A targets' 11.2, midpoint 14.4; self-check word in 31.1 % against 35.2 % and 6.8 %,
  midpoint 21.0 %). Stage A3 queued as unit `sr-a3` (RAM guard `sr-a3-watch`, log `structreward/runs/chain_a3.out`);
  it starts when the GPU is free.
- 2026-11-15 03:02: the second diagnostic (02:24) is cut short to free the GPU: it is stopped after its base run;
  the stage A model's run under the direct-answer prompt is not done (the failure analysis of 02:26 already shows
  where the loss sits). The base under that prompt writes about 900 tokens per response, so it is not an
  answer-only run either.
- 2026-11-15 03:26: the base run of the second diagnostic finished and the unit was stopped: base, seed 0, official
  direct-answer prompt = 61.00 (`runs/diag_direct/base/seed0`; 87 responses cut at the token limit, 59.7 min). Not
  comparable with the CoT scores; kept as a reference only. Stage A3 started (targets and gate 0 re-run inside the
  chain, then the SFT).
- 2026-11-15 07:23: **stage A3 results (own solutions as written): both gates passed.**
  - Gate 1, held-out 300: numbered-step format 97.3 % (base without the instruction 12.3 %), pass. Accuracy
    93.0 → 92.3, Δ −0.67 [−2.33, +1.00]; finished length 2,494 → 1,484 characters.
  - MC check: 86.8 → 86.1, Δ −0.69 [−3.11, +1.64]; finished length 4,254 → 2,945 characters; checking expressions
    0.90 → 0.74 per 1,000 characters; truncation 3.9 → 2.0 %.
  - Gate 2, MMMU dev (seed 0): **63.44**, Δ −1.71 [−3.91, +0.49] against the base mean; questions the base reliably
    solves −0.88 [−3.53, +1.77]; truncation 14.1 → 12.0 %, mean response 7,479 → 5,367 characters. **Pass (> 63.06),
    by 0.38.** Not a gain: the interval includes zero and the point estimate is below the base and below the
    prompted reference (64.67).
  - Against stage A (another model's solutions, boxes by rule): MMMU 52.33 → 63.44, held-out 80.2 → 92.3, MC check
    64.6 → 86.1.
- 2026-11-15 07:26: analysis for stage B, saved responses only. Can step results be read by rule from plain numbered
  steps (`numbered` + `local_result`, reference results filtered by `load_pool`)?
  - Base with the instruction on the SFT questions (19,262 responses read): 10.4 % of the steps have no readable
    result; the last result agrees with a correct answer in 73.8 %. Stage A3 model on held-out (1,168): 15.8 % and
    78.8 %.
  - The process score separates right from wrong solutions of the same question: correct minus incorrect +0.165
    [+0.142, +0.188] (441 questions; mean 0.390 against 0.198); stage A3 model on held-out +0.169 [+0.108, +0.233]
    (32 questions). With the last step and the last reference result left out (intermediate results only): +0.099
    [+0.075, +0.122] (416 questions). Strong in the geometry and function subsets, close to zero in AI2D and
    MAVIS-Geometry, small in M3CoT and ScienceQA.
  - Reading: noisy but informative. Whether a higher process score among correct solutions marks better reasoning
    is not testable offline. Stage B is not started; it waits for the user's decision (Amendment 3).

- 2026-11-15 15:18: user's go ("진행해 보자 그럼") → Amendment 4 written, `sr.py selfcheck` passes with the plain-step
  reading, stage B started on the stage A3 model: unit `sr-b3` (`COLD=sr_sft3 RUN_NAME=sr_rl3 STEPS=steps`,
  `structreward/chain_b.sh`, log `structreward/runs/chain_b3.out`), RAM guard `sr-b3-watch`. `chain_b.sh` runs end to
  end for the first time here; round 0 is checked before the run is left alone.
- 2026-11-15 15:25: stage B round 0 ran end to end (rollout, reward, judgment/choice examples, training, guard) in
  6.6 minutes. Round 0 (20 questions × 8): format 98.1 %, right 89.4 %, rule 0.334, consistency 0.656, 5.0 steps,
  reward 0.592; truncated 0; mean 490 tokens (median 245); 20 groups, 5 updates, KL max 0.003; judgment/choice
  examples 20 pointwise (18 Correct, 2 Incorrect) and 3 pairwise; guard passes. Note on the length guard: the
  reference lengths in `pool_rl_len.jsonl` are characters while response lengths are tokens (ratio 0.237 at round
  0); the guard only compares that ratio with its own round-0 value, so the unit does not enter the rule.
- 2026-11-15 16:38: **stage B stopped by the registered KL guard after round 15** (KL max 0.151 > 0.1; rounds 0–15,
  2,560 responses). No checkpoint of the plan (rounds 24, 49) was reached, so no registered dev evaluation exists.
  - What changed over the rounds (finished responses; each round has other questions): steps per response 5.0 → 1.8
    (median 5 → 2; one-step responses 1 % → 49 %), rule among right responses 0.365 → 0.691, reward 0.592 → 0.866,
    right 0.894 → 0.919 (no trend: 0.84–1.00 over the rounds), median tokens 244 → 142, length ratio 0.237 → 0.178
    (0.75 × round 0; the length guard at 0.6 × did not fire), KL max per round 0.003 → 0.151.
  - Cause, from reading round 15: the model writes the whole solution as one "Step 1:" paragraph that ends with the
    final value. The rule term is the share of *generated* steps that match (paper eq. 7, 1/M over generated steps),
    so one step whose result is the last reference result scores 1/1 and the full reward 1.21; among right
    responses of the same question a one-step response earns +0.294 more than a multi-step one (13 questions, 85 %
    positive). The reward was raised by merging steps, not by solving more questions. Amendment 4 named the lean
    towards shorter solutions (−0.15) but not this path; the paper's format rule has no minimum step count either.
  - Not done: no restart, no change of the reward or of the guard. Both need the user's decision.
- 2026-11-15 16:40: diagnostic 3 registered before its result: MMMU dev (900 questions, seed 0, frozen pipeline) of
  the adapter as it stood when the guard stopped the run (after round 15; `grpo/runs/sr_rl3/merged_r015` →
  `runs/sr_rl3_r015_full/seed0`, unit `sr-b3-dev`). Exploratory: not a checkpoint of the plan and not a gate; it
  shows what the step merging does to MMMU against the cold start on the same seed (63.44) and the base mean
  (65.16). One seed cannot support a gain claim.
- 2026-11-15 17:31: user's decision ("보상의 허점은 막아야지") → Amendment 5 written (rule term over the reference
  results; step guard), `sr.py selfcheck` passes (a one-step solution: rule 1.0 under the paper's term, 0.5 under the
  new one), the step guard run on the first run's log stops it. Unit `sr-b4` queued behind diagnostic 3.
- 2026-11-15 18:08: **diagnostic 3 result** (exploratory; adapter of the first stage B run as stopped after round
  15): MMMU dev seed 0 = **64.00**, Δ −1.16 [−3.36, +1.22] against the base mean; against the cold start on the same
  seed (63.44) +0.56 [−2.00, +3.22] (77 questions gained, 72 lost). Truncation 14.9 % (cold start 12.0 %, base
  14.1 %), mean response 5,874 characters (cold start 5,367). The step merging carried over to MMMU: steps per
  response 5.41 → 1.87, one-step responses 2.7 % → 57.2 %, median length 1,490 → 1,152 characters. Reading: writing
  the solution as one paragraph instead of numbered steps neither helped nor hurt within what one seed can tell;
  the score is below the base mean and not a gain. Unit `sr-b4` (Amendment 5) started when this evaluation ended.
- 2026-11-15 20:06: **second stage B run (Amendment 5) stopped by the step guard after the reward of round 21**
  (steps per response, mean of rounds 20–21, 10.9 > 2 × 5.03). 21 rounds were trained (0–20); the checkpoint of the
  plan (round 24) was not reached, so no registered dev evaluation exists. Over the rounds: steps per response
  5.0 → 10.9, rule 0.44 → 0.52–0.63, reward 0.69 → 0.78–0.84, KL max 0.003 → 0.075, median tokens 244 → 217–240
  (no collapse), truncation ≤ 5.6 %; right 0.89 → 0.92–0.99 in the last rounds (other questions each round; no
  comparison with the cold start on the same questions yet).
- 2026-11-15 20:07: diagnostic 4 registered before its result: MMMU dev (900 questions, seed 0, frozen pipeline) of
  the adapter as it stood when the step guard stopped the run (after the training of round 20;
  `grpo/runs/sr_rl4/merged_r020` → `runs/sr_rl4_r020_full/seed0`, unit `sr-b4-dev`). Exploratory, as diagnostic 3:
  not a checkpoint of the plan, not a gate, and one seed cannot support a gain claim. Compared with the base mean
  (65.16), the cold start (63.44) and diagnostic 3 (64.00) on the same seed.
- 2026-11-15 20:08: reading of the second run's rollouts (saved responses). The step count rose mostly in a tail:
  median 5 → 6–7, 90th percentile 7 → 12–13, responses with more than 10 steps 3 % → 14 % (the guard reads the mean,
  10.9 in rounds 20–21); characters per step 130 → 84. The added steps are finer steps of the same derivation (one
  algebraic move per step), plus a few very long wandering solutions (up to 38 steps); not filler. Rule among right
  responses 0.494 → 0.556; against the reference of another question of the same subset 0.076 → 0.097; so about
  +0.04 of the rise is above chance and +0.02 is chance matching from the larger number of steps. Right on the
  questions both runs saw (rounds 0–15): run 1 0.912 / 0.915, run 2 0.910 / 0.913 (first / second half), no
  difference; rounds 16–21 of run 2 0.95–0.97, on questions with no comparison.
  Added to diagnostic 4 before any of its results: the held-out 300 (4 samples, seed 0, as gate 1) for the stopped
  adapters of both runs, paired against the cold start on the same questions (92.3 %), unit `sr-b4-held` after the
  MMMU evaluation. It tells whether either run solves more unseen questions of the training kind.
- 2026-11-15 21:51: **diagnostic 4, MMMU part** (exploratory; adapter of the second stage B run as stopped, after the
  training of round 20): MMMU dev seed 0 = **61.89**, Δ −3.27 [−5.49, −1.07] against the base mean (below the base);
  against the cold start on the same seed (63.44) −1.56 [−4.11, +1.11] (64 gained, 78 lost); against the stopped
  adapter of run 1 (64.00) −2.11 [−4.89, +0.78]. Truncation 18.9 % (cold start 12.0 %, base 14.1 %); steps per
  response mean 17.2, median 7 (cold start 5.4 / 5); checking expressions 1.51 per 1,000 characters (cold start 1.21).
  - Where the difference to the cold start comes from: questions finished by both models (718) 69.1 → 69.4 (+0.22
    of the difference); questions cut at the token limit only by run 2 (74) 62.2 → 27.0 (−2.89); cut only by the
    cold start (12) +0.44; cut by both (96) +0.67. The whole loss is the added truncation.
  - What the cut responses are: step loops. Cut responses of run 2 have 52 steps on average (cold start 6.4), up to
    348, repeating the same few statements as new steps. The rule term over the reference results pays for more
    steps; on hard MMMU questions that became repetition until the token limit.
  - Reading: closing the merging hole by dividing by the reference results opened the opposite one. Where the model
    finishes, neither reward changed MMMU accuracy against the cold start (run 2: 69.1 → 69.4 on 718 questions).
- 2026-11-15 22:14: **diagnostic 4, held-out part** (300 unseen questions of the training kind, 4 samples, seed 0;
  stopped adapters of both runs against the cold start on the same questions): cold start 92.3 %; run 1 (paper's
  rule term, merged steps) 89.9 %, Δ −2.42 [−4.00, −0.92]; run 2 (Amendment 5, split steps) 92.1 %, Δ −0.25 [−1.92,
  +1.33]; run 2 minus run 1 +2.17 [+0.50, +3.83]. Steps per response 4.9 / 1.5 / 10.1, median length 761 / 507 /
  728 characters, truncation 1.2 / 1.6 / 1.3 %. By the cold start's own result: questions it solves 0–2 times of 4
  (24) 26.0 → 26.0 (run 1) / 41.7 (run 2); 3 of 4 (21) 75.0 → 72.6 / 73.8; 4 of 4 (255) 100 → 97.4 / 98.3 (groups
  picked on the cold start's result, so part of each shift is regression to the mean). MMMU, questions finished by
  both the cold start and the run: run 1 69.6 → 71.0 (739), run 2 69.1 → 69.4 (718).
  Reading: neither run solves more unseen questions of its own training kind than the cold start; run 1 solves
  fewer.
- 2026-11-15 22:17: Amendment 6 written (rule term over the larger of the two counts), `sr.py selfcheck` passes (the
  same solution in 1 / 3 / 5 steps against 2 reference results: 0.5 / 0.67 / 0.4). Unit `sr-b5` started.
- 2026-11-16 02:22: **third stage B run (Amendment 6), round 24: no guard fired; dev r024 = 63.67**, Δ −1.49 [−3.84,
  +0.87] against the base mean; above the floor (63.06), so the run goes on to round 49 as registered. Against the
  cold start on the same seed +0.22 [−2.44, +3.00] (75 gained, 73 lost). Not a gain.
  - Rounds 0 → 24 on the pool: reward 0.571 → 0.55–0.63 (no step-count route: steps 5.0 → 3.5–4.6, median 5 → 4),
    rule 0.306 → 0.28–0.39, right 0.89 → 0.88–0.98 (the same questions gave run 2 the same values in rounds 16–21),
    truncation ≤ 4.4 %, KL max ≤ 0.058, length ratio 0.237 → 0.246.
  - MMMU: truncation **20.6 %** (cold start 12.0 %, base 14.1 %; run 1 14.9 %, run 2 18.9 %). Split against the cold
    start: finished by both (697) 69.4 → 71.4 (+1.56 of the difference); cut only by run 3 (95) 61.1 → 32.6
    (−3.00); cut only by the cold start (18) 16.7 → 61.1 (+0.89); cut by both (90) 28.9 → 36.7 (+0.78). The groups
    are picked on each model's own outcome, so the parts are a description, not separate effects; the unbiased
    figure is the total, +0.22.
  - The cut responses of run 3 are not step loops (cut responses have 4.5 steps on average) but repetition inside a
    step (38 % of them repeat more than half of their last lines; cold start 22 %), e.g. a sentence that flips
    between two options until the token limit. Most frequent subjects: Music 12, Materials 9, Energy and Power 7.
  - All three GRPO runs raised MMMU truncation over the cold start, whatever the rule term. Common to the three:
    responses cut at the token limit are left out of training (deviation D3), so nothing in the reward acts
    against running to the limit, and the pool shows almost no truncation (≤ 5.6 % per round) to learn from.
    Candidate cause, not tested.
- 2026-11-16 02:34: **defect audit** (user: "이런 식으로 계속 해보고 결함들 더 찾아서 다음 학습 계획을 제대로 해보자"), saved
  rollouts and predictions only, while run 3 goes on. Found:
  1. *Cut responses are outside the reward.* `--drop-truncated` (deviation D3) leaves a response cut at the token
     limit out of the loss and out of the group baseline. A finished wrong answer is pushed down, never finishing is
     not. All three stage B runs raised MMMU truncation over the cold start (12.0 → 14.9 / 18.9 / 20.6 %) whatever
     the rule term, and run 3's cut responses flip between options without committing. The earlier runs fit: v5
     (dropped) 14.1 → 16.0 %; v2 and v4 (cut = 0 reward) truncation fell. Candidate cause, to be tested by the next
     run. The pool itself shows almost nothing of this: 1.4 % of run 3's rollouts are cut (61 of 4,320).
  2. *A long response weighs by its length.* The loss is one mean over all tokens of an update (D3); the paper
     averages per response first. With cut responses back in, an 8,192-token response would otherwise outweigh a
     typical one (median 220 tokens) about 37 times.
  3. *Judgment examples are one-sided.* 479 of 520 pointwise examples of run 3 have the target "Correct" (92 %),
     and these examples take 3.2 of 8.2 optimizer updates per round.
  4. *Reference results repeat.* 19.3 % of the reference results equal the one before them (54 % of the questions
     have such a repeat), and a matched reference result cannot be reused, so stating a value twice is paid.
     1.3 % are formulas our result rule cut off ("2.5 \\times"), some carry a literal \\boxed wrapper.
  5. *Most of the signal is the process term among correct solutions.* Run 3: 78 % of the groups are all right
     (71 % of the trained tokens), 16 % mix right and wrong. Right responses score 0.32 on the rule term on average
     and 0.6 % get full marks: the term measures overlap with another model's path. It still separates right from
     wrong on the same question (+0.142 [+0.106, +0.181]); in all-right groups the top response has more matches
     than the bottom one in 80 %.
  6. *Nothing during training looks at hard questions.* Every guard reads the pool, where the model is 90 % right.
  7. *Rollouts and the evaluation sample differently* (rollouts: temperature 1.0, no top-k, no presence penalty;
     evaluation: 0.7 / top-p 0.8 / top-k 20 / presence 1.5). Needed for the policy-gradient ratio; a known limit.
  Checked and not worth changing: reading fixes for "≈", fractions, π, trailing words and label numbers ("Pair 2")
  move the consistency term's false zeros among right responses only from 31.3 to 28.8 % and leave the right-wrong
  separation unchanged (+0.142 → +0.139); evaluating products in reference results changes nothing measurable.
  Logprob mismatch between rollout and training (0.015 per token), clipping (1 %), gradient norm (0.12): normal.
- 2026-11-16 03:07: **third stage B run stopped by the KL guard after round 33** (KL max 0.156 > 0.1); the round-49
  checkpoint was not reached. Rounds 25–33 on the pool: reward 0.55–0.74, steps 4.3 → 3.3 (inside the step guard),
  right 0.86–1.00, truncation up to 12.5 % in round 31, KL max 0.043 → 0.156. The only registered evaluation of this
  run is round 24 (63.67). Unit `sr-probe` (queued behind it) started the probe runs for the next amendment.
- 2026-11-16 03:45: probe check done (table in Amendment 7); Amendment 7 written; `sr.py selfcheck` passes; `chain_b.sh`
  got the switches `TRUNC`, `NORM`, `AUX`, `PROBE`, `PROBE_MAX` (defaults = the earlier behaviour). Unit `sr-b6` started.
- 2026-11-16 03:45: from the probe check, not a registered measure: the three runs also solve fewer of the hard probe
  questions than the cold start. Right: cold start 47 %, run 1 40 % (−7.0, paired SE 5.4), run 2 45 % (−2.0, SE 5.7),
  run 3 round 24 36 % (−11.0, SE 5.3); on questions finished by both models 57.5 → 47.5 (run 1, 80 questions),
  58.7 → 54.7 (run 2, 75), 57.7 → 46.5 (run 3, 71). One response per question, so each difference alone is within
  about 2 SE; the direction is the same in all three. The probe's share of right answers is reported for run 4.
- 2026-11-16 03:52: run 4 (`sr_rl6`), rounds 0–1 ran end to end with the new settings: balanced judgment examples (3 + 3
  pointwise and 3 pairwise; 4 + 4 and 4), cleaned reference results (rule 0.282 / 0.259), loss per response, both
  guards pass. No cut response in these two rounds yet. KL max 0.002 / 0.019 (run 3 at round 1: 0.006): the
  per-response mean moves the policy faster on short responses; the KL guard (0.1) is unchanged.
- 2026-11-16 05:34: **run 4 (Amendment 7) stopped by the KL guard after round 19** (KL max 0.154 > 0.1; 20 rounds
  trained). The round-24 checkpoint was not reached.
  - Probe guard: round 7 cut 21 % (cold start 15 %), right 45 % (47 %); round 15 cut 15 %, right 44 %. No stop; at
    round 15 the share of cut responses is the cold start's (run 3 at round 24: 25 %).
  - Pool, rounds 0 → 19: reward 0.550 → 0.52–0.63, rule 0.28 → 0.24–0.35, right 0.85–0.99 without trend, cut
    responses 0–8 per round (now trained on), steps per response 5.0 → 2.7 (the step guard's limit is 2.5),
    median tokens 244 → 156–226, length ratio 0.237 → 0.192, KL max 0.002 → 0.154 (run 3 at round 19: 0.058).
  - Reading so far: the KL grows faster than in run 3 (loss per response: short responses weigh as much as long
    ones), and the step count falls further (the cleaned reference lists are shorter, 3.0 results per question, and
    the two-sided rule term pulls the step count towards that number).
- 2026-11-16 05:35: diagnostic 5 registered before its results (exploratory, as diagnostics 3 and 4): the adapter of
  run 4 as stopped (after the training of round 19) on MMMU dev seed 0 (`grpo/runs/sr_rl6/merged_r019` →
  `runs/sr_rl6_r019_full/seed0`) and on the probe (`structreward/runs/probe_rl6_r019.jsonl`), unit `sr-b6-dev`.
  The question it answers: with cut responses in the reward, does MMMU truncation stay at the cold start's level
  (12.0 %) instead of rising (14.9 / 18.9 / 20.6 % in runs 1–3)?
- 2026-11-16 05:40: **defect audit, part 2** (saved rollouts; diagnostic 5 still running, its result not known):
  8. *The KL coefficient cannot hold the policy inside the KL stop limit.* With the paper's 1e-3 the KL max per round
     passed 0.1 in three of four runs before the planned checkpoints (run 1 round 15, run 3 round 33, run 4 round 19;
     run 2 was at 0.075 when the step guard stopped it at round 21). v5 and v6 used 1e-2 and stayed at ≤ 0.006
     (8 rounds) and ≤ 0.041 (30 rounds); other pools, so only an indication. In run 4 the updates on short
     responses carry the higher KL (0.052 against 0.021 for updates with a mean response of 300 tokens or more).
  9. *Keeping cut responses gave little signal on this pool.* Run 4: 16 of 400 groups contain a cut response (3.3 of
     8 on average, the same loop-prone questions as in run 3); cut responses in rounds 0–19: run 3 47, run 4 53.
     Whether it changed the MMMU behaviour is what diagnostic 5 measures.
  10. *The two-sided rule term pulls the step count to the number of reference results* (3.0 after cleaning): run 4
     went 5.0 → 2.7 steps, close to the step guard's limit of 2.5. Any rule term that counts steps pays for some
     way of placing the step marks (merge: run 1, split: run 2, towards the reference count: runs 3–4).
  Candidate that does not look at step marks at all (`sr.py all_values`, `in_order`; reward mode `values`): every
  value the body states (a number after an equals sign, option mentions, yes/no), in order; share of the cleaned
  reference results found in that order. Measured on saved responses, against the two-sided term:
  - cold start, held-out: right minus wrong on the same question +0.237 [+0.110, +0.367] (two-sided +0.131 [+0.082,
    +0.182]); among right responses 0.46, full marks 22 %, zero 25 % (two-sided 0.28, full marks 0 %); against
    another question's reference 0.101 (two-sided 0.038);
  - the same solution written in 1, 3 or 5 steps scores the same by construction (selfcheck);
  - what it pays for instead: stating more values. Within a question, among right responses, corr(values read,
    score) +0.48 … +0.64; the best-scoring response has about 8 more values than the worst, is 38 characters longer
    (median) and has a self-check word as often (−0.02 … +0.12); corr(length) +0.08 … +0.19;
  - 2 of 3 all-right questions get the same score for all responses (85 of 259 have a spread), so fewer groups are
    trained on the process term alone: on run 4's rollouts 194 process-only groups, 55 right-and-wrong, 16 with a
    cut response, 135 without spread (two-sided: about 300 / 60 / 16 / 25).
  A guard on the values read per response needs a 4-round window: under an unchanged policy a 2-round mean against
  round 0 leaves 0.5–2 × in 11.5 % of random question orders (the number of values depends on the questions drawn);
  the last 4 rounds over the first 4 never do in 500 orders (range 0.59–1.76). `chain_b.sh` has it in that form.
- 2026-11-16 07:14: **diagnostic 5** (exploratory; run 4's adapter as stopped after round 19): MMMU dev seed 0 =
  **62.89**, Δ −2.27 [−4.64, +0.04] against the base mean; against the cold start on the same seed −0.56 [−3.11,
  +2.11] (73 gained, 78 lost). Truncation **17.0 %** (cold start 12.0 %; runs 1–3: 14.9 / 18.9 / 20.6 %). Split
  against the cold start: finished by both (722) 70.1 → 69.9 (−0.11); cut only by run 4 (70) 51.4 → 31.4 (−1.56);
  cut only by the cold start (25) +0.78; cut by both (83) +0.33. Finished responses: median 1,184 characters (cold
  start 1,378), 3 steps (5), checking expressions 1.22 per 1,000 characters (1.06).
  Probe at the stop: cut 18 % (cold start 15 %), right 36 % (47 %); over the run, right minus cold start −2.0 (SE
  5.7) at round 7, −3.0 (5.2) at round 15, −11.0 (5.5) at round 19; on questions finished by both 56.8 → 55.4,
  58.2 → 50.6, 56.0 → 44.0.
  Reading: keeping cut responses in the reward did not stop the rise of MMMU truncation (item 1 of the audit is not
  confirmed as the main cause; on this pool it reaches 16 of 400 groups). All four runs, with four different rule
  terms and two ways of treating cut responses, end with more truncation on MMMU and fewer hard probe questions
  solved; the loss on the probe grows with the rounds, as the KL does.
- 2026-11-16 07:15: Amendment 8 written (KL coefficient 0.01, nothing else); `sr.py selfcheck` passes. Unit `sr-b7` started.
- 2026-11-16 11:18: **run 5 (Amendment 8, KL coefficient 0.01): round 24 reached, dev r024 = 62.00**, Δ −3.16 [−5.56,
  −0.84] against the base mean (below the base). **Dev floor (≤ 63.06): the run stopped as registered.**
  - The larger coefficient did not hold the policy: KL max per round 0.03–0.07 from round 6 on and 0.10 at round
    19, about the path of run 4 (it stayed just under the stop limit).
  - Probe: round 7 cut 12 % / right 42 %; round 15 cut 21 % / right 41 %; round 23 cut 23 % / right 34 % (cold start
    15 % / 47 %; the probe guard's limit is more than 23 %). On questions finished by both 56.8 → 49.4, 56.6 → 52.6,
    54.2 → 45.8.
  - MMMU truncation 20.8 % (cold start 12.0 %), mean response 7,206 characters.
  - Pool, rounds 0 → 24: reward 0.550 → 0.53–0.67, rule 0.28 → 0.25–0.39, right 0.83–1.00 without trend, steps
    5.0 → 3.0, cut responses 0–13 per round.
  Five stage B runs now end the same way: MMMU 61.9–64.0 (cold start 63.44, base 65.16), MMMU truncation
  14.9–20.8 % (cold start 12.0 %), hard probe right 34–45 % (cold start 47 %).
- 2026-11-16 11:21: from the saved rollouts, before the next step: the mean negative log-probability of the sampled
  tokens per round shows no trend in any run (0.2–0.5, set by the questions drawn), so the saved data neither show
  nor exclude a sharper policy. What the five runs have in common besides the pool and the cold start: about four
  of five trained groups are all-right groups, trained only on the process term (run 5: 19.4 groups, 5 GRPO updates
  and 1.7 judgment updates per round). With the outcome alone, run 5's rollouts would have trained 86 groups in 25
  rounds (65 with right and wrong, 21 with a cut response), 3.4 per round.
- 2026-11-16 11:21: **diagnostic 6 registered before any result: stage B without the process term and without the
  judgment tasks** (`STEPS="right clean"`: reward = 1 for a right finished answer, else 0; `AUX=none`). Purpose: to
  find out whether the updates that the process term and the judgment tasks add are what costs the hard questions
  (probe) and raises MMMU truncation, or whether the outcome updates alone do it too. 40 questions a round
  (`QUESTIONS=40`, the whole pool in 25 rounds, about 7 trained groups a round), otherwise as run 5 (cut responses
  kept, loss per response, KL coefficient 0.01, probe after rounds 7 / 15 / 23, guards, dev after round 24, floor
  63.06); it ends at round 24 (`MAX_ROUNDS=25`). Run name `sr_rl8`, unit `sr-b8`.
  Read as: probe and MMMU truncation at round 24 against the cold start (cut 15 % / right 47 %; 12.0 %) and against
  run 5 (23 % / 34 %; 20.8 %). It has about a third of run 5's updates, so "no loss" would say that the pool's
  outcome signal does no harm at that amount, not that the process term is proven harmful. Not a candidate model
  unless the user decides otherwise.
- 2026-11-16 14:19: user's decision ("1번이 맞을 듯" = the first option: hard questions in the training). Amendment 9
  written; hard pool built (`sr.py build_hard`: 55 rounds, 440 multiple choice + 220 numeric, 0 MMMU hits; a first
  build had 2 question ids used twice, an item present in both sources, fixed and asserted); the reward agrees with
  the stored correctness on 1,936 saved base responses; guard false-stop rates simulated; `grpo.py guard` got
  `--acc-floor` and `--trunc-max` (defaults = the old values), `sr.py` reads the pool name from `SR_POOL`. Unit
  `sr-hard1` queued behind diagnostic 6.
- 2026-11-16 15:43: **diagnostic 6 result** (no process term, no judgment tasks; reward = right; easy pool, 40
  questions a round, from the cold start; 25 rounds, 45 updates, KL max ≤ 0.036): MMMU dev r024 = **63.78**, Δ −1.38
  [−3.64, +0.73] against the base mean, +0.33 [−2.33, +3.00] against the cold start. **MMMU truncation 18.9 %** (cold
  start 12.0 %, run 5 20.8 %). Probe: round 7 cut 19 % / right 38 %, round 15 23 % / 44 %, round 23 23 % / 40 % (cold
  start 15 % / 47 %). Pool: right 0.90 → 0.93–0.97, cut 0–20 of 320 per round without trend, steps 4.8 → 5.3–6.7.
  On MMMU the finished responses did not change (median 1,420 characters against 1,378; re-check expressions per
  response 2.59 against 3.04; questions finished by both 70.1 → 71.4); only the share that never finishes rose.
  Reading: the rise of truncation does **not** come from the process term or the judgment tasks. A third of run 5's
  updates, with the outcome alone and a KL a quarter as large, gives the same rise. Six runs on the easy pool, six
  times more truncation on hard questions.
- 2026-11-16 15:44: checked on saved responses whether the outcome reward itself favours longer solutions: no. Within
  a question, right and wrong finished responses are equally long (length ratio median 0.99 on the easy pool, 1.00
  on the hard multiple-choice questions, 0.98 on hard numeric ones) and right ones do not have more re-check
  expressions. Hypothesis left, not tested: on the easy pool a wrong answer is rare and gets a large negative
  advantage in its group, while a response that never finishes hardly occurs there (1.5 %), so the model is told
  "committing in an uncertain state is bad" and never "not finishing is bad too"; on hard questions it then commits
  less often. The hard pool of Amendment 9 has both kinds in most groups (wrong 35–50 %, cut 17 %), each pushed down
  alike, so it predicts no such rise there; the probe at rounds 7 / 15 / 23 of run `hard1` is the first check.
  Unit `sr-hard1` started at 15:43 (probe of the base model first).
- 2026-11-16 16:22: run `hard1` (Amendment 9), start: probe of the base model: cut 31 %, right 28 % (the cold start had
  15 % / 47 % on the same questions; the probe guard's limits for this run are therefore cut above 39 %, right below
  16 %). Rounds 0–1 ran end to end: right 0.56 / 0.52, cut 10.4 / 17.7 %, mean 3,645 / 3,988 tokens, 9 of 12 groups
  trained in each (3 updates), KL max 0.001 / 0.002, guards pass. A round takes 11–13 minutes (rollout 7.5–9.6,
  training 2.7–3), so round 24 is about 5 hours after the start.
- 2026-11-16 23:20: **run `hard1`, round 24** (Amendment 9; 25 rounds, 70 updates, KL max 0.029, no guard tripped). MMMU dev seed 0 =
  **64.89**, Δ −0.27 [−2.53, +1.89] against the base mean, +0.22 [−2.67, +3.11] against base seed 0; base stable-correct
  (453) −0.88 [−3.53, +1.32]. **MMMU truncation 128 of 900 = 14.2 %** (base seed 0: 127 = 14.1 %; base seeds 0–4: 127 /
  139 / 133 / 146 / 144, mean 15.3 %). Finished by both (739): 71.0 → 70.9. Cut only by the base (33): 33.3 → 39.4; cut
  only by `hard1` (34): 41.2 → 26.5; cut by both (94): 34.0 → 40.4. Pool (different questions each round, so no
  same-question comparison): first 8 rounds right 0.497, cut 0.135; last 8 rounds right 0.431, cut 0.194. Probes after
  rounds 7 / 15 / 23: cut 23 / 17 / 21 %, right 42 / 40 / 40 % (base, one response each: 31 / 28).
  Registered acceptance at r024: dev above the base mean: **no** (64.89 < 65.16); truncation ≤ 14.1 %: 14.2 %, one
  question above the registered number, which was the base's seed-0 value (the base's own seeds reach 16.2 %). Not
  accepted; no 5-seed evaluation. Dev floor passed (64.89 > 63.06), so the run continues to round 49 as registered.
  Reading: the first of the seven GRPO runs of this protocol without a rise of MMMU truncation, and without a gain.
  It agrees with the hypothesis of 15:44, but pool and start model (A3 → base) changed together in a single run, so it
  does not separate them.

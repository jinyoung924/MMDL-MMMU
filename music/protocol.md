# Music target protocol — exact-label SFT where the base is near chance

Registered 2026-11-12 08:13, before any step-0 tagging. Nothing below changes after results are seen without the
user's decision; any change is recorded as a numbered amendment.

User decision (2026-11-12): "어 진행하자" to the staged plan below, starting with step 0. Steps 1–3 are an outline;
each gets its registered details in this file before it runs.

## Why
- v8–v12 taught items of the same kind as items the base already solves (hard numeric VWI). On the held-out 300
  the net change was never significant (+0.12 … +2.21), and v11 lowered MMMU (−3.11).
- Idea: use external, exact targets only for a skill where the base is near chance, so there is little to forget
  inside that domain, and hold the other domains with the base's own long correct solutions (v12 anchors; MC check
  −1.30 n.s.).
- Music on the official seeds 0–4 (`results/seed*`): 30 questions, all Sheet Music, all multiple choice.
  - Accuracy 36.0 %. 49.3 % of responses are truncated; truncated 25.7 % correct, finished 46.1 %.
  - 0/5 correct on 8 questions, 1–4/5 on 19, 5/5 on 3.
- Encoder probe (`encoder_probe/results.md`, synthetic scores only): a linear probe on frozen encoder features reads
  pitch 100 %, clef 100 %, key signature 86 %; the model asked directly reads 9 %, 51 %, 28 %.

## Steps (outline)
0. **Tag the first error on the Music questions** (no GPU). Gate below.
1. Reading test on realistic rendered scores (several staves, key signatures, accidentals; labels from the source
   notation) and the base measured on it.
2. Train: exact reading targets + interval / key questions built from the same scores + v12 anchors.
   Gates: reading on unseen pieces, Δ accuracy 95 % CI lower bound > 0; MC check (289 items) without a significant loss.
3. MMMU seed 0, then 5 seeds. Primary: Music Δ, CI lower bound > 0. Guard: no significant loss on the other 29 subjects.

MMMU val is never training data. In step 0 it is only read.

## Step 0 — is score reading the first failure?

**Population.** The 27 Music questions with at least one wrong answer in seeds 0–4.

**Shown per question** (`python music/step0.py export` → `music/step0/cases/<id>/`): the question, the gold answer, the
images, and up to two wrong responses — finished ones first, then truncated ones, each in seed order. A truncated
response is shown as its first 6,000 and last 3,000 characters.

**Taggers.** Two independent sets of Claude agents (A and B), 4 agents each, different batch splits
(`music/step0/batches.json`). They get `music/step0/tagger_instructions.md` and
`reports/failure_tagging_protocol.md` only. They are not told the hypothesis or this gate.

**Fields.** Protocol v1 fields, plus:
- `first_error`: the step-5 tag (P / T / K / R / PK) of the first error in the visible text, also when the tag is G;
  `none` if no error is visible.
- `reading_kind` when `first_error` is P: pitch, accidental-or-key-signature, clef, rhythm-or-meter, location
  (bar, staff, part), other.

**Gate** (`python music/step0.py summary`):
- Judged set = the 27 minus questions that both taggers tag D or S.
- Strict count = questions where both taggers give `first_error` = P. Lenient count = at least one does.
- **Pass** if strict ≥ half of the judged set.
- **Fail** if lenient < half of the judged set. The Music target stops and the result goes to the user.
- **Otherwise** I open the images of every question the taggers disagree on and decide P or not P
  (`music/step0/adjudication.jsonl`, one reason per question). Pass if strict + adjudicated P ≥ half.

**Also reported:** agreement between A and B (Cohen's κ on `first_error` = P vs not, and raw agreement on the tag),
the `reading_kind` counts, and the tags of the questions that are not P.

**Limits.**
- Taggers and adjudicator are the same model family, and reading dense scores from images is error-prone for them
  too. A human check of a sample is still needed.
- A tag records the first wrong statement in the written solution. It does not show that fixing it fixes the answer.
- The gate was chosen before tagging but after seeing the Music accuracy and truncation numbers above.

## Amendment 1 (2026-11-12, user decision "어 진행해" after the step-0 report)
The step-1 reading test uses exam-style excerpts on one staff, like the MMMU Music images, instead of the outline's
scores with several staves. Reason: step 0 showed that 26 of the 27 tagged questions use such excerpts.

## Step 1 — reading test and base measurement
Registered 2026-11-12, after the test items were generated and checked by eye, before any model saw them.

**Test set** (`python music/reading.py test` → `music/data/read_test.jsonl`, images in `music/data/read_test/`):
300 multiple-choice items, 50 per task, 4 options, gold letter balanced over A–D, in the pool format of `grpo/`
(same CoT MC prompt as `run_eval.build_prompt`).
- Rendering: ABC → verovio → PNG. Music font **Leland**, which later training data must not use. Images are grey,
  90–200 px tall, lightly blurred and JPEG-compressed, to resemble the MMMU Music scans. Labels come from the ABC.
- Tasks:
  - `clef`: treble, bass, alto or tenor, on a two-bar melody.
  - `pitch`: one whole note in any of the four clefs, up to two ledger lines, natural, sharp or flat; answer = note name.
  - `keysig`: 0–6 sharps or flats; answer = how many and which.
  - `timesig`: 12 time signatures on a two-bar melody.
  - `duration`: one note or rest, 8 values from sixteenth to whole, three of them dotted.
  - `interval`: two whole notes in treble or bass clef, 2nd to 10th; answer = quality and number.
- Checks done: self-test of the interval and note-name code (`reading.py` asserts); 31 rendered items compared by
  eye with their labels, all correct. A first version drew a stray "0" for `M:none`; fixed by omitting the meter line.

**Base measurement** (same procedure as the held-out tests, `grpo/heldout_protocol.md`): `grpo.py screen` on the base
engine, T = 1, 4 samples per item, engine seed 0, 8,192 tokens → `music/runs/read_base.jsonl`. Note that this is not
the evaluation sampling recipe (0.7 / 0.8 / 20 / 1.5).

**Reported** (`python music/reading.py report music/runs/read_base.jsonl`): per task and overall, accuracy with a
95 % bootstrap CI over items, share of truncated responses, accuracy of finished responses.

**Rule.**
- Overall accuracy < 70 % → go to step 2.
- Overall accuracy ≥ 70 % → stop and report: the test does not reproduce the failure seen on MMMU.
- Tasks where the base reaches ≥ 90 % count as already read. The step-2 reading gate uses the other tasks' items.

**Limit.** Test and later training items come from the same generator. Leland keeps the font unseen, but the gate
measures reading of rendered excerpts, not of scanned exam papers. Only step 3 (MMMU) tests that.

## Step 2 — training and gates
Registered 2026-11-12, after the training items were generated and checked by eye, before any generation or
training. Runs as `music/chain.sh`.

**Targets: the base's own solutions, written with the exact reading in the prompt** (the v9 procedure). The prompt
of each training item carries what the image shows, in words derived from the ABC (clef, staff position, accidental,
note name, and so on), and the base solves the item step by step in its own words. Training pairs that solution
with the normal prompt, which has no reading in it. Reason: the target then holds the correct statement about the
image in the model's own style (in target-origin terms: external information, self-generated form).
- Items (`python music/reading.py train` → `music/data/read_train.jsonl`): 2,400 — pitch 800, interval 600,
  keysig 300, duration 300, clef 200, timesig 200. Fonts Leipzig, Bravura, Gootville, Petaluma; never Leland. No
  (task, ABC) pair of the test set. Small tasks repeat an item as a new render (pitch has 149 distinct items).
  Duration items get a random key signature, so that every note and rest value exists outside the test set.
- Checks done: the test set regenerates identically after the code change (rows and all 300 images); 12 training
  items in the four fonts compared by eye with their labels, all correct; one reference per task read through.
- Generation: `grpo.py screen`, 2 samples per item, engine seed 3, T = 1 → `music/runs/read_train_gen.jsonl`.
- Selection (`python music/reading.py select`): one random response per item among those that are correct,
  finished and do not mention that a reading was given (regex `LEAK`). **Stop** if a task keeps < 60 % of its items.
- Anchors: the 3,217 `replay` responses of `grpo/runs/v12/rft_train.jsonl` (the base's own long correct solutions:
  1,093 numeric, 2,124 MC). The v9 knowledge targets are not used.

**Training** (`python grpo/rft.py train music`): identical to v7–v12 — LoRA r16, α32, LR 1e-4, 2 epochs, seed 0,
16 responses per update. The epoch-2 adapter is the registered one.

**Gates.** Both are run whatever the first one says.
1. Reading: the test set, same procedure as for the base (4 samples, seed 0), with the adapter →
   `music/runs/read_tuned.jsonl`. Paired per-item Δ, bootstrap over items. **Pass** if the 95 % CI lower bound over
   all 300 items is > 0. Per-task rows are reported.
2. MC check: 289 items (`grpo/data/heldout/v7_unseen_v12.txt`), 4 samples, seed 0, against
   `grpo/runs/heldout/v7_base.jsonl`, as in v12. **Fail** if the whole 95 % CI is below 0. Truncation, finished
   length and wait+check per 1k characters are reported.

**If both pass, step 3 seed 0 runs in the same chain:** merge, `SEEDS=0 bash eval.sh` → `runs/music_full`, then
`analyze.py compare results/seed* vs … --base-mean 1 --target Music`. One seed on 30 Music questions cannot confirm
anything; it is a first look. The 5-seed run starts only after the seed-0 result has gone to the user.

**Expected cost:** generation ≈ 0.5 h, training ≈ 3 h, reading gate ≈ 0.5 h, MC check ≈ 0.7 h, MMMU seed 0 ≈ 1.2 h.

**Limits.**
- The targets will be shorter than the base's usual solutions. On Music little is at stake; the MC check watches
  the other domains for the v9-type loss.
- Pitch and interval items have no key signature, although some MMMU questions need it (Music_14, Music_28).
- The numeric held-out 300 is not used here (it has served five tests).

## Amendment 2 (2026-11-12, user decision "어 1번으로 진행" after the step-2 stop)
Registered before any training. The own-words targets are replaced by **template targets**.
- For every training item the solution is its exact reading (the text the first attempt put in the prompt), then
  "Among the options, that is (X) …" and "Answer: X" (`python music/reading.py select template`). All 2,400 items
  are used. No generation pass. The 60 % rule belonged to the own-words attempt and no longer applies.
- Added with this amendment: for a pitch on or beyond a ledger line, the reading spells out the steps from the
  nearest staff line ("Counting down one step at a time from line 1 (D3): C3, B2, A2, G2."), 379 items. The items
  themselves (images, options, gold) are unchanged; checked.
- Unchanged: training items, anchors, training settings, both gates, step 3.
- Checks done: 5,617 rows (2,400 + 3,217 anchors); every template is read as correct by the answer parser; no test
  item and no Leland image in the training file; four targets read through.
- What this gives up: the targets are no longer in the model's own form. They are short (median 361 characters;
  anchors 8,789) and each task has one sentence pattern. Whether a reading learned this way is used on the
  differently worded MMMU questions is tested only by step 3.

## Amendment 3 (2026-11-13) — round 2 of the Music training data
Registered 04:08, after the 5-seed result, before any round-2 model run. User direction (2026-11-13 01:15, after
the tagging report and the question whether the result could end below the base): "그럼 이런 식으로 작업을 해놓자.
화학이나 기타 분야들도". Round 2 is trained together with the chem items in one adapter; that training, its gates
and its MMMU criteria are registered in `targets/protocol.md` ("Round 2").

What changes in the Music data, each tied to what step 3 showed:
- **Notes under a key signature** (new tasks `pitch_key`, `interval_key`): `Music_14` and `Music_28` were misread
  because a key signature changes the note. The reading states the key signature and why the note is or is not
  changed by it (the key signature, or the note's own sharp, flat or natural sign).
- **Worn training renders** (`render_worn`): half of them tilted by up to 1.5°, a quarter with heavier strokes,
  height 70–220 px, a quarter in pure black and white, uneven margins, sometimes a stray letter. The tuned model
  read rendered excerpts at 89 % and scanned MMMU excerpts worse.
- "an alto clef" instead of "a alto clef" in the readings.
- Training set `python music/reading.py train2` → `music/data/read_train2.jsonl`: 2,550 items (pitch 500,
  pitch_key 500, interval 400, interval_key 300, keysig 250, duration 250, clef 200, timesig 150), the four
  training fonts, no item of either test set. Round 1's files (`read_train*`, `grpo/runs/music/`) are kept as trained.
- Supplementary test `python music/reading.py test2` → `music/data/read_test2.jsonl`: 50 `pitch_key` and 50
  `interval_key` items, font Leland, rendered like the registered test set. It is reported, not a gate.
- The registered test set (300) is unchanged and stays the Music reading gate.

Checks done:
- `python music/reading.py check`: every pitch and interval label agrees with the notes verovio itself holds after
  reading the ABC — test 100/100, test2 100/100, round-1 training 1,400/1,400, round-2 training 1,700/1,700.
  (verovio keeps the previous piece's key in its note data for a following piece in C. The drawing is not affected:
  renders before and after a keyed piece are pixel-identical. The check reads only written accidentals for pieces in C.)
- The registered test set regenerates identically with the round-2 code (rows and images, clef and pitch tasks).
- 12 key-signature test items and 17 worn training items compared by eye with their labels, all correct.

## Amendment 4 (2026-11-13) — round 3: make the reading reliable where it is weak, and teach the steps after it
Registered 15:37, after the round-2 result and the paired check, before any round-3 training. User decision
(2026-11-13, after the cost and gain estimates): "어 진행해보자. 우선 music 으로 이 방법이 우선 통하는지 조금이라도
개선이 생기는지 부터 봐야함". Runs as `music/chain_round3.sh`.

**What the round-2 model gets wrong on the reading tests** (800 responses, classified from its own sentences):
- Single notes: inside the staff 92.9 %, outside the five lines 80.9 %. Of 58 wrong answers, 22 name the wrong clef,
  13 state the wrong position, 7 derive the wrong note name from the right position, 9 fail later.
- Two-note items: 76.5 %. Of 94 wrong answers, 35 misread a note, 25 have both notes right and the semitone count
  wrong, 31 have notes, number and semitones right and the quality or the option wrong.
- On the five MMMU questions of the paired check it does no better with re-drawn images than with the scans.

**Round-3 training data** (`python music/reading.py train3` → `music/data/read_train3.jsonl`, 3,700 items; item
builder `item3`):
- Half of all single notes sit outside the five lines (edge or ledger lines); two-note items start there half the time.
- More C clefs: 400 clef items, two thirds alto or tenor; two-note items also in alto and tenor clef.
- The steps after the reading are written out: the semitone count from the natural notes plus the effect of each
  accidental, then the size of the major or perfect interval of that number, then the comparison that gives the
  quality. A new task asks for the semitone count alone (`semitones`, 300 items).
- Every reading of a piece without a key signature says so ("There is no key signature").
- Several question forms: three wordings per task, the interval asked by full name, by quality alone, or as a
  true-or-false statement; note names also as true-or-false (about 20 % of the note and interval items).
- Counts: pitch 800, pitch_key 600, interval 600, interval_key 400, clef 400, semitones 300, keysig 250,
  duration 250, timesig 100. Worn renders and the four training fonts as in round 2. No item shares its content
  with either test set under any task name.
- Checks done: `reading.py check` — all 2,700 note, interval and semitone labels agree with verovio's note data;
  the 531 true-or-false items are consistent with their truth and always list (A) True (B) False; five targets
  read through.

**Training**: `targets/round2.py select round3 read_train3` (3,700 + the 3,217 v12 anchors, no chem), then
`grpo/rft.py train round3`, settings unchanged (LoRA r16, α32, LR 1e-4, 2 epochs, seed 0).

**Gates.** MMMU is run only if all four pass; otherwise the chain stops and the result goes to the user.
1. Reading test (300), 4 samples: paired Δ against the base, CI lower bound > 0. (Key-signature items reported.)
2. Positions (`reading.py cells`, both test sets): single notes outside the five lines ≥ 90 % and two-note items
   ≥ 85 % (round 2: 80.9 % and 76.5 %).
3. Paired check (`rerender_check.py gate`): the five MMMU questions with their scanned images, 16 samples, T = 1:
   ≥ 70 % of answers right (round 2: 50 %, base 42.5 %, at 8 samples).
4. MC check (289): fails if the whole CI is below 0.

**MMMU, 5 seeds** (`runs/round3_full`, `targets/round2.py compare … round3 music/rerender/ids.txt`):
- The five questions of the paired check (`Music_3, 15, 25, 26, 28`) were looked at while rounds 2 and 3 were
  designed and serve as gate 3. They are development questions: reported, but in neither group below.
- **Primary:** Δ on the other 25 Music questions, pass if the CI lower bound > 0. (Round 2 on these 25: −3.2
  [−14.4, +8.0]; its +1.3 on all 30 came from the five development questions.)
- **Guard:** Δ on the 870 questions of the other subjects; a loss counts if the whole CI is below 0.
- **Adoption:** only if the overall Δ is ≥ 0 and the guard holds.

**Limits.** Gate 3 rests on five questions. Twenty-five questions give a wide interval for the primary criterion
(about ± 12 points), so only a large Music gain can be established.

## Run log
- Step 0 launched 2026-11-12 08:14: 27 cases exported (37 images, longest side up to 2,954 px, taggers told to
  crop and enlarge); 8 tagger agents started (A 7/7/7/6, B 7/7/7/6 cases).
- **Step 0 done 08:24: PASS.** Tags in `music/step0/tags_{A,B}.jsonl`, gate output in `music/step0/summary.txt`.
  All 54 evidence quotes occur verbatim in the case files (checked by script).
  - Judged 26. `validation_Music_18` is tagged D by both taggers (the accidental is blurred; read as a sharp, the
    gold key does not fit the image; medium confidence).
  - `first_error` = P: A 23, B 23, strict 23, lenient 23 of 26 (needed 13). No disagreement, so no adjudication.
    κ (P vs not) 1.00; tag agreement 25/27 (`Music_16`: X vs K). Confidence: high 22, medium 5 for each tagger.
  - Not P: `Music_7` (K: states "E minor has 3 sharps" before reading the score), `Music_16` (says it cannot see
    the images, then guesses), `Music_29` (K: takes the bassoon for a treble-range instrument).
  - `reading_kind` (A / B, 24 questions including Music_18): pitch 11 / 10, rhythm-or-meter 7 / 7, clef 2 / 2,
    accidental-or-key-signature 2 / 2, other 2 / 3.
  - Tag split (A): P 15, G 9 (all shown responses cut off; the first visible error is P in 8, K in 1), K 1, X 1, D 1.
- Spot check by me, images opened (not part of the gate): `Music_3, 4, 15, 23, 26, 28` — the taggers' readings hold
  in 6 of 6. Examples of what the model wrote: alto clef read as bass clef, 2/4 read as 3/4, 9/8 read as 3/8, a
  two-flat key signature read as a sharp, a note in a space read as on a line.
- Check on existing runs (not part of the gate): larger input images do not raise Music. Qwen pixel setting
  (min 1.0 M px, seed 0) 30.0 %, hires (min 262 k px, seed 0) 36.7 %, base seed 0 40.0 %, seed 1 33.3 % (n = 30 each).
- For step 1: the Music images are mostly small exam-style excerpts (median 164 k px, 25 of 37 under 250 k px):
  one staff, a clef and a few notes. Only `Music_21` is an orchestral score. The outline's "several staves" is
  therefore not what the target looks like; changing it needs the user's decision (given, see Amendment 1).
- Step 1 base measurement launched 2026-11-12 08:52 (unit `music-read-base`, RAM guard `music-read-base-watch`,
  log `music/runs/read_base.out`).
- **Step 1 done 09:32 (39 min, 1,200 responses): overall 44.4 % [39.8, 49.0] < 70 % → go to step 2.** No task reaches
  90 %, so all six stay in the step-2 reading gate. Report in `music/runs/read_base_report.txt`.

  | task | accuracy [95 % CI] | truncated | finished accuracy |
  |---|---|---|---|
  | clef | 49.5 [36.0, 63.0] | 0.0 % | 49.5 |
  | pitch | 20.5 [14.5, 27.0] | 1.0 % | 20.7 |
  | keysig | 53.0 [41.5, 65.0] | 1.5 % | 53.8 |
  | timesig | 82.5 [73.5, 90.5] | 0.0 % | 82.5 |
  | duration | 39.0 [28.0, 50.0] | 1.5 % | 39.6 |
  | interval | 22.0 [15.5, 29.0] | 38.0 % | 35.5 |

  - Every finished response carries an answer tag, so the low scores are not a parsing effect.
  - Clef by class: bass 100 %, treble 90 %, alto 0 %, tenor 0 % (a C clef is never recognised).
  - Pitch is at chance (4 options) in every clef: treble 11 %, bass 20 %, alto 28 %, tenor 19 %.
  - Interval responses are long (finished median 17,068 characters) and 38 % are cut off, as on MMMU Music.
- Step 2 chain launched 2026-11-12 09:41 (`music/chain.sh`, unit `music-chain`, RAM guard `music-chain-watch`, log
  `music/runs/chain.out`).
- **Step 2 stopped at selection, 11:48, by the registered rule.** Generation took 2 h 7 min (expected 0.5 h; interval
  responses have a median of 13,110 characters even with the reading in the prompt). No training was run.
  - Correct in generation: clef 86 %, pitch 91 %, keysig 97 %, timesig 100 %, duration 97 %, interval 75 % (16 % cut off).
  - Items kept by `select` (correct, finished, no `LEAK` match): clef 84.5 %, pitch 76 %, keysig 97 %, timesig 100 %,
    duration 76 %, **interval 51.8 % (< 60 %)**. 1,477 correct responses were dropped for mentioning the given reading.
  - Looking at what passed (exploratory, after the stop): many solutions still lean on the prompt ("the prompt
    says …", "not an alto clef as mentioned in the prompt") or copy the given sentences. With a stricter filter
    (those phrases, or 8 consecutive words copied from the reading) the kept share is clef 78 %, pitch 41 % (79 of
    149 distinct pitch items), keysig 88 %, timesig 100 %, duration 46 %, interval 4 %.
  - Interval solutions are long because the semitone counting goes wrong (e.g. "G4 to A4 is 1 semitone"), not the reading.
  - Reading: the own-words procedure works when the model can do the task once it has a hint. Here the hint is the
    perception itself, which the model does not have, so it cites, copies or argues with it. What to do next is the
    user's decision.
- Amendment 2 chain launched 2026-11-12 18:18 (`music/chain.sh`, same units and log; a "relaunch" line marks the
  start in `music/runs/chain.out`).
- **Step 2 done 21:58: both gates pass.** Training 702 updates, 3 h 4 min.
  - Reading gate (`music/runs/gate_reading.txt`): **44.4 → 88.7 %, Δ +44.25 [+39.25, +49.25]**; truncation 7.0 → 0.3 %.

    | task | base → tuned | Δ [95 % CI] |
    |---|---|---|
    | clef | 49.5 → 93.5 | +44.0 [+31.0, +56.5] |
    | pitch | 20.5 → 84.5 | +64.0 [+53.5, +74.0] |
    | keysig | 53.0 → 98.0 | +45.0 [+32.5, +57.0] |
    | timesig | 82.5 → 100.0 | +17.5 [+9.5, +26.5] |
    | duration | 39.0 → 84.5 | +45.5 [+30.5, +59.5] |
    | interval | 22.0 → 71.5 | +49.5 [+39.0, +60.0] |
  - MC check (`music/runs/gate_mc.txt`): 86.8 → 84.8 %, Δ **−1.99 [−4.24, +0.26]**. Passes by the rule (the CI
    includes 0) but only just; v12 had −1.30. Truncation 3.9 → 4.3 %, finished length 4,254 → 4,153 characters,
    wait+check per 1k 0.90 → 0.87.
- **Step 3 seed 0 done 23:08** (`runs/music_full/compare_base_mean.txt`): all 900 +0.07 [−1.98, +2.13]; **Music
  +4.00 [−12.00, +21.33]**; other 29 subjects −0.07 [−2.21, +2.07]; their base stable-correct questions +1.11
  [−1.33, +3.56]. Truncation 14.1 → 14.7 %. By the §5.5 labels a candidate (point > 0, no forgetting signal); on its
  own it shows no Music gain: tuned seed 0 scores 40.0 %, the base seeds 40.0 / 33.3 / 30.0 / 30.0 / 46.7.
  - The trained reading is used on MMMU Music and nowhere else: its phrases appear in 15 of 30 Music responses
    (base seed 0: 1) and in 0 of 870 others. Music truncation 49.3 % (base mean) → 23.3 %; median response
    15,859 → 4,850 characters.
  - Read correctly on real images: `Music_15` (alto clef, C3; base 0/5) and `Music_26` (A♭ in space 2), both now right.
  - Read wrongly, in the trained wording: `Music_28` (treble clef called a bass clef), `Music_14` (the key
    signature's sharp taken as an accidental, a note placed "in space 5"), `Music_3` (first note right, second
    note wrong). So the format transfers to the scanned questions, the reading itself only partly.
  - Defect found in the targets: the templates say "a alto clef" (should be "an"); the model reproduces it.
    It does not change any label.
- Step 3 details, registered 23:10 after seed 0 and before seeds 1–4 (`music/chain_5seed.sh` → `runs/music_full/`;
  launched 23:10 as unit `music-5seed`, log `music/runs/chain_5seed.out`):
  - Primary: Music Δ over 5 paired seeds, pass if the CI lower bound > 0 (`compare.txt`, "target subjects").
  - Guard: the other 29 subjects' Δ over 5 paired seeds; a loss counts if the whole CI is below 0.
  - Also reported: Δ on their base stable-correct questions from the seeds-0–1 comparison (`compare_seeds01.txt`,
    selection on base seeds 2–4), Music truncation, and how many Music responses use the trained reading.
- **Step 3 done 2026-11-13 03:55 (5 seeds): the primary criterion is not met; the guard holds.**
  Tuned 65.22 ± 0.98 (65.22 / 64.78 / 65.22 / 66.78 / 64.11), base 65.16 ± 0.93.

  | group | Δ, 5 paired seeds | 95 % CI |
  |---|---|---|
  | all 900 | +0.07 | [−1.16, +1.29] |
  | Music, 30 (primary) | **+5.33** | **[−6.00, +18.00]** |
  | other 29 subjects, 870 (guard) | −0.11 | [−1.38, +1.10] |
  | their base stable-correct questions, 468 (seeds 0–1) | +0.00 | [−1.71, +1.71] |

  - Music per seed: base 40.0 / 33.3 / 30.0 / 30.0 / 46.7 (mean 36.0), tuned 40.0 / 36.7 / 40.0 / 43.3 / 46.7 (mean
    41.3). Tuned is never below the base seed; with 30 questions that is still inside the noise.
  - Per question (150 responses each): 22 responses gained, 14 lost. Largest gains `Music_15` 0 → 5, `Music_25`
    2 → 5, `Music_19` 0 → 3; largest losses `Music_18` 3 → 0, `Music_3` 2 → 0, `Music_28` 2 → 0.
  - Music truncation 49.3 → 32.0 %; accuracy of finished Music responses 46.1 → 47.1 %.
  - The trained reading appears in 73 of 150 Music responses (46.6 % of them correct; 36.4 % of the other 77) and in
    0 of 4,350 responses on other subjects.
  - Stable-correct questions wrong in both paired seeds: base 3, tuned 7 (4 of them cut off or without an answer tag).
  - Reading: the skill is learned (step 2), used only on Music, and costs nothing measurable elsewhere (CI ± 1.2).
    The Music gain has the right sign and size (+1.6 questions) but is not established. The losses sit on questions
    where the tuned model now misreads a scanned image in fluent template wording (key signatures, real engraving).
- Round 2 (Amendment 3, trained and judged under `targets/protocol.md`): gates passed 2026-11-13 08:13 (reading test
  88.7 %, key-signature items 84.8 %, MC check −0.43 [−2.34, +1.38]); MMMU 5 seeds done 14:06: Music +1.33
  [−10.67, +14.67], other subjects −0.07 [−1.22, +1.03], overall −0.02. Primary not met, base stays. Details and
  the comparison with round 1 are in the run log of `targets/protocol.md`.
- Exploratory paired check, 2026-11-13 14:34–14:52 (`music/rerender_check.py`, `music/rerender/report.txt`; not
  registered beforehand; MMMU val images only read). Five MMMU Music questions whose content is one or two whole
  notes (`Music_3, 15, 25, 26, 28`) asked with the original scan and with the same notes re-drawn by the generator's
  renderer; base, round 1 and round 2; 8 samples, T = 1, seed 0 (40 responses per cell).

  | model | image | answer right | all note names stated right |
  |---|---|---|---|
  | base | scan / redrawn | 42.5 % / 45.0 % | 12.5 % / 7.5 % |
  | round 1 | scan / redrawn | 50.0 % / 40.0 % | 30.0 % / 45.0 % |
  | round 2 | scan / redrawn | 50.0 % / 50.0 % | 45.0 % / 45.0 % |

  - The trained models do no better on the re-drawn images than on the scans. So the look of the scans is not what
    stops the transfer on these questions. My earlier explanation to the user (rendered vs scanned appearance) was
    not supported and is withdrawn.
  - All five questions have a note on or beyond a ledger line or just outside the staff. On the registered test the
    trained models are weaker exactly there (round 2: pitch inside the staff 88 %, on ledger lines 75 %, just
    outside the staff 62 %; intervals 62–82 %), and the questions also need steps after the reading (counting
    letter names and semitones), which the models get wrong (e.g. "from B up to A gives 5 (B C D E F)").
  - When the trained models state all note names correctly the answer is right in 57–61 % of responses, otherwise in
    38–41 % (crude string match; it over-counts for `Music_15`). A correct reading helps but does not settle the answer.
  - Limits: five questions, T = 1 sampling, a string match for "reading right".
- Round 3 (Amendment 4) launched 2026-11-13 15:38: `music/chain_round3.sh`, unit `round3`, RAM guard
  `round3-watch`, log `music/runs/chain_round3.out`.
- **Round 3 gates done 20:22: three of four fail; MMMU not run.** Training 864 updates, 3 h 50 min.
  - Gate 1, reading test: 44.4 → 87.9 %, Δ +43.50 [+38.42, +48.50] — pass. Clef 96.0, pitch 87.5, keysig 92.0,
    timesig 98.5, duration 73.5 (round 2: 92.5), interval 80.0 (7 % of its responses cut off; round 2: 0.5 %).
    Key-signature items 29.8 → 91.0 % (`pitch_key` 97.5, `interval_key` 84.5).
  - Gate 2, positions: single notes outside the five lines 92.0 % (round 2: 80.9) — met; two-note items 82.2 %
    (round 2: 76.5) — below 85 %. **Fail.**
  - Gate 3, paired check, 16 samples: 65.0 % of the answers on the scanned images right (round 2: 50.0, base 42.5)
    — below 70 %. **Fail.** On the re-drawn images 78.8 % of answers and 95.0 % of full readings are right; on the
    scans 63.8 % of full readings. With the reading now good on re-drawn images, a difference between scan and
    re-drawn image shows; in round 2 it was hidden because both were read badly. My statement that the look of the
    scans is not what stops the transfer was therefore only half right.
  - Gate 4, MC check: 86.8 → 83.9 %, Δ **−2.85 [−5.19, −0.61]**. **Fail: a significant loss**, the first in this line
    (round 1: −1.99 [−4.24, +0.26], round 2: −0.43 [−2.34, +1.38]). Truncation 3.9 → 4.0 %, finished length
    4,254 → 4,387 characters, wait+check per 1k 0.90 → 0.87.
- 20:27: adapter-strength check started on the round-3 adapter (`music/sweep_round3.sh`, unit `sweep3`): copies with
  `lora_alpha` 16 and 24 instead of 32 (strength 50 % and 75 %), each through the reading tests, the paired check
  and the MC check. No training; reported, not a gate. This is the strength knob named in the guard of
  `targets/protocol.md`.
- Strength check done 2026-11-14 00:13 (`music/runs/gate_*_round3_a50|a75.txt`):

  | strength | reading test | single notes outside the staff | two-note items | paired check, scans | MC check Δ |
  |---|---|---|---|---|---|
  | 100 % | 87.9 % | 92.0 % | 82.2 % | 65.0 % | −2.85 [−5.19, −0.61] |
  | 75 % | 78.2 % | 85.1 % | 43.0 % | 48.8 % | −1.73 [−3.89, +0.35] |
  | 50 % | 55.5 % | 41.0 % | 11.0 % | 28.8 % | −1.73 [−3.81, +0.26] |

  The reading falls away quickly with lower strength, the MC loss only a little. No strength keeps the reading and
  removes the loss.
- 02:36: exploratory run outside the gates, on the user's instruction to continue and their stated priority (does
  Music move at all): the round-3 model on the 30 MMMU Music questions only, frozen pipeline, 5 seeds
  (`music/music_only_round3.sh`, unit `musiconly` → `runs/round3_music/music.txt`). The base is first run on Music
  only (seed 0) to confirm that a subject-only run reproduces the full run's Music answers. This run cannot lead to
  adoption: gates 2–4 failed, and it does not measure the other subjects.
- **Music-only run done 03:22 (`runs/round3_music/music.txt`): Music does not improve.**
  The base on Music only reproduces the full run exactly (seed 0: 30 of 30 responses identical).

  | group | base → round 3 | Δ, 5 paired seeds | 95 % CI |
  |---|---|---|---|
  | Music, all 30 | 36.0 → 33.3 | −2.67 | [−16.67, +12.00] |
  | Music, the 25 outside the paired check | 35.2 → 26.4 | −8.80 | [−20.00, +3.20] |
  | the 5 paired-check questions | 40.0 → 68.0 | +28.00 | [−32.00, +76.00] |

  - Per seed: base 40.0 / 33.3 / 30.0 / 30.0 / 46.7, round 3 23.3 / 30.0 / 33.3 / 46.7 / 33.3.
  - Music truncation 49.3 → 29.3 %; accuracy of finished Music responses 46.1 → 37.7 %. The trained reading
    appears in 104 of 150 responses (38 % of them correct, 22 % of the others). 21 responses gained, 25 lost.
  - The gain sits on the five questions whose content the items were built around (one or two whole notes). On the
    other 25 — chords, rhythm, melodies, ornaments, keys, full scores — the model is not better and nominally worse.
  - Reading across the three rounds: the training fixes the reading of what its generator draws and nothing else
    in Music. Music as a subject did not improve in any round (+5.3, +1.3, −2.7; none established), and round 3
    added a significant loss on the MC check. By the plan stated to the user beforehand, this line stops here.

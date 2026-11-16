# Next targets — where else is misreading the first failure?

Registered 2026-11-13 00:10, before any tagging. Nothing below changes after results are seen without the user's
decision; any change is recorded as a numbered amendment.

User decision (2026-11-12, "어 진행해"): while the GPU runs the Music 5 seeds (`music/protocol.md`), tag the next
candidate image types without the GPU — all Chemical Structures questions and a sample of Diagrams.

## Why
- The Music target covers 2.1 of the 34.8 points the base loses on MMMU val (official seeds 0–4).
- The same recipe (exact-label training of a notation the base cannot read) could apply to other image types that a
  program can draw. Lost points by image type: Diagrams 9.9 (246 questions), Tables 4.0, Photographs 3.1, Plots and
  Charts 2.7, Sheet Music 2.1, Paintings 2.0, Chemical Structures 2.0 (31 questions).
- Before building anything, check on the questions themselves whether misreading the image is the first failure,
  as step 0 did for Music.

MMMU val is only read here. Nothing is trained.

## Populations (`python targets/tag.py export` → `targets/<set>/cases/<id>/`)
- `chem`: every question with image type Chemical Structures and at least one wrong answer in seeds 0–4 (25 of 31).
- `diagrams`: questions with image type Diagrams and at least one wrong answer (144 of 246), shuffled with seed 0;
  the first 48 are tagged (`targets/diagrams/order.txt` keeps the order).

Shown per question: the question, the gold answer, the images, and up to two wrong responses — finished ones
first, then truncated ones, each in seed order. A response longer than 9,000 characters is shown as its first 6,000
and last 3,000 characters (for Music only truncated responses were shortened; these responses are longer).

## Taggers
Claude agents with `targets/tagger_instructions.md` and `reports/failure_tagging_protocol.md` only; they are not
told the purpose or the rules below.
- `chem`: two independent sets, A and B, both on all 25.
- `diagrams`: set A on all 48; set B on the first 16 of the shuffled order, for agreement only.

Fields: protocol v1 fields plus `first_error` (the step-5 tag of the first error in the visible text, also when the
tag is G; `none` if no error is visible), `misread` (what was misread, when `first_error` is P) and `image_kind`
(what kind of drawing the image is).

## Rules (`python targets/tag.py summary chem|diagrams`)
- `chem`, same rule as Music step 0. Judged set = the 25 minus questions both taggers tag D or S. Strict = both give
  `first_error` = P; lenient = at least one. **Reading is the first failure** if strict ≥ half of the judged set;
  **not** if lenient < half; in between I open the images of the questions they disagree on and decide.
- `diagrams` is descriptive, no pass or fail. Reported: the share of `first_error` = P among set A's judged
  questions with a 95 % Wilson interval, the counts per `image_kind`, and the agreement of A and B on the 16
  (κ on P vs not, raw agreement on the tag).
  A kind of diagram is called a candidate for the reading recipe when it has at least 5 sampled questions, at least
  half of them P, and a program can draw it with exact labels (my judgement, stated per kind).

## Limits
- Taggers and adjudicator are the same model family. A human check of a sample is still needed.
- A tag records the first wrong statement in the written solution. It does not show that fixing it fixes the answer;
  on Music the reading was learned (44 → 89 % on rendered excerpts) and seed 0 of MMMU still showed no gain.
- 48 diagrams give wide intervals per kind.

## Chem target, step 1 — reading test and base measurement
Registered 2026-11-13 01:25, after the test items were generated and checked, before any model saw them.

User decision (2026-11-13, after the tagging report): "그럼 이런 식으로 작업을 해놓자. 화학이나 기타 분야들도" — prepare
the same pipeline for chemistry and the other candidates. The user's worry, recorded as a design constraint: the
result must not end up below the base model (see "Guard" below).

**Test set** (`python targets/chem.py test` → `targets/chem/data/chem_test.jsonl`): 280 multiple-choice items, 40 per
task, gold letter balanced, in the pool format of `grpo/`, same CoT MC prompt as the MMMU evaluation.
- Drawing: SMILES built by the generator → RDKit skeletal formula, black on white. Label font **Nimbus Roman**, which
  training data must not use. Line width 1.3–2.8, a rotation out of {0, 0, 0, ±30, 90, 180}°, longer side
  180–560 px, light blur and JPEG compression as for Music.
- Tasks, chosen from what the tagging found misread:
  - `ring_size`: one carbon ring of 3–8 atoms, with or without double bonds and substituents; how many ring atoms.
  - `chain`: unbranched chain of 3–9 carbons with heteroatom labels; how many carbons.
  - `atom_count`: how many times one halogen label is drawn (1–4), next to other labels.
  - `ring_position`: two different groups on a six-membered ring (cyclohexane or benzene); 1,1 / 1,2 / 1,3 / 1,4.
  - `locant`: which carbon of a chain carries the group, counted from the nearer end (1–4).
  - `double_bonds`: how many C=C bonds are drawn (0–4) in a chain or ring.
  - `wedge`: whether the bond to a named group is a solid wedge, a hashed wedge or a plain line (3 options).
- Checks done: `python targets/chem.py check` compares the labels of 2,800 generated items with what RDKit computes
  from the same SMILES (ring size, carbon count, label count, double bonds, ring relation, locant, wedged bond): all
  agree. 38 rendered items compared by eye with their labels, all correct.
- The Music generator was refactored so that chem reuses its item format, splits, report and gate. The Music test
  set still regenerates identically (rows and all 300 images after the refactor; 60 of 60 images after the later
  sizing change).

**Base measurement**: `grpo.py screen`, base engine, T = 1, 4 samples per item, seed 0 →
`targets/chem/runs/chem_base.jsonl` (`targets/chem/base_after_5seed.sh`; it starts when the Music 5-seed evaluation ends).

**Rule**, as for Music step 1: overall accuracy < 70 % → build the training set; ≥ 70 % → stop and report (the test
does not reproduce the failure). Tasks where the base reaches ≥ 90 % count as already read and stay out of the gate.

**Limits.**
- No Fischer, Newman, chair or Haworth projections (5 of the 17 misread questions), no fused ring systems, no
  reaction schemes. The MMMU structures (morphine, ciprofloxacin, sugars) are far more complex than these molecules,
  so the gap between rendered items and MMMU is likely larger than it was for Music.
- On Music the reading was learned and MMMU seed 0 still showed no gain. Passing this step says nothing about MMMU.

## Guard against ending below the base (applies to every target)
- A trained model replaces the base only if the measured overall score is not below the base's; otherwise the base stays.
- The targets are to be trained into one adapter, not one adapter each, so that the diffuse cost on the other
  questions is paid once.
- Adapter strength is a free knob: the reading tests take minutes and the MC check half an hour, so a lower strength
  can be chosen where the MC check shows no loss.

## Round 2 — one adapter for Music (round 2) and chem
Registered 2026-11-13 04:08, before the chem base result and before any round-2 training. Runs as
`targets/chain_round2.sh` once the chem base measurement has finished.

**Why now.** Music round 1 (5 seeds, `music/protocol.md`): Music +5.33 [−6.00, +18.00], other subjects −0.11
[−1.38, +1.10], overall +0.07. The reading is learned and used only on Music, the gain is not established, and
nothing measurable is lost. The user's bar (2026-11-13): any gain in the overall score counts, and the result must
not end below the base.

**Training data** (`python targets/round2.py select` → `grpo/runs/round2/rft_train.jsonl`), template targets as in
Music Amendment 2:
- Music round 2: all 2,550 items of `music/data/read_train2.jsonl` (Music Amendment 3).
- Chem: decided by the chem step-1 rule from the base measurement — nothing if the base scores ≥ 70 % overall,
  otherwise the training items of the tasks the base reads below 90 % (up to 2,200).
- Anchors: the 3,217 `replay` responses of v12, as in Music round 1.
- Circuits are not in this round (no generator yet).

**Training** (`python grpo/rft.py train round2`): identical to v7–v12 and Music round 1 — LoRA r16, α32, LR 1e-4,
2 epochs, seed 0, 16 responses per update. The epoch-2 adapter is the registered one.

**Gates** (4 samples, seed 0, same procedure as before). All are run; MMMU follows only if none fails.
1. Music reading test (300): paired Δ against the base, pass if the 95 % CI lower bound > 0.
2. Chem reading test (280), only if chem was trained: same rule.
3. MC check (289): fails if the whole CI is below 0.
Reported, not a gate: the key-signature items (`read_test2`), base and tuned.

**MMMU, 5 seeds** (`runs/round2_full`, `python targets/round2.py compare`), paired with the base's 5 seeds,
bootstrap over questions:
- Target questions = the 30 Music questions, plus the 31 questions with image type Chemical Structures if chem
  was trained.
- **Primary:** Δ on the target questions, pass if the CI lower bound > 0.
- **Guard:** Δ on the other questions; a loss counts if the whole CI is below 0.
- **Adoption:** the trained model replaces the base only if the overall Δ is ≥ 0 and the guard holds.
- Also reported: overall, Music and Chemical Structures separately, stable-correct questions (seeds 0–1).

**What this cannot show.** An overall gain of about +1 is inside the 5-seed noise (CI about ± 1.2), so "adopt" means
"not measurably worse and nominally not below", not "better". Only the primary criterion can establish a gain.

**Expected cost:** training ≈ 3.6 h, gates ≈ 1 h, MMMU 5 seeds ≈ 6.3 h.

## Run log
- 2026-11-13 00:12: packets exported — `chem` 25 cases (39 images; Chemistry 15, Pharmacy 7, others 3), `diagrams`
  48 cases (51 images; Electronics 8, Materials 8, Biology 6, Energy and Power 4, Mechanical Engineering 4, 10 other
  subjects). 18 tagger agents started: chem A 7/6/6/6 and B 7/6/6/6, diagrams A 7×6 + 6 and B 6/5/5.
- **`chem` done 00:20: reading is the first failure** (`targets/chem/summary.txt`). Judged 24 (`Pharmacy_23` is D
  for both taggers). `first_error` = P: A 17, B 17, strict 17, lenient 17 (needed 12) = 71 %. κ 1.00, tag
  agreement 25/25, confidence high 22 / medium 3 for each. All 50 evidence quotes are verbatim.
  - The other 7 are K: the structure is read correctly and a rule is misapplied (VSEPR shape from a Lewis
    structure, number of stereoisomers, R/S from a Fischer projection, Markovnikov, basicity order, drug facts).
  - What is misread (17): ring size or ring count (7-membered ring read as benzene, bicyclic quinolone read as
    three rings, chair read as bicyclic), chain length and substituent count (heptane with 4 Br read as 3 carbons
    with 3 Br), which atom a group sits on (para NO2 placed on N, H placed on the carboxyl carbon, 1,4 read as
    1,2), wedge / dash and projections (Fischer, Newman, chair linkage), which bond an arrow or label points to.
  - Kinds of drawing: skeletal formulas and reaction schemes 11, projections (Fischer, Newman, chair, Haworth) 5,
    Lewis structures 2, others 7 (ball-and-stick model, binding-site sketch, one free-body diagram mislabelled as
    a chemical structure).
  - Spot check by me, images opened: `Chemistry_3`, `_4`, `_7` — the taggers' readings hold in 3 of 3.
- **`diagrams` done 00:21** (`targets/diagrams/summary.txt`). Set A: 48 tagged, judged 44 (3 D, 1 S).
  `first_error` = P in 22 of 44 = **50 % [36, 64]**; K 17, R 4, T 2, none 2. In 21 of the 48 every shown response is
  cut off (tag G). A and B agree on all 16 shared questions (κ 1.00, tags 16/16). Confidence high 37, medium 11.
  All evidence quotes are verbatim.
  - The taggers' `image_kind` labels are free text; grouped by me into families:

    | family | judged | P | K | other | cut off only |
    |---|---|---|---|---|---|
    | engineering drawings (structures, machines, fluids, heat) | 19 | 9 | 7 | 3 | 15 |
    | circuits | 7 | 5 | 1 | 1 | 3 |
    | geometry, plans, graphs | 5 | 3 | 1 | 1 | 3 |
    | biology and medical drawings | 5 | 4 | 1 | 0 | 0 |
    | cartoons, a photograph, a 2×2 matrix | 5 | 0 | 5 | 0 | 0 |
    | trees and networks (computer science) | 3 | 1 | 1 | 1 | 0 |
  - By the registered rule only **circuits** are a candidate (7 sampled, 5 P, a program can draw them with exact
    values and connections). Misread there: series taken as parallel, which nodes a resistor joins, shunt
    branches taken as one series chain, a component value.
  - Engineering drawings: 9 of 19 P (below half), and each drawing is one of a kind (where a load sits, which
    dimension is which, the shape of a cross-section), so no generator covers them. Not a candidate.
  - Biology and medical: 4 of 5 P, but only the two pedigree charts are a notation a program can draw (2 < 5 sampled).
  - The five cartoons, photograph and matrix carry the Diagrams label in MMMU but fail on knowledge.
  - `Chemistry_13` (tag S for both): gold 12.97, the model answers 13.0 after rounding to three significant
    figures in all five seeds. The official-style open-answer scoring needs the same number; nothing was changed.
- 2026-11-13 01:24: chem test set (280) and training items (2,200; fonts DejaVu Sans, DejaVu Serif, FreeSans,
  Nimbus Sans; no test item) generated. `rdkit 2026.09.2` added to the `vllm-train` env with `pip install --no-deps`
  (numpy and pillow unchanged). Base measurement queued as unit `chem-base` behind the Music 5-seed evaluation
  (log `targets/chem/runs/chem_base.out`).
- 2026-11-13 04:08: round-2 chain queued behind the chem base measurement (unit `round2`, RAM guard
  `round2-watch`, log `targets/round2.out`). The Music 5-seed evaluation ended 03:55 and `chem-base` started then.
- **Chem step 1 done 04:12 (17 min, 1,120 responses): overall 71.9 % [67.6, 76.0] ≥ 70 % → stop for chem.** By
  the registered rule the test does not reproduce the failure, so chem is not trained in round 2 (the chain's
  `select` applies the rule by itself). Report in `targets/chem/runs/chem_base_report.txt`.

  | task | accuracy [95 % CI] | truncated |
  |---|---|---|
  | ring_size | 87.5 [77.5, 95.6] | 0.0 % |
  | chain | 46.2 [36.9, 56.2] | 6.9 % |
  | atom_count | 83.1 [75.0, 90.6] | 1.9 % |
  | ring_position | 50.6 [37.5, 64.4] | 0.0 % |
  | locant | 66.2 [55.6, 76.2] | 3.7 % |
  | double_bonds | 85.6 [77.5, 92.5] | 0.6 % |
  | wedge | 83.8 [73.8, 92.5] | 0.0 % |

  - Reading: on simple drawn molecules the base reads ring size, labels, double bonds and wedges at 83–88 %. What
    it misreads on MMMU are much more complex drawings (fused rings, several stereocentres, projections, reaction
    schemes), which this generator does not produce. The result is close to the line (the CI includes 70 %), and
    three tasks are weak: counting chain carbons (46 %), ring positions (51 %), locants (66 %).
  - A chem target therefore needs a harder generator before any training. Not started; the user's decision.
- Round-2 chain started 04:13. Base on the key-signature items (`music/runs/read2_base_report.txt`, 35 min):
  `pitch_key` 43.5 % [34.5, 52.5], `interval_key` 16.0 % [10.0, 22.5] with 44 % of responses cut off, both 29.8 %.
  `select`: Music 2,550 + chem 0 + anchors 3,217 = 5,767 rows. Training started 04:49 (720 updates).
- **Round-2 gates done 08:13: all pass.** MMMU 5 seeds started 08:13.
  - Music reading test (`music/runs/gate_reading_round2.txt`): 44.4 → 88.7 %, Δ **+44.25 [+39.25, +49.17]** (round 1:
    88.7). Clef 92.0, pitch 81.5, keysig 89.5, timesig 100.0, duration 92.5, interval 76.5; truncation 7.0 → 0.1 %.
  - Key-signature items (`gate_reading2_round2.txt`, reported): 29.8 → 84.8 %, Δ +55.00 [+47.25, +62.50];
    `pitch_key` 43.5 → 93.0, `interval_key` 16.0 → 76.5; truncation 22.8 → 0.0 %.
  - MC check (`gate_mc_round2.txt`): 86.8 → 86.3 %, Δ **−0.43 [−2.34, +1.38]** (round 1: −1.99 [−4.24, +0.26]);
    truncation 3.9 → 2.9 %, finished length 4,254 → 4,196 characters, wait+check per 1k 0.90 → 0.87.
- **Round 2 MMMU done 14:06 (5 seeds, `runs/round2_full/verdict.txt`): primary NO, guard YES, adopt NO.**
  Tuned 65.13 (65.33 / 64.89 / 66.89 / 64.89 / 63.67), base 65.16. The base stays.

  | group | Δ, 5 paired seeds | 95 % CI | round 1 |
  |---|---|---|---|
  | all 900 | −0.02 | [−1.16, +1.13] | +0.07 |
  | Music 30 = target questions (primary) | **+1.33** | **[−10.67, +14.67]** | +5.33 [−6.00, +18.00] |
  | other 870 (guard) | −0.07 | [−1.22, +1.03] | −0.11 |
  | their base stable-correct questions, 468 (seeds 0–1) | −0.21 | [−2.03, +1.60] | +0.00 |
  | Chemical Structures 31 (not trained, reported) | −4.52 | [−13.55, +3.87] | +1.94 |

  - Music per seed: base 40.0 / 33.3 / 30.0 / 30.0 / 46.7 (36.0), round 1 40.0 / 36.7 / 40.0 / 43.3 / 46.7 (41.3),
    round 2 36.7 / 46.7 / 33.3 / 33.3 / 36.7 (37.3).
  - Music truncation 49 → 32 → 25 %; accuracy of finished Music responses 46.1 → 47.1 → 42.5 %. The trained reading
    appears in 15 → 78 → 101 of 150 Music responses. Round 2 against the base: 19 responses gained, 17 lost.
  - Round 2 fixed `Music_28` (2 → 0 → 5 of 5) and kept `Music_15` (0 → 5 → 5), but lost what round 1 had gained on
    `Music_25` (2 → 5 → 1) and `Music_19` (0 → 3 → 0). Its readings of the scanned images are still often wrong, and
    it now also states key signatures that are not there (`Music_3`: "the key signature shows 1 sharp" for a sharp
    that belongs to the note; `Music_14`: both notes read as F).
  - Reading: two trainings teach the reading to 85–89 % on rendered excerpts in an unseen font, cost nothing
    measurable on the other 870 questions (−0.11, −0.07), and do not raise Music on MMMU (+5.3, +1.3, neither
    established, the second not better than the first). The skill does not carry from rendered excerpts to the
    scanned ones. More synthetic variety (round 2) did not close that gap.
  - By the plan stated to the user before these runs, the synthetic-reading line stops here: no chem or circuit
    generator is built on it. What comes next is the user's decision.
- Exploratory look after the result (user's question why the gain does not carry over; round 2, seed 0, my own
  comparison with the verified readings of step 0): in all 8 Music questions inspected (`Music_3, 8, 14, 17, 18, 22,
  25, 30`) the model's reading of the MMMU image is wrong in at least one fact that matters — a key signature
  stated where there is none (`_3`, `_30`), the wrong number of sharps (`_8`, `_22`), a note placed on the wrong
  line or ledger line (`_14`, `_18`, `_25`), the four clefs named in the wrong order (`_17`). Three of the eight
  answers are right anyway. So the cause is not the other subjects in the evaluation: on the scanned images the
  reading itself is still wrong. The reading gate (same renderer, unseen font) did not measure this, as its
  registered limit said.

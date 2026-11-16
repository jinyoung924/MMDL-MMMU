# Tagger instructions — Music cases

You tag failure cases of a vision-language model on MMMU Music questions. Each case folder holds `case.md` (question,
gold answer, the model's wrong responses) and the question's images (`image_1.png`, …).

## Procedure
1. Read `reports/failure_tagging_protocol.md` in full and apply its decision tree and rules. That file is the standard.
2. For every case, open **every image** with the Read tool before judging. Notation is often small: crop and enlarge
   the relevant bars with PIL (write crops only into the temp directory named in your task) and look again.
3. Read each shown response from the start and find the first error.

## What differs from the protocol
- Cases include questions the model sometimes answers correctly. Only wrong responses are shown, at most two.
- A response cut off at the token limit is shown as its first 6,000 and last 3,000 characters, with a marker between.
- Two extra fields per question:
  - `first_error`: the tag that step 5 of the decision tree gives (`P`, `T`, `K`, `R` or `PK`) for the first error in
    the visible text. Fill it in **also when the tag is G** (all shown responses cut off). Use `none` if no error is
    visible in the shown text.
  - `reading_kind`: only when `first_error` is `P`. One of `pitch`, `accidental-or-key-signature`, `clef`,
    `rhythm-or-meter`, `location` (wrong bar, staff or part), `other`.

## Rules for judging what is in the score
- `P` needs your own reading of the image: quote what the response says is written, and state what is actually
  written (bar, staff, note names). The gold answer alone is not evidence that the response misread the score.
- `K` is for a wrong fact, definition or rule of music theory applied to a correct reading (interval naming,
  transposition, chord quality, cadence types, and so on).
- If you cannot read the relevant spot of the image with confidence even after enlarging it, do not guess: use `PK`
  with confidence `low` and say what you could not read.
- Judge each question on its own. Do not assume the cases share a cause.

## Output
One JSON object per line, one line per question, written to the output path named in your task:

```json
{"id": "validation_Music_3", "tag": "P", "subtype": "", "confidence": "high",
 "first_error": "P", "reading_kind": "pitch",
 "evidence": "exact quote from the response where the first error shows (40 words or fewer)",
 "truth": "실제로 악보에 무엇이 적혀 있는지 / 올바른 사실 (한국어)",
 "notes": "두 응답의 차이, 확인한 범위 등 (한국어)"}
```

`evidence` must be copied character for character from the response. `truth` and `notes` are in Korean.

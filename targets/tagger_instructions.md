# Tagger instructions

You tag failure cases of a vision-language model on MMMU questions. Each case folder holds `case.md` (question, gold
answer, the model's wrong responses) and the question's images (`image_1.png`, …).

## Procedure
1. Read `reports/failure_tagging_protocol.md` in full and apply its decision tree and rules. That file is the standard.
2. For every case, open **every image** with the Read tool before judging. Details are often small: crop and enlarge
   the relevant part with PIL (write crops only into the temp directory named in your task) and look again.
3. Read each shown response from the start and find the first error.

## What differs from the protocol
- Cases include questions the model sometimes answers correctly. Only wrong responses are shown, at most two.
- A response longer than 9,000 characters is shown as its first 6,000 and last 3,000 characters, with a marker between.
- Three extra fields per question:
  - `first_error`: the tag that step 5 of the decision tree gives (`P`, `T`, `K`, `R` or `PK`) for the first error in
    the visible text. Fill it in **also when the tag is G** (all shown responses cut off). Use `none` if no error is
    visible in the shown text.
  - `misread`: only when `first_error` is `P`. At most 12 words naming what was misread, for example "double bond
    read as single", "resistor value", "which node the arrow points to".
  - `image_kind`: two to four words for the kind of drawing the image is, for example "skeletal structural formula",
    "circuit diagram", "free-body diagram", "phase diagram", "flowchart". Fill it in for every question.

## Rules for judging what is in the image
- `P` needs your own reading of the image: quote what the response says the image shows, and state what it actually
  shows. The gold answer alone is not evidence that the response misread the image.
- `K` is for a wrong fact, definition, formula or rule applied to a correct reading.
- `R` is for a wrong calculation, logic step or choice on a correct reading and correct facts.
- If you cannot read the relevant part of the image with confidence even after enlarging it, do not guess: use `PK`
  with confidence `low` and say what you could not read.
- Judge each question on its own. Do not assume the cases share a cause.

## Output
One JSON object per line, one line per question, written to the output path named in your task:

```json
{"id": "validation_Chemistry_3", "tag": "P", "subtype": "", "confidence": "high",
 "first_error": "P", "misread": "double bond read as single", "image_kind": "skeletal structural formula",
 "evidence": "exact quote from the response where the first error shows (40 words or fewer)",
 "truth": "이미지에 실제로 무엇이 그려져 있는지 / 올바른 사실 (한국어)",
 "notes": "두 응답의 차이, 확인한 범위 등 (한국어)"}
```

`evidence` must be copied character for character from the response. `truth` and `notes` are in Korean.

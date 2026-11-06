# V2 pre-training investigation

Branch: `solgyu-lee`.

Update 2026-10-30: the v2 four-arm SFT pilot has completed; no checkpoint passed its development
gate. The investigation text below preserves the earlier pre-training stage. Current work is
[stability-targeted recruitment](../stability_v1/README.md), with a separate prospective protocol.

The existing v1 models are audited with `../path_audit_v2.py`, `../precision_audit_v2.py`,
and `../backend_audit_v2.py`. The audit uses eight original training examples, never
MMMU examples. Greedy generation is limited to 512 tokens for this path comparison;
truncation is reported separately. An earlier 8192-token audit was interrupted and
its partial artifacts retained in `path_audit_interrupted_8192/`.

`diagnostic_annotations.json` contains 40 assistant-reviewed development examples.
They originate from the pinned BMMR training source but are **permanently excluded
from SFT**. Original source assistant answers were inspected only after writing
the annotations; disagreements and rechecks are recorded. There is no independent
human/second-model verification. These are a convenience sample selected by image
quality and skill relevance, not by base-model correctness.

`prepare_diagnostic.py` authenticates source rows, checks arithmetic, reserves related
candidate images/questions, and freezes checksums. `data.py` refuses a training role,
changed labels/images/manifests and source-split mismatches. `integrity_checks.json`
records five negative controls. `candidate_roles.jsonl` gives every pool item an
explicit development/reserved/unassigned role; **none is ready for training**.
The remaining train/development/confirmation split must be reviewed and frozen
before any SFT. Similar-image/text reservation is a heuristic, not semantic proof.

`run_diagnostic.py` evaluates the original input, visual facts, general knowledge,
both additions, and neutral length-control text. It uses the unchanged base model,
existing CoT instruction and generation parameters (8192 tokens, temperature .7,
top-p .8, top-k 20, presence penalty 1.5), with generation seeds 0/1/2. This separate
diagnostic uses the existing Answer-tag regex without random answer fallback and
must not be presented as an official MMMU score.

`summarize_diagnostic.py` checks all 600 outputs and computes paired confidence
intervals by resampling the 40 questions together across the three seeds.
Neither these examples nor their prompts/outputs may become training examples.

Completed 2026-10-29: all 600 responses passed the summary integrity checks.
Mean accuracy was 83.33% original, 94.17% visual facts, 83.33% general knowledge,
96.67% both, and 85.83% neutral control. These are information-intervention scores,
not SFT gains or official MMMU results. The train160/dev80/confirmation80 split
remains incomplete. See `diagnostic_summary.json` and
`../../reports/diagram_sft_v2_plan.md` for uncertainty, limitations and next steps.

Raw images, model responses and runtime artifacts are ignored by Git. Summaries,
annotation provenance, checksums and comparison code are retained for review.

# Stability-targeted SFT recruitment

Branch: `solgyu-lee`. Started 2026-10-30.

Current stage (2026-10-31): the separately registered development completion finished with exit0;
**A/B SFT and all development measurements finished; the registered development gates failed,
so this experiment is stopped**. Confirmation student inference and official MMMU evaluation
were not run.
Missing seeds2–4 for all74 eligible, source-valid development
candidates were completed, reusing existing0/1 responses (222 new responses; one pinned output directory).
See the [prospective extension](../../reports/stability_development_recruitment_extension_20261031.md)
and [immutable manifest](recruitment_extension_20261031/manifest.json).
The original failed [recruitment proposal](cohort_proposal_final_recruitment.json) is unchanged:
29 training weak,7 development weak (minimum12),13 observed5/5 development candidates.
The separate [source-metadata hold](../../reports/stability_source_metadata_amendment_20261031.md)
excludes TRAIN1368 symmetrically without altering its supported mathematical review or native stratum.
The [completed proposal](cohort_proposal_development_completion.json) has K28/N28,13 development
weak and68 observed5/5 candidates. The approved [cohort lock](cohort/dataset_lock.json) freezes
A28/B28 and development40 (12 weak/12 stable/16 remainder); train and development IDs/groups
are disjoint. Each arm uses seed0, one epoch,7 updates and only checkpoints4/7.
At fresh seed10, base has32/40 overall and6/12 weak; A7 has34/40 and8/12; B7 has33/40 and8/12.
Only step7 passes the registered B entry gate. The [selection receipt](runs/development_selection_seed10.json)
fixes A7/B7 for fresh seeds11/12. Those follow-up measurements are now complete. Across seeds10–12,
base/A7/B7 score21/36,24/36,18/36 on the fixed weak group and101/120,103/120,97/120 overall.
All three score36/36 on the stable group. B is below base on weak questions at both seeds11 and12;
four of the six registered operating criteria fail. The immutable
[aggregate](runs/development_aggregate.json) records `stopped_development_operating_gates_failed`,
with confirmation, official evaluation and checkpoint reselection all disallowed.
The weak-example strategy did not pass this experiment; A's higher point estimate is not independently
confirmed improvement. No further checkpoint was selected. Full details and limitations are in the
[review findings](../../reports/stability_review_findings.md).

A separate [TRAIN-only step diagnostic](../../reports/stability_step_diagnostic_results_20261031.md)
subsequently completed with the unchanged B7: the exposed28 questions across seeds0–4 score69/140
before and75/140 after; four become observed5/5 and one becomes0/5. Eight prospectively fixed
baseline-wrong pairs received visible-step review: two recover a verified final argument, one
recovers the answer letter with unresolved image grounding. These are in-sample diagnostics,
not new development/confirmation evidence. The original stop and all no-CONF/no-reselection
boundaries remain unchanged; no new SFT was run.

Final cohort freezing and SFT must authenticate both the semantic-protection and source-metadata receipts.
The audit and metadata gate are now implemented and verified. Native-image review found TRAIN1707 to be a rotated equivalent of
DEV780 despite different earlier image-hash groups; TRAIN1707 is held. See the
[registered protection amendment](../../reports/stability_semantic_protection_amendment_20261030.md).
This permits isolated CPU-only source-relation hashing for protection, including reserved IDs.
Target writers never receive confirmation contents. Student-model inference on confirmation
is forbidden in this stopped experiment because the final development operating gates failed. Machine protection retains
212 train/110 development/110 confirmation candidates; these are not SFT approvals.
The prospective experiment compares a same-stratum random training cohort with a verified 1–3/5
cohort. Both receive independently drafted and image/math-reviewed targets. The previous rationale
format comparison was changed before any new Geometry3K student outputs.

- Governing protocol: [registered sampling experiment](../../reports/stability_sampling_protocol_20261030.md).
- Diagnosis: [review findings](../../reports/stability_review_findings.md).
- Immutable candidate lock: [candidates/candidate_lock.json](candidates/candidate_lock.json).
- Source: pinned official InterGPS Geometry3K original **train** only; val/test are protection-only.
- Roles: 234 train candidates, 117 development candidates, 115 reserved confirmation candidates,
  assigned by conservative source group before student outcomes. These are recruitment counts,
  not approved training examples.
- Old train/development/confirmation roles and all evaluation-derived material remain protected.
  Candidate loaders refuse confirmation during this stage. Training is not possible from candidate
  readiness flags, which are all false.

## Initial screen

```bash
/home/leesg17/miniconda3/envs/vllm/bin/python -B \
  pilot_diagram/stability_v1/screen_candidates.py \
  --stage all --out pilot_diagram/stability_v1/runs/candidate_screen_batch01 \
  --check-only
```

Remove `--check-only` to execute the registered 64-train/40-development batch. Existing complete
seed files can be resumed only with identical configuration, code, model, source and input hashes.
The runner uses the native zero adapter and existing prompt/Answer-tag regex; missing tags are wrong,
with no random fallback in this recruitment screen. It runs seeds0,1 for all selected inputs, then
seeds2–4 only for mixed outcomes and the preregistered per-role homogeneous audit.

Runtime state is in `runs/<name>/status.json`, and complete immutable seed files have matching
`seed*.manifest.json` receipts. Source answers are provisional for recruitment; selected labels
must pass independent image/math review. Recruitment frequencies are neither post-SFT improvement
evidence nor unbiased population estimates.

CPU integrity checks cover frozen roles, original source members, native questions/choices,
protected groups, image bytes, zero adapter tensors, immutable resume and tamper rejection.
`check_reviews.py` separately audits the old train-only review evidence and normalizes final proof
validity separately from the strict whole-displayed-trace criterion.

`blind_*` and `*_review.json` artifacts contain assistant-authored draft/review work. They are
not human-gold labels, final cohorts, or automatically approved SFT data. A source defect or ambiguous
image is held; questions are not repaired into evaluation-derived training variants.

# Stage 9 — Expert-Label Calibration & Elliott Validation

## Run

    py -3 scripts\run_stage9_expert_validation.py

Outputs:
- `Modules/Elliott_Waves/Evaluation/stage9/stage9_validation.json`
- `Modules/Elliott_Waves/Evaluation/stage9/stage9_validation_report.md`

## Review workflow

1. Start the local review app: `py -3 scriptselliott_chart_lab.py`.
2. Open `http://127.0.0.1:8765` on the same computer.
3. Select a candidate, inspect its OHLC chart and Elliott structure, then record a verdict.
4. Each reviewer uses a stable, unique reviewer ID. Select `Expert reviewer (self-declared)` only if the reviewer genuinely has relevant Elliott Wave expertise; enter a meaningful qualification statement and confirm independent judgment.
5. A second distinct expert must review the same candidate independently. Disagreements remain excluded from consensus and must not be silently resolved.
6. Run Stage 9 again to audit the records and determine whether there is enough consensus data for a chronological calibration experiment.

The reviewer role and qualification are self-declared metadata. The project owner must verify reviewer credentials outside the software. A chart candidate has already been proposed by the AI; reviews are therefore expert audits of candidate hypotheses, not a fully blind independent discovery dataset.

## Eligibility and calibration gates

- Only records marked expert, with reviewer ID, qualification statement, independent-review confirmation, valid timestamp and candidate pivots are accepted.
- Two distinct reviewers must agree on accepted/rejected verdict for a candidate.
- `needs_correction` records require detailed notes and are not included in binary calibration.
- At least 100 consensus candidates and at least 30 accepted plus 30 rejected examples are required before calibration.
- When eligible, isotonic regression is fitted on the first 70% of chronologically ordered consensus examples and evaluated on the final 30%. Raw-score Brier, calibrated Brier, base-rate Brier and ROC AUC are reported.
- A better score does not automatically promote a model. A human governance review is still required.
- OCR, approximate chart mappings and unreviewed external references are never ground truth.

## Current status at Stage 9 launch

The existing `reviewed_labels.jsonl` file did not exist, so there are no expert reviews yet. The 16 collected images and four approximate chart mappings are not a substitute: the current mappings include large price-to-candle discrepancies and remain explicitly non-training-eligible.

Stage 9 does not change Stage 1 thresholds, Stage 3 models, Stage 5 walk-forward outputs, Stage 7 forecasts, or Stage 8 results.

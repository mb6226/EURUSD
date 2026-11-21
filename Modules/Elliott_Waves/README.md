# Elliott Wave Intelligence Module

## Stage 1 — Elliott Intelligence Core

The first-stage engine is a research baseline that:

- extracts confirmed ZigZag / directional-change pivots from OHLC candles;
- can expose the current unfinished swing as a provisional pivot;
- scans rolling pivot windows for five-leg impulse hypotheses;
- scans three-leg A-B-C correction hypotheses and marks possible flat-like structures;
- checks basic hard Elliott constraints and ranks candidates with transparent heuristic reasons;
- keeps competing hypotheses instead of forcing one count.

### Run

From the project root in PowerShell:

```powershell
py -3 scripts\run_elliott_stage1.py

eurusd-ai analyze-elliott data\eurusd-15min-bid-2025-11-20-2026-11-20.csv --min-leg-pips 15 --top 25 --output Modules\Elliott_Waves\Evaluation\m15_candidates.json
py -3 -m pytest -q
```

The multi-timeframe runner writes JSON reports under `Evaluation\stage1\` for M5, M15, H1, H4 and D1. Initial pivot thresholds are configurable in `scripts/run_elliott_stage1.py`.

### Important limitations

- The score is a heuristic ranking, not a calibrated probability.
- The current engine implements basic impulse and ABC correction hypotheses only. Diagonals, triangles, complex corrections, alternation, channeling, degree nesting and context-aware alternates remain future work.
- The pivot threshold changes the swing structure. Counts must be compared across multiple thresholds / degrees.
- A confirmed pivot is only known after the reversal threshold has occurred. The latest provisional pivot can change as new candles arrive.
- The source M1 feed excludes flat candles; resampled bars inherit this property and some buckets may be partial.
- Nothing here should be treated as a trading signal until independently labelled and tested out of sample.


## Stage 2 — Dataset & Chart Lab

A local human-review chart lab is available through `py -3 scripts/elliott_chart_lab.py`. It displays recent EURUSD OHLC candles for M5/M15/H1/H4/D1, overlays Stage 1 pivots and candidate counts, and stores explicit human reviews in `Modules/Elliott_Waves/Dataset/reviewed_labels.jsonl`. See `Modules/Elliott_Waves/Dataset/README.md` for the review workflow and dataset policy. Candidate scores remain heuristic rankings, not probabilities or ground-truth labels.


## Stage 3 — Local Research Collector

A separate manual-run collector scans configured public EURUSD Elliott Wave research listing pages and stores deduplicated references in `Dataset/external_references/collected_analyses.jsonl`. Run `py -3 scripts/run_elliott_research_collector.py` once when desired. It is local-only, does not schedule itself or upload data, and stores metadata plus short descriptions rather than full articles or chart images. Imported references remain unreviewed and are never automatically treated as training labels. See `Research_Collector/README.md`.


## Stage 4 — Chart Image Extraction & OCR

The local Research Collector now extracts chart image references from article Open Graph/Twitter metadata and image tags, downloads only configured public image hosts, and stores image/OCR records separately from article references. Chart images are saved in `Dataset/external_references/chart_images/`; structured OCR detections are appended to `Dataset/external_references/chart_image_extractions.jsonl`. Detected labels retain confidence and normalized image coordinates; a first-pass price-axis calibration is attempted from right-side EURUSD price ticks. No OCR output is considered ground truth, and every image remains `needs_visual_review` / `training_eligible=false`. See `Research_Collector/README.md`.

## Stage 8 — Nested Walk-Forward Parameter Optimization

Run the research-only parameter search with:

    py -3 scripts\run_stage8_parameter_optimization.py

Outputs are written to Evaluation\stage8\stage8_parameter_optimization.json and
Evaluation\stage8\stage8_parameter_optimization.md. The experiment uses three
expanding chronological outer folds; each fold selects parameters on an inner
validation segment and evaluates them on the next outer segment. It searches
pivot/minimum-leg threshold, minimum candidate score, Wave-2 retracement soft
threshold, and ABC-B retracement threshold. Retracement is measured from observed
wave lengths; no fixed Fibonacci levels are imposed.

The objective is a training-referenced structural-stability proxy (pivot density,
candidate density, hard-rule validity, mean heuristic score, and Wave-2 retracement
distribution). It is not independent expert ground truth, forecast accuracy, or
profitability. Current Stage 8 results are diagnostic only: parameter selections
are not consistently better on outer tests, and no settings are promoted into the
Stage 1 defaults. Expert-reviewed chart labels and a prospective holdout are
required before promotion.

## Stage 9 — Expert-label calibration and validation

Run `py -3 scripts\run_stage9_expert_validation.py` to audit expert reviews, require agreement from two distinct reviewers, and perform chronological score calibration only after minimum sample gates are met. The local Chart Lab at `http://127.0.0.1:8765` now records reviewer ID, self-declared role, qualification statement and independent-review confirmation. Self-declared credentials are not verified automatically. OCR and approximate chart mappings are never ground truth. See `Modules\Elliott_Waves\Dataset\STAGE9_EXPERT_REVIEW.md`.


## Research-engine integration

The Detection package now includes an independent ATR-reversal pivot detector and raw wave-structure measurement API:

- `detect_atr_pivots(candles, atr_period=14, atr_multiplier=1.5, min_bars=2)` provides an alternative to fixed-pip directional-change pivots.
- `wilder_atr(candles, period=14)` exposes the causal ATR series used by that detector.
- `measure_wave_structure(pivots)` reports impulse / ABC leg sizes, actual retracement and extension ratios, durations, and hard-rule diagnostics without forcing Fibonacci cutoffs.

These are research alternatives, not replacements for the existing Stage-1 engine. See `Detection/RESEARCH_INTEGRATION.md` for the third-party audit and licensing decisions. Run `py -3 -m pytest -q` before using the branch.

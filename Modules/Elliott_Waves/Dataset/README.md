# Elliott Wave Learning Dataset (Stage 2)

## Build the automated five-year dataset
From the project root:
```powershell
py -3 scripts\build_elliott_learning_dataset.py
py -3 scripts\verify_elliott_learning_dataset.py
py -3 -m pytest -q
```

The builder reads the validated shared five-year EURUSD BID data and writes outputs to `Modules/Elliott_Waves/Dataset/generated/`:
- `causal_swings.jsonl`: confirmed directional-change swings, wave size, duration, and actual retracement relative to the preceding swing.
- `weak_structure_labels.jsonl`: overlapping impulse / ABC-style structural hypotheses, rule reasons, heuristic scores, and explicit eligibility flags.
- `multitimeframe_asof_events.jsonl`: swing and structure events with latest available swing context from each timeframe.
- `dataset_manifest.json`: source, per-timeframe counts, label policy, and causality policy.

## Causality and label quality
- Each pivot stores its extreme time separately from its confirmation time. Confirmation availability is set to the close of the candle that confirms the reversal (M5/M15/H1/H4/D1 bucket duration).
- Provisional pivots are excluded from the learning dataset.
- Multi-timeframe context is an as-of join: every context swing must have `available_at <= event_time`. The verification script checks this invariant across every generated event.
- Structure labels are weak rule-engine hypotheses, not expert-confirmed Elliott counts and not calibrated probabilities. `training_eligible` is a filter for research experiments, not a guarantee of correctness.
- Ambiguous or invalid candidates remain traceable with rule reasons; manual chart review is optional and is not required to build the dataset.

## Optional Chart Lab
```powershell
py -3 scripts\elliott_chart_lab.py
```
Open http://127.0.0.1:8765. Keep the local server bound to 127.0.0.1; do not expose it publicly.

## Current scope
The automated label engine currently covers basic impulse and ABC / zigzag / possible-flat hypotheses. Diagonals, triangles, complex combinations, degree nesting, calibrated confidence, and independently validated ground truth are future work. Do not train a production forecaster by treating heuristic labels as unquestioned truth.

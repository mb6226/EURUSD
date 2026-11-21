"""Recompute Stage-5 diagnostics and attach causal Stage-4 context to saved forecasts."""
import json
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support, mean_absolute_error

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Modules/Elliott_Waves/Evaluation/stage5"
PRED = OUT / "daily_walk_forward_predictions.jsonl"
STAGE4 = ROOT / "Modules/Elliott_Waves/Evaluation/stage4/multitimeframe_scenarios.jsonl"


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main():
    predictions = [json.loads(x) for x in PRED.read_text(encoding="utf-8").splitlines() if x.strip()]
    snapshots = []
    with STAGE4.open(encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            snapshots.append((dt(x["as_of"]), x))
    snapshots.sort(key=lambda x: x[0])
    times = [x[0] for x in snapshots]
    for p in predictions:
        cutoff = dt(p["forecast_cutoff_ny"])
        i = bisect_right(times, cutoff) - 1
        snap = snapshots[i][1] if i >= 0 and (cutoff-times[i]).total_seconds() <= 48*3600 else None
        p["stage4_context"] = {
            "snapshot_available": bool(snap),
            "snapshot_as_of": snap.get("as_of") if snap else None,
            "timeframes_represented": snap.get("timeframes_represented", 0) if snap else 0,
            "abstain": snap.get("abstain", True) if snap else True,
            "conflicts": snap.get("conflicts", []) if snap else [],
            "scenarios": snap.get("scenarios", []) if snap else [],
            "timeframe_leaders": snap.get("timeframe_leaders", {}) if snap else {},
            "score_semantics": "heuristic ranking, not probability",
        }
    PRED.write_text("".join(json.dumps(x, ensure_ascii=False)+"\n" for x in predictions), encoding="utf-8")
    evaluated = [x for x in predictions if "actual" in x]
    y = [x["actual"]["direction"] for x in evaluated]
    pred = [x["classifier_direction"] for x in evaluated]
    labels = ["DOWN", "FLAT", "UP"]
    precision, recall, f1, support = precision_recall_fscore_support(y, pred, labels=labels, zero_division=0)
    published = [x for x in evaluated if x["direction"] != "CONFLICT"]
    close_true = [x["actual"]["close_return_pips"] for x in evaluated]
    close_pred = [x["predicted_close_return_pips"] for x in evaluated]
    high_true = [x["actual"]["high_excursion_pips"] for x in evaluated]
    high_pred = [x["predicted_high_excursion_pips"] for x in evaluated]
    low_true = [x["actual"]["low_excursion_pips"] for x in evaluated]
    low_pred = [x["predicted_low_excursion_pips"] for x in evaluated]
    old_path = OUT / "walk_forward_metrics.json"
    metrics = json.loads(old_path.read_text(encoding="utf-8"))
    metrics.update({
        "method": "five_year_expanding_window_walk_forward_with_stage4_context",
        "retrain_every_sessions": 5,
        "direction_accuracy": float(np.mean(np.array(y) == np.array(pred))),
        "direction_baseline_accuracy": float(max(y.count(c)/len(y) for c in set(y))),
        "direction_balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "direction_macro_f1": float(f1_score(y, pred, labels=labels, average="macro", zero_division=0)),
        "direction_confusion_matrix_labels_down_flat_up": confusion_matrix(y, pred, labels=labels).tolist(),
        "per_class_metrics_down_flat_up": {
            label: {"precision": float(precision[i]), "recall": float(recall[i]),
                    "f1": float(f1[i]), "support": int(support[i])}
            for i, label in enumerate(labels)
        },
        "published_forecast_coverage_excluding_conflict": len(published)/len(evaluated),
        "published_direction_accuracy_when_not_conflict": float(np.mean([
            x["classifier_direction"] == x["actual"]["direction"] for x in published
        ])) if published else None,
        "published_conflict_count": sum(x["direction"] == "CONFLICT" for x in evaluated),
        "stage4_snapshot_coverage": float(np.mean([x["stage4_context"]["snapshot_available"] for x in predictions])),
        "stage4_context_attached_to_forecasts": True,
        "regression_mae_pips": {
            "close_return": float(mean_absolute_error(close_true, close_pred)),
            "high_excursion": float(mean_absolute_error(high_true, high_pred)),
            "low_excursion": float(mean_absolute_error(low_true, low_pred)),
        },
        "limitations": [
            "Five years of daily sessions provide more evidence than the one-year baseline but still only about 1,120 evaluated, serially dependent forecasts.",
            "Classifier vote shares are not calibrated probabilities.",
            "Stage-4 structures and rankings are weak-rule hypotheses, not expert-confirmed Elliott counts.",
            "The current Elliott engine supports basic impulse/ABC heuristics, not complete Elliott theory.",
            "This is a forecasting research model, not a trading recommendation.",
        ],
    })
    old_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    report = f"""# EURUSD Stage 5 — Five-Year Daily Walk-Forward

- NY cutoff: 17:00 America/New_York (DST-aware)
- Sessions available: {metrics['sessions_available']}
- Warm-up: {metrics['warmup_sessions']} sessions
- Forecasts: {metrics['forecast_count']}
- Evaluated forecasts: {metrics['evaluated_forecasts']}
- Retraining cadence: every {metrics['retrain_every_sessions']} sessions
- Feature count: {len(metrics['feature_names'])}
- Stage-4 snapshot coverage: {metrics['stage4_snapshot_coverage']:.1%}

## Direction diagnostics

- Classifier accuracy: {metrics['direction_accuracy']:.3%}
- Majority-class baseline: {metrics['direction_baseline_accuracy']:.3%}
- Balanced accuracy: {metrics['direction_balanced_accuracy']:.3%}
- Macro F1: {metrics['direction_macro_f1']:.3%}
- Non-conflict published forecast coverage: {metrics['published_forecast_coverage_excluding_conflict']:.1%}
- Accuracy on non-conflict forecasts: {metrics['published_direction_accuracy_when_not_conflict']:.3%}
- Conflict/abstention count: {metrics['published_conflict_count']}

Confusion matrix order: DOWN, FLAT, UP.

{metrics['direction_confusion_matrix_labels_down_flat_up']}

## Regression diagnostics (MAE, pips)

- Close return: {metrics['regression_mae_pips']['close_return']:.2f}
- High excursion: {metrics['regression_mae_pips']['high_excursion']:.2f}
- Low excursion: {metrics['regression_mae_pips']['low_excursion']:.2f}

## Interpretation

This is a chronological expanding-window simulation. At each 17:00 New York cutoff, features use only fully closed bars and the latest Stage-4 snapshot whose timestamp is no later than the cutoff. Model updates occur every five sessions; training labels are only used after their target session has completed.

The classifier's direction accuracy must be compared with the majority baseline and class balance. Vote shares are not calibrated probabilities. Stage-4 scores are heuristic rankings, not probabilities. The result is research evidence, not proof of Elliott-wave forecasting skill or trading profitability.
"""
    (OUT / "walk_forward_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({k:v for k,v in metrics.items() if k not in ("feature_names","per_class_metrics_down_flat_up")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

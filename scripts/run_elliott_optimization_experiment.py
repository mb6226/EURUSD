"""Controlled, causal feature-ablation experiment for Elliott walk-forward research."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from eurusd_ai.data_catalog import PROJECT_ROOT, EURUSD_TIMEFRAMES
from eurusd_ai.market_data import load_ohlcv_csv
from Modules.Elliott_Waves.Training.walk_forward import (
    TIMEFRAMES, build_feature_rows, build_labels, add_stage4_reasoning_features,
)

OUT = PROJECT_ROOT / "Modules/Elliott_Waves/Evaluation/optimization"
MIN_TRAIN = 180
REFIT_EVERY = 5
SEED = 20261121
CLASSES = ["DOWN", "FLAT", "UP"]

def groups(names):
    all_names = set(names)
    stage4 = {x for x in names if x.startswith("stage4_")}
    ell_terms = ("pivot_count", "last_swing_", "impulse_score", "abc_score", "hard_valid_count")
    ell = {x for x in names if any(t in x for t in ell_terms)}
    technical = all_names - ell - stage4
    macro = {x for x in names if x.startswith(("d1_", "h4_", "h1_"))} | stage4
    return {
        "full_all_timeframes": all_names,
        "without_stage4_context": all_names - stage4,
        "elliott_structure_plus_stage4": ell | stage4,
        "macro_D1_H4_H1_plus_stage4": macro,
        "technical_only_no_elliott_no_stage4": technical,
    }

def main():
    print("Loading canonical timeframe data...", flush=True)
    data = {tf: load_ohlcv_csv(EURUSD_TIMEFRAMES[tf]) for tf in TIMEFRAMES}
    print("Building causal features once...", flush=True)
    features, cutoffs = build_feature_rows(data)
    stage4_path = PROJECT_ROOT / "Modules/Elliott_Waves/Evaluation/stage4/multitimeframe_scenarios.jsonl"
    add_stage4_reasoning_features(features, cutoffs, stage4_path)
    labels = build_labels(data, cutoffs)
    names = sorted(features[0])
    variants = groups(names)
    usable = [i for i, x in enumerate(labels) if x is not None]
    results, all_preds = [], []
    for variant, selected in variants.items():
        cols = sorted(selected)
        print(f"Variant {variant}: {len(cols)} features", flush=True)
        y_true, y_pred = [], []
        pred_rows = []
        latest = None
        for i in range(len(cutoffs)):
            if labels[i] is None or i < MIN_TRAIN:
                continue
            train_idx = [j for j in range(i) if labels[j] is not None]
            if len(train_idx) < MIN_TRAIN:
                continue
            if latest is None or i % REFIT_EVERY == 0:
                X = np.asarray([[features[j][k] for k in cols] for j in train_idx], dtype=float)
                y = np.asarray([labels[j]["direction"] for j in train_idx])
                latest = RandomForestClassifier(
                    n_estimators=64, max_depth=5, min_samples_leaf=5,
                    max_features="sqrt", class_weight="balanced_subsample",
                    random_state=SEED, n_jobs=-1,
                ).fit(X, y)
            xnow = np.asarray([[features[i][k] for k in cols]], dtype=float)
            pred = str(latest.predict(xnow)[0])
            actual = labels[i]["direction"]
            y_true.append(actual); y_pred.append(pred)
            rec = {"variant": variant, "cutoff": cutoffs[i].isoformat(),
                   "prediction": pred, "actual": actual, "correct": pred == actual}
            pred_rows.append(rec); all_preds.append(rec)
        acc = float(accuracy_score(y_true, y_pred))
        results.append({
            "variant": variant, "feature_count": len(cols), "n": len(y_true),
            "accuracy": acc,
            "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
            "macro_f1": float(f1_score(y_true, y_pred, labels=CLASSES, average="macro", zero_division=0)),
            "predicted_class_counts": {c: y_pred.count(c) for c in CLASSES},
            "true_class_counts": {c: y_true.count(c) for c in CLASSES},
        })
        print(json.dumps(results[-1]), flush=True)
    # Causal baselines on exactly the same evaluated cutoffs.
    eval_idx = [i for i in range(len(cutoffs)) if labels[i] is not None and i >= MIN_TRAIN]
    for name in ("expanding_majority", "previous_session_persistence"):
        yt, yp = [], []
        for i in eval_idx:
            past = [labels[j]["direction"] for j in range(i) if labels[j] is not None]
            if name == "expanding_majority":
                counts = {c: past.count(c) for c in CLASSES}
                pred = max(CLASSES, key=lambda c: (counts[c], -CLASSES.index(c)))
            else:
                pred = past[-1]
            yt.append(labels[i]["direction"]); yp.append(pred)
        results.append({
            "variant": name, "feature_count": 0, "n": len(yt),
            "accuracy": float(accuracy_score(yt, yp)),
            "balanced_accuracy": float(balanced_accuracy_score(yt, yp)),
            "macro_f1": float(f1_score(yt, yp, labels=CLASSES, average="macro", zero_division=0)),
        })
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment": "causal_feature_ablation_v1",
        "data_rows": {tf: len(data[tf]) for tf in TIMEFRAMES},
        "sessions": len(cutoffs), "evaluated_samples": len(eval_idx),
        "warmup_sessions": MIN_TRAIN, "refit_every_sessions": REFIT_EVERY,
        "model": "RandomForest 64 trees, depth 5, min leaf 5, sqrt features, balanced_subsample",
        "target": "next completed NY session close direction; +/-5 pip deadband",
        "results": results,
        "warning": "Historical ablation on previously inspected data is diagnostic, not an untouched holdout or proof of edge. All features are causally cutoff-filtered; candidate selection requires a fresh prospective period.",
    }
    (OUT / "feature_ablation_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (OUT / "feature_ablation_predictions.jsonl").open("w", encoding="utf-8") as f:
        for row in all_preds: f.write(json.dumps(row) + "\n")
    print("SAVED", OUT, flush=True)

if __name__ == "__main__":
    main()

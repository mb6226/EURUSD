"""Train an Elliott morphology model from chronological weak labels.

Weak rule-engine labels are training hypotheses, not verified Elliott ground truth.
All transforms are fitted on the training period only; the final period is held out.
"""
from __future__ import annotations
import json, math, sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
DATA = ROOT / "Modules" / "Elliott_Waves" / "Dataset" / "generated" / "weak_structure_labels.jsonl"
OUT = ROOT / "Modules" / "Elliott_Waves" / "Training" / "stage3"
MODEL = ROOT / "Modules" / "Elliott_Waves" / "Models" / "elliott_structure_model.joblib"
PIP = 0.0001
TF_CODE = {"M5": 1, "M15": 2, "H1": 3, "H4": 4, "D1": 5}
FEATURE_NAMES = (
    "timeframe_code", "direction_sign", "leg_count", "log_total_pips",
    "net_to_path_efficiency", "log_total_duration_hours",
    "leg1_log", "leg2_log", "leg3_log", "leg4_log", "leg5_log",
    "leg1_share", "leg2_share", "leg3_share", "leg4_share", "leg5_share",
    "ratio_2_1", "ratio_3_2", "ratio_4_3", "ratio_5_4",
    "motive_3_vs_1", "corrective_2_vs_1", "corrective_4_vs_3",
    "duration1_log", "duration2_log", "duration3_log", "duration4_log", "duration5_log",
    "duration1_share", "duration2_share", "duration3_share", "duration4_share", "duration5_share",
)

def epoch(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()

def make_features(row: dict) -> list[float]:
    legs = [max(0.0, float(x)) for x in row["leg_lengths_pips"]]
    n = len(legs)
    total = sum(legs)
    times = [epoch(x) for x in row["pivot_extreme_times"]]
    durations = [max(0.0, times[i+1] - times[i]) / 3600.0 for i in range(n)]
    duration_total = sum(durations)
    direction = 1.0 if row["direction"] == "up" else -1.0
    net = abs(legs[0] - legs[1] + sum(legs[2::2]) - sum(legs[3::2]))
    def ratio(a, b):
        return a / b if b > 1e-9 else 0.0
    def share(a, b):
        return a / b if b > 1e-9 else 0.0
    padded_legs = (legs + [0.0] * 5)[:5]
    padded_durs = (durations + [0.0] * 5)[:5]
    vals = [
        float(TF_CODE[row["timeframe"]]), direction, float(n),
        math.log1p(total), ratio(net, total), math.log1p(duration_total),
    ]
    vals += [math.log1p(x) for x in padded_legs]
    vals += [share(x, total) for x in padded_legs]
    vals += [ratio(legs[i], legs[i-1]) if i < n else 0.0 for i in range(1, 5)]
    vals += [ratio(legs[2], legs[0]) if n >= 5 else 0.0,
             ratio(legs[1], legs[0]) if n >= 3 else 0.0,
             ratio(legs[3], legs[2]) if n >= 5 else 0.0]
    vals += [math.log1p(x) for x in padded_durs]
    vals += [share(x, duration_total) for x in padded_durs]
    assert len(vals) == len(FEATURE_NAMES), (len(vals), len(FEATURE_NAMES))
    return vals

def main():
    try:
        import numpy as np
        import joblib
        from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.decomposition import PCA
        from sklearn.cluster import MiniBatchKMeans
        from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, classification_report, confusion_matrix
    except ImportError as exc:
        raise SystemExit("Install ML dependencies with: py -3 -m pip install -e .[ml]") from exc

    rows = []
    with DATA.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("training_eligible") and r.get("hard_valid"):
                rows.append(r)
    rows.sort(key=lambda r: epoch(r["available_at"]))
    if len(rows) < 500:
        raise RuntimeError(f"Not enough eligible weak labels: {len(rows)}")

    X = np.asarray([make_features(r) for r in rows], dtype=np.float32)
    y = np.asarray([r["pattern"] for r in rows])
    times = np.asarray([epoch(r["available_at"]) for r in rows])
    # Strict chronological 70/15/15 split with a one-day purge at both boundaries.
    t70, t85 = np.quantile(times, [0.70, 0.85])
    purge = 24 * 3600
    train_idx = np.where(times < t70 - purge)[0]
    val_idx = np.where((times >= t70 + purge) & (times < t85 - purge))[0]
    test_idx = np.where(times >= t85 + purge)[0]
    if min(len(train_idx), len(val_idx), len(test_idx)) < 100:
        raise RuntimeError("Chronological split too small after purge; inspect date coverage.")
    classes = sorted(set(y[train_idx]))
    keep_train = np.isin(y[train_idx], classes)
    train_idx = train_idx[keep_train]
    val_idx = val_idx[np.isin(y[val_idx], classes)]
    test_idx = test_idx[np.isin(y[test_idx], classes)]

    # Unsupervised morphology representation; fit only on training examples.
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X[train_idx])
    pca = PCA(n_components=min(8, X_train_scaled.shape[1]), random_state=42)
    Z_train = pca.fit_transform(X_train_scaled)
    kmeans = MiniBatchKMeans(n_clusters=8, random_state=42, batch_size=1024, n_init=5)
    kmeans.fit(Z_train)

    model = RandomForestClassifier(
        n_estimators=300, max_depth=16, min_samples_leaf=4,
        class_weight="balanced_subsample", n_jobs=-1, random_state=42
    )
    weights = np.asarray([max(0.5, min(1.0, float(rows[i]["heuristic_score"]) / 100.0)) for i in train_idx])
    model.fit(X[train_idx], y[train_idx], sample_weight=weights)

    def eval_split(idx):
        pred = model.predict(X[idx])
        probs = model.predict_proba(X[idx])
        confidence = probs.max(axis=1)
        accepted = confidence >= 0.55
        return pred, probs, confidence, accepted

    val_pred = model.predict(X[val_idx])
    pred, probs, confidence, accepted = eval_split(test_idx)
    y_test = y[test_idx]
    train_majority_share = Counter(y[train_idx]).most_common(1)[0][1] / len(train_idx)
    labels = list(model.classes_)
    metrics = {
        "stage": "Stage 3 Elliott AI Trainer",
        "label_semantics": "weak_rule_engine_hypotheses_not_expert_ground_truth",
        "split": {"train": len(train_idx), "validation": len(val_idx), "test": len(test_idx),
                  "train_end_utc": datetime.fromtimestamp(float(times[train_idx].max())).isoformat() + "Z",
                  "test_start_utc": datetime.fromtimestamp(float(times[test_idx].min())).isoformat() + "Z",
                  "purge_hours": 24},
        "class_distribution_train": dict(Counter(y[train_idx])),
        "class_distribution_test": dict(Counter(y_test)),
        "weak_label_validation_agreement": {"accuracy": float(accuracy_score(y[val_idx], val_pred)), "balanced_accuracy": float(balanced_accuracy_score(y[val_idx], val_pred)), "macro_f1": float(f1_score(y[val_idx], val_pred, average="macro", zero_division=0))},
        "weak_label_test_agreement": {
            "accuracy": float(accuracy_score(y_test, pred)),
            "balanced_accuracy": float(balanced_accuracy_score(y_test, pred)),
            "macro_f1": float(f1_score(y_test, pred, average="macro", zero_division=0)),
            "majority_class_baseline": float(train_majority_share),
            "abstention_threshold": 0.55,
            "coverage": float(accepted.mean()),
            "accuracy_when_not_abstaining": float(accuracy_score(y_test[accepted], pred[accepted])) if accepted.any() else None,
            "confusion_matrix_labels": labels,
            "confusion_matrix": confusion_matrix(y_test, pred, labels=labels).tolist(),
            "classification_report": classification_report(y_test, pred, labels=labels, output_dict=True, zero_division=0),
        },
        "unsupervised_representation": {
            "method": "StandardScaler + PCA + MiniBatchKMeans",
            "latent_dimensions": int(pca.n_components_),
            "explained_variance_ratio_sum": float(pca.explained_variance_ratio_.sum()),
            "clusters": int(kmeans.n_clusters),
            "fit_scope": "training_period_only",
        },
        "features": list(FEATURE_NAMES),
        "warning": "Metrics measure agreement with weak rule-engine labels only. They do not establish Elliott expert accuracy, predictive edge, or trading profitability."
    }

    OUT.mkdir(parents=True, exist_ok=True)
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model, "scaler": scaler, "pca": pca, "kmeans": kmeans,
        "feature_names": list(FEATURE_NAMES), "classes": labels,
        "abstention_threshold": 0.55, "label_semantics": metrics["label_semantics"],
        "train_end_epoch": float(times[train_idx].max()),
    }
    joblib.dump(bundle, MODEL)
    (OUT / "training_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    with (OUT / "heldout_predictions.jsonl").open("w", encoding="utf-8") as f:
        for j, idx in enumerate(test_idx):
            row = rows[idx]
            latent = pca.transform(scaler.transform(X[idx:idx+1]))[0]
            cluster = int(kmeans.predict(latent.reshape(1, -1))[0])
            record = {
                "available_at": row["available_at"], "timeframe": row["timeframe"],
                "weak_label": str(y_test[j]), "model_prediction": str(pred[j]),
                "weak_label_agreement": bool(pred[j] == y_test[j]),
                "model_score_not_calibrated_probability": float(confidence[j]),
                "abstain": bool(not accepted[j]), "morphology_cluster": cluster,
                "latent_embedding": [round(float(v), 6) for v in latent],
            }
            f.write(json.dumps(record, separators=(",", ":")) + "\n")

    print("TRAIN_ROWS", len(train_idx), "VALIDATION_ROWS", len(val_idx), "TEST_ROWS", len(test_idx), flush=True)
    print("CLASSES", labels, flush=True)
    print("WEAK_LABEL_TEST_AGREEMENT", json.dumps(metrics["weak_label_test_agreement"], indent=2), flush=True)
    print("PCA_VARIANCE", metrics["unsupervised_representation"]["explained_variance_ratio_sum"], flush=True)
    print("MODEL", MODEL, flush=True)
    print("OUTPUT", OUT, flush=True)

if __name__ == "__main__":
    main()




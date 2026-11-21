"""Train a classifier from independently reviewed, labelled candidate features."""
from __future__ import annotations
import argparse, csv
from pathlib import Path
from ..Detection.features import FEATURE_NAMES

def train(labels_csv: str, model_path: str) -> None:
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report
        import joblib
    except ImportError as exc:
        raise SystemExit("ML dependencies missing. Run: pip install -e .[ml]") from exc
    X, y = [], []
    with Path(labels_csv).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = set(FEATURE_NAMES) | {"label"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Label CSV missing columns: {', '.join(sorted(missing))}")
        for row in reader:
            X.append([float(row[k]) for k in FEATURE_NAMES])
            y.append(row["label"].strip())
    if len(X) < 30 or len(set(y)) < 2:
        raise ValueError("Need at least 30 reviewed examples and at least 2 label classes")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    model = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=42, min_samples_leaf=2)
    model.fit(X_train, y_train)
    print(classification_report(y_test, model.predict(X_test), zero_division=0))
    out = Path(model_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "feature_names": list(FEATURE_NAMES)}, out)
    print(f"Saved model: {out.resolve()}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("labels_csv")
    p.add_argument("--model-path", default="Modules/Elliott_Waves/Models/elliott_wave_model.joblib")
    a = p.parse_args()
    train(a.labels_csv, a.model_path)

if __name__ == "__main__": main()

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from scripts.stage6_evaluate_and_govern import (
    causal_baselines,
    evaluate,
    load_predictions,
    metrics,
    run,
)


def _rows(labels, predictions=None, conflicts=None):
    predictions = predictions or labels
    conflicts = conflicts or [False] * len(labels)
    rows = []
    for i, (actual, pred, conflict) in enumerate(zip(labels, predictions, conflicts)):
        rows.append({
            "forecast_cutoff_ny": (datetime(2026, 1, 1, 22, tzinfo=timezone.utc) + timedelta(days=i)).isoformat(),
            "classifier_direction": pred,
            "direction": "CONFLICT" if conflict else pred,
            "actual": {"direction": actual},
        })
    return rows


def test_causal_baselines_use_only_previous_actuals():
    rows = _rows(["UP", "DOWN", "DOWN", "FLAT"])
    majority, persistence, indices = causal_baselines(rows)
    assert indices == [1, 2, 3]
    assert majority == ["UP", "DOWN", "DOWN"]
    assert persistence == ["UP", "DOWN", "DOWN"]


def test_metrics_confusion_matrix_and_class_support():
    result = metrics(["DOWN", "UP", "UP"], ["DOWN", "DOWN", "UP"])
    assert result["n"] == 3
    assert result["confusion_matrix"] == [[1, 0, 0], [0, 0, 0], [1, 0, 1]]
    assert result["per_class"]["FLAT"]["support"] == 0


def test_promotion_gate_rejects_weak_candidate():
    labels = (["DOWN"] * 30) + (["UP"] * 30) + (["FLAT"] * 10)
    predictions = ["DOWN"] * len(labels)
    report = evaluate(_rows(labels, predictions), min_evaluated=20, bootstrap_samples=100)
    assert report["promotion_gate"]["decision"] == "REJECT_PROMOTION_KEEP_INCUMBENT"
    assert report["promotion_gate"]["promote_candidate"] is False


def test_perfect_candidate_still_needs_minimum_sample():
    labels = (["DOWN", "UP", "FLAT"] * 20)
    report = evaluate(_rows(labels, labels), min_evaluated=100, bootstrap_samples=100)
    assert report["evaluation"]["model"]["accuracy"] == 1.0
    assert report["promotion_gate"]["enough_evidence"] is False
    assert report["promotion_gate"]["promote_candidate"] is False


def test_conflict_abstentions_do_not_change_classifier_metrics():
    labels = ["DOWN", "UP", "FLAT", "DOWN", "UP", "FLAT"]
    flags = [False, True, False, False, True, False]
    report = evaluate(_rows(labels, labels, flags), min_evaluated=2, bootstrap_samples=50)
    assert report["evaluation"]["model"]["accuracy"] == 1.0
    assert report["evaluation"]["published_non_conflict_coverage"] < 1.0
    assert report["evaluation"]["published_non_conflict"]["accuracy"] == 1.0


def test_load_predictions_rejects_duplicate_cutoffs(tmp_path):
    path = tmp_path / "predictions.jsonl"
    row = _rows(["UP"])[0]
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_predictions(path)


def test_stage6_run_writes_audit_and_registry_without_promoting(tmp_path, monkeypatch):
    import scripts.stage6_evaluate_and_govern as stage6
    labels = (["DOWN"] * 20) + (["UP"] * 20) + (["FLAT"] * 10)
    rows = _rows(labels, ["DOWN"] * len(labels))
    inp = tmp_path / "predictions.jsonl"
    inp.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
    model = tmp_path / "model.joblib"
    model.write_bytes(b"test-model")
    monkeypatch.setattr(stage6, "REGISTRY", tmp_path / "registry")
    out = tmp_path / "out"
    report = run(inp, out, model, min_evaluated=10, bootstrap_samples=50)
    assert (out / "stage6_evaluation.json").is_file()
    assert (out / "stage6_report.md").is_file()
    assert report["promotion_gate"]["promote_candidate"] is False
    champion = json.loads((tmp_path / "registry" / "champion.json").read_text())
    assert champion["status"] == "NO_VALIDATED_CHAMPION"
    assert report["registry"]["artifact_sha256"]


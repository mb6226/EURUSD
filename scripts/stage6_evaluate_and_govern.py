"""Stage 6: leakage-aware evaluation, drift monitoring and model governance.

Consumes immutable Stage-5 walk-forward predictions. It does not tune on the
held-out period. Promotion is deliberately conservative and requires evidence
against causal baselines; otherwise the candidate is retained but not promoted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

CLASSES = ("DOWN", "FLAT", "UP")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE5 = PROJECT_ROOT / "Modules/Elliott_Waves/Evaluation/stage5/daily_walk_forward_predictions.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "Modules/Elliott_Waves/Evaluation/stage6"
DEFAULT_MODEL = PROJECT_ROOT / "Modules/Elliott_Waves/Models/daily_elliott_forecaster.joblib"
REGISTRY = PROJECT_ROOT / "Modules/Elliott_Waves/Models/registry"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_predictions(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_number}: {exc}") from exc
            if "actual" not in item:
                continue
            actual = item["actual"].get("direction")
            pred = item.get("classifier_direction")
            if actual not in CLASSES or pred not in CLASSES:
                raise ValueError(f"Invalid class at line {line_number}: actual={actual}, pred={pred}")
            rows.append(item)
    rows.sort(key=lambda x: x["forecast_cutoff_ny"])
    stamps = [x["forecast_cutoff_ny"] for x in rows]
    if len(stamps) != len(set(stamps)):
        raise ValueError("Duplicate forecast cutoff timestamps")
    if stamps != sorted(stamps):
        raise ValueError("Forecasts are not chronological")
    return rows


def metrics(y_true: list[str], y_pred: list[str]) -> dict:
    n = len(y_true)
    if not n:
        return {"n": 0, "accuracy": None, "balanced_accuracy": None, "macro_f1": None,
                "per_class": {}, "confusion_matrix": []}
    matrix = [[sum(a == actual and p == predicted for a, p in zip(y_true, y_pred))
               for predicted in CLASSES] for actual in CLASSES]
    per_class = {}
    recalls, f1s = [], []
    for i, label in enumerate(CLASSES):
        tp = matrix[i][i]
        support = sum(matrix[i])
        predicted_count = sum(row[i] for row in matrix)
        precision = tp / predicted_count if predicted_count else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
        if support:
            recalls.append(recall)
        f1s.append(f1)
    return {
        "n": n,
        "accuracy": sum(a == p for a, p in zip(y_true, y_pred)) / n,
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else None,
        "macro_f1": sum(f1s) / len(f1s),
        "per_class": per_class,
        "confusion_matrix": matrix,
        "confusion_matrix_order": list(CLASSES),
    }


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n == 0:
        return None
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / den
    return [max(0.0, center - margin), min(1.0, center + margin)]


def causal_baselines(rows: list[dict]) -> tuple[list[str], list[str], list[int]]:
    """At each t, use only labels observed at earlier forecast origins."""
    majority, persistence, indices = [], [], []
    history: list[str] = []
    for i, row in enumerate(rows):
        if history:
            counts = Counter(history)
            # Deterministic tie-break: FLAT, DOWN, UP.
            majority.append(sorted(CLASSES, key=lambda c: (-counts[c], ("FLAT", "DOWN", "UP").index(c)))[0])
            persistence.append(history[-1])
            indices.append(i)
        history.append(row["actual"]["direction"])
    return majority, persistence, indices


def block_bootstrap_difference(correct_model: list[int], correct_base: list[int],
                               block_size: int = 10, samples: int = 1000,
                               seed: int = 20261121) -> dict:
    """Paired moving-block bootstrap; preserves short-range serial dependence."""
    n = len(correct_model)
    if n < 2:
        return {"mean_accuracy_difference": None, "ci95": None, "samples": 0, "block_size": block_size}
    diff = np.asarray(correct_model, dtype=float) - np.asarray(correct_base, dtype=float)
    rng = np.random.default_rng(seed)
    blocks = [np.arange(i, min(i + block_size, n)) for i in range(n)]
    estimates = []
    needed = n
    for _ in range(samples):
        chosen = []
        while len(chosen) < needed:
            block = blocks[int(rng.integers(0, len(blocks)))]
            chosen.extend(diff[block].tolist())
        estimates.append(float(np.mean(chosen[:needed])))
    return {
        "mean_accuracy_difference": float(np.mean(diff)),
        "ci95": [float(x) for x in np.quantile(estimates, [0.025, 0.975])],
        "samples": samples,
        "block_size": block_size,
        "method": "paired moving-block bootstrap; 10 forecast origins per block",
    }


def yearly_metrics(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        year = datetime.fromisoformat(row["forecast_cutoff_ny"].replace("Z", "+00:00")).year
        grouped.setdefault(str(year), []).append(row)
    result = {}
    for year, group in sorted(grouped.items()):
        result[year] = metrics([x["actual"]["direction"] for x in group],
                               [x["classifier_direction"] for x in group])
    return result


def evaluate(rows: list[dict], min_evaluated: int = 250, bootstrap_samples: int = 1000) -> dict:
    if len(rows) < 2:
        raise ValueError("At least two evaluated forecasts are required")
    y = [x["actual"]["direction"] for x in rows]
    model_pred = [x["classifier_direction"] for x in rows]
    majority, persistence, base_indices = causal_baselines(rows)
    model_indices = [model_pred[i] for i in base_indices]
    actual_indices = [y[i] for i in base_indices]
    majority_metrics = metrics(actual_indices, majority)
    persistence_metrics = metrics(actual_indices, persistence)
    model_common = metrics(actual_indices, model_indices)

    model_correct = [int(a == p) for a, p in zip(actual_indices, model_indices)]
    majority_correct = [int(a == p) for a, p in zip(actual_indices, majority)]
    persistence_correct = [int(a == p) for a, p in zip(actual_indices, persistence)]
    majority_boot = block_bootstrap_difference(model_correct, majority_correct, samples=bootstrap_samples)
    persistence_boot = block_bootstrap_difference(model_correct, persistence_correct, samples=bootstrap_samples)

    published_positions = [j for j, i in enumerate(base_indices) if rows[i].get("direction") != "CONFLICT"]
    published_actual = [actual_indices[j] for j in published_positions]
    published_model = [model_indices[j] for j in published_positions]
    published_majority = [majority[j] for j in published_positions]
    published_persistence = [persistence[j] for j in published_positions]

    n = len(base_indices)
    acc_count = sum(model_correct)
    majority_ci = majority_boot["ci95"]
    persistence_ci = persistence_boot["ci95"]
    enough = n >= min_evaluated
    beats_majority = (majority_metrics["accuracy"] is not None and
                      model_common["accuracy"] > majority_metrics["accuracy"] and
                      majority_ci is not None and majority_ci[0] > 0)
    beats_persistence = (persistence_metrics["accuracy"] is not None and
                         model_common["accuracy"] > persistence_metrics["accuracy"] and
                         persistence_ci is not None and persistence_ci[0] > 0)
    promoted = bool(enough and beats_majority and beats_persistence and
                    model_common["balanced_accuracy"] >= majority_metrics["balanced_accuracy"])
    # Existing vote shares are not calibrated probabilities; no Brier/log-loss is reported.
    abstentions = sum(x.get("direction") == "CONFLICT" for x in rows)
    return {
        "schema_version": 1,
        "evaluation": {
            "evaluated_forecasts_in_input": len(rows),
            "common_baseline_comparison_n": n,
            "first_forecast_excluded_from_causal_baseline_comparison": True,
            "model": model_common,
            "expanding_majority_baseline": majority_metrics,
            "previous_session_persistence_baseline": persistence_metrics,
            "model_accuracy_wilson95": wilson_interval(acc_count, n),
            "model_vs_expanding_majority": majority_boot,
            "model_vs_persistence": persistence_boot,
            "published_non_conflict": metrics(published_actual, published_model),
            "published_non_conflict_coverage": len(published_positions) / n if n else None,
            "published_majority_baseline_same_subset": metrics(published_actual, published_majority),
            "published_persistence_baseline_same_subset": metrics(published_actual, published_persistence),
            "conflict_abstentions_in_all_evaluated": abstentions,
            "conflict_rate": abstentions / len(rows) if rows else None,
            "yearly_model_metrics": yearly_metrics(rows),
        },
        "promotion_gate": {
            "minimum_evaluated_forecasts": min_evaluated,
            "actual_common_sample_size": n,
            "enough_evidence": enough,
            "beats_expanding_majority_with_95pct_block_ci": beats_majority,
            "beats_persistence_with_95pct_block_ci": beats_persistence,
            "balanced_accuracy_not_below_majority_baseline": (
                model_common["balanced_accuracy"] >= majority_metrics["balanced_accuracy"]
            ),
            "promote_candidate": promoted,
            "decision": "PROMOTE" if promoted else "REJECT_PROMOTION_KEEP_INCUMBENT",
            "reason": ("All predeclared gates passed." if promoted else
                       "At least one predeclared evidence/performance gate failed; no automatic promotion."),
        },
        "limitations": [
            "These Stage-5 outcomes have already been inspected; this is governance/audit evidence, not a fresh untouched holdout.",
            "Daily forecast outcomes are serially dependent; block-bootstrap intervals are approximate.",
            "The classifier vote shares are not calibrated probabilities; Brier score and log-loss are intentionally omitted.",
            "No raw feature vectors were saved with each forecast, so this run monitors target/metric drift by year, not feature-level PSI.",
            "A Stage-5 candidate is not promoted merely because it is newer or was retrained.",
            "No model tuning is performed on this evaluation set.",
        ],
    }


def register_candidate(report: dict, model_path: Path, input_path: Path, output_dir: Path) -> dict:
    """Archive an immutable candidate; never overwrite the current champion."""
    REGISTRY.mkdir(parents=True, exist_ok=True)
    candidate_hash = sha256_file(model_path)
    input_hash = sha256_file(input_path)
    code_hash = sha256_file(Path(__file__))
    version = f"stage5_{candidate_hash[:12]}" if candidate_hash else "stage5_model_missing"
    entry_dir = REGISTRY / version
    entry_dir.mkdir(parents=True, exist_ok=True)
    archived_model = None
    if model_path.is_file():
        archived_model = entry_dir / "daily_elliott_forecaster.joblib"
        if not archived_model.exists():
            shutil.copy2(model_path, archived_model)
    manifest = {
        "version": version,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "artifact_sha256": candidate_hash,
        "stage5_predictions_sha256": input_hash,
        "stage6_evaluator_sha256": code_hash,
        "artifact_source": str(model_path),
        "archived_artifact": str(archived_model) if archived_model else None,
        "evaluation_decision": report["promotion_gate"]["decision"],
        "promoted": report["promotion_gate"]["promote_candidate"],
        "note": "Archived candidate; champion pointer is only changed by a passing promotion gate.",
    }
    (entry_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (entry_dir / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    champion_path = REGISTRY / "champion.json"
    if report["promotion_gate"]["promote_candidate"]:
        champion_path.write_text(json.dumps({"version": version, "artifact_sha256": candidate_hash}, indent=2),
                                 encoding="utf-8")
    elif not champion_path.exists():
        champion_path.write_text(json.dumps({
            "version": None, "artifact_sha256": None,
            "status": "NO_VALIDATED_CHAMPION",
            "reason": "No candidate has passed the Stage-6 promotion gate.",
        }, indent=2), encoding="utf-8")
    return manifest


def run(input_path: Path = DEFAULT_STAGE5, output_dir: Path = DEFAULT_OUTPUT,
        model_path: Path = DEFAULT_MODEL, min_evaluated: int = 250,
        bootstrap_samples: int = 1000) -> dict:
    rows = load_predictions(input_path)
    report = evaluate(rows, min_evaluated=min_evaluated, bootstrap_samples=bootstrap_samples)
    report["provenance"] = {
        "input_predictions": str(input_path),
        "input_sha256": sha256_file(input_path),
        "model_artifact": str(model_path),
        "model_artifact_sha256": sha256_file(model_path),
        "evaluation_code_sha256": sha256_file(Path(__file__)),
        "stage5_input_is_immutable": True,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stage6_evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest = register_candidate(report, model_path, input_path, output_dir)
    report["registry"] = manifest
    (output_dir / "stage6_evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Stage 6 â€” Automatic Evaluation & Retraining Governance", "",
        f"- Evaluated forecasts: {report['evaluation']['evaluated_forecasts_in_input']}",
        f"- Common baseline sample: {report['evaluation']['common_baseline_comparison_n']}",
        f"- Model accuracy: {report['evaluation']['model']['accuracy']:.3%}",
        f"- Expanding-majority accuracy: {report['evaluation']['expanding_majority_baseline']['accuracy']:.3%}",
        f"- Previous-session persistence accuracy: {report['evaluation']['previous_session_persistence_baseline']['accuracy']:.3%}",
        f"- Model vs majority 95% block CI: {report['evaluation']['model_vs_expanding_majority']['ci95']}",
        f"- Model vs persistence 95% block CI: {report['evaluation']['model_vs_persistence']['ci95']}",
        f"- Non-conflict coverage: {report['evaluation']['published_non_conflict_coverage']:.3%}",
        f"- Promotion decision: {report['promotion_gate']['decision']}", "",
        "## Decision", "", report["promotion_gate"]["reason"], "",
        "## Interpretation", "",
        "This evaluator uses only prior observed outcomes to construct the expanding-majority and persistence baselines. "
        "It excludes the first forecast from comparisons because no earlier outcome is available. "
        "The moving-block bootstrap partially accounts for serial dependence. "
        "No hyperparameter search or fitting occurs on these evaluation outcomes.", "",
        "The Stage-5 period has already been examined, so these results are not a new untouched holdout. "
        "A fresh prospective period is required before claiming generalization. "
        "Vote shares are not calibrated probabilities; no probability scoring is reported.", "",
        "The candidate artifact is archived immutably. A failed gate never overwrites a champion.",
    ]
    (output_dir / "stage6_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage-6 causal evaluation and model governance")
    parser.add_argument("--input", type=Path, default=DEFAULT_STAGE5)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--min-evaluated", type=int, default=250)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    args = parser.parse_args()
    report = run(args.input, args.output_dir, args.model, args.min_evaluated, args.bootstrap_samples)
    print(json.dumps({
        "evaluation": report["evaluation"],
        "promotion_gate": report["promotion_gate"],
        "registry": report["registry"],
    }, indent=2))


if __name__ == "__main__":
    main()




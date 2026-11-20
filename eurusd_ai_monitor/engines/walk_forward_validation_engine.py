from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from math import ceil, isfinite, sqrt
import json
from statistics import mean, pstdev
from typing import Any, Mapping

HORIZONS = ("15M", "1H", "4H")
HORIZON_MINUTES = {"15M": 15, "1H": 60, "4H": 240}
TARGET_COVERAGES = (0.80, 0.90, 0.95)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None and result.utcoffset() is not None else None


def _near(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-6 * max(1.0, abs(left), abs(right))


class WalkForwardValidationEngine:
    """Sequential out-of-sample validation with label-availability purging."""

    VERSION = "walk-forward-validation-v1"

    def __init__(
        self, *, minimum_training_samples: int = 100,
        test_window_samples: int = 30, maximum_training_samples: int = 500,
        minimum_folds: int = 2,
    ):
        for name, value, lower in (
            ("minimum_training_samples", minimum_training_samples, 20),
            ("test_window_samples", test_window_samples, 10),
            ("maximum_training_samples", maximum_training_samples, 20),
            ("minimum_folds", minimum_folds, 2),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < lower:
                raise ValueError(f"{name} must be an integer >= {lower}")
        if maximum_training_samples < minimum_training_samples:
            raise ValueError("maximum_training_samples must be >= minimum_training_samples")
        self.minimum_training_samples = minimum_training_samples
        self.test_window_samples = test_window_samples
        self.maximum_training_samples = maximum_training_samples
        self.minimum_folds = minimum_folds

    def validate(self, replay: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(replay, Mapping):
            raise TypeError("replay must be a mapping")
        if replay.get("report_type") != "EURUSD_POINT_IN_TIME_FORECAST_REPLAY":
            raise ValueError("UNSUPPORTED_REPLAY_REPORT_TYPE")
        if replay.get("status") != "COMPLETE":
            return self._blocked(replay, "REPLAY_NOT_COMPLETE")
        if replay.get("symbol") != "EURUSD" or replay.get("timeframe") != "M5":
            raise ValueError("REPLAY_STREAM_IDENTITY_UNSUPPORTED")
        if not replay.get("replay_id") or not replay.get("source_history_sha256"):
            raise ValueError("REPLAY_IDENTITY_OR_SOURCE_HASH_MISSING")
        policy = replay.get("integrity_policy")
        required = (
            "forecast_inputs_filtered_by_observed_and_as_of_at_each_cutoff",
            "only_closed_candles_used",
            "target_outcome_uses_first_closed_version_observed_after_target_close",
            "later_revisions_never_rewrite_forecast_or_target_version",
            "future_outcomes_excluded_from_forecast_snapshot",
            "system_knowledge_replay_only",
        )
        if not isinstance(policy, Mapping) or any(policy.get(key) is not True for key in required):
            raise ValueError("REPLAY_POINT_IN_TIME_INTEGRITY_POLICY_UNVERIFIED")
        records = replay.get("records")
        if not isinstance(records, list):
            raise ValueError("REPLAY_RECORDS_MISSING")

        accepted = {h: [] for h in HORIZONS}
        rejected = Counter()
        seen = set()
        for row in records:
            if not isinstance(row, Mapping):
                rejected["RECORD_NOT_A_MAPPING"] += 1
                continue
            horizon = row.get("horizon")
            if horizon not in HORIZONS:
                rejected["HORIZON_UNSUPPORTED"] += 1
                continue
            forecast_id = row.get("forecast_id")
            if not isinstance(forecast_id, str) or not forecast_id:
                rejected["FORECAST_ID_MISSING"] += 1
                continue
            if forecast_id in seen:
                rejected["DUPLICATE_FORECAST_ID"] += 1
                continue
            seen.add(forecast_id)
            if row.get("replay_id") != replay.get("replay_id"):
                rejected["REPLAY_ID_MISMATCH"] += 1
                continue
            if row.get("forecast_status") != "AVAILABLE":
                rejected["FORECAST_NOT_AVAILABLE"] += 1
                continue
            if not row.get("snapshot_sha256") or not row.get("anchor_version_id") or not row.get("target_version_id"):
                rejected["FORECAST_OR_TARGET_PROVENANCE_MISSING"] += 1
                continue
            cutoff = _time(row.get("forecast_cutoff_utc"))
            target_close = _time(row.get("target_close_time_utc"))
            if cutoff is None or target_close is None or target_close <= cutoff:
                rejected["FORECAST_TARGET_TIME_INVALID"] += 1
                continue
            expected, actual = _number(row.get("expected_move_pips")), _number(row.get("actual_move_pips"))
            payload = row.get("forecast_json")
            if expected is None or actual is None or not isinstance(payload, Mapping):
                rejected["COMPLETED_OUTCOME_OR_FORECAST_INVALID"] += 1
                continue
            dispersion = _number(payload.get("historical_dispersion_pips"))
            payload_expected = _number(payload.get("expected_move_pips_baseline"))
            if dispersion is None or dispersion <= 0 or payload_expected is None or not _near(expected, payload_expected):
                rejected["BASELINE_DISPERSION_INVALID"] += 1
                continue
            if payload.get("numeric_probability") is not None or payload.get("calibrated_confidence") is not None:
                rejected["UNSUPPORTED_PROBABILITY_OR_CONFIDENCE"] += 1
                continue
            one, two = payload.get("descriptive_band_1_sigma_pips"), payload.get("descriptive_band_2_sigma_pips")
            if not isinstance(one, list) or len(one) != 2 or not isinstance(two, list) or len(two) != 2:
                rejected["DESCRIPTIVE_BANDS_MISSING"] += 1
                continue
            bounds = [_number(v) for v in one + two]
            if (any(v is None for v in bounds)
                or not _near(bounds[0], expected - dispersion)
                or not _near(bounds[1], expected + dispersion)
                or not _near(bounds[2], expected - 2 * dispersion)
                or not _near(bounds[3], expected + 2 * dispersion)):
                rejected["DESCRIPTIVE_BANDS_INCONSISTENT"] += 1
                continue
            accepted[horizon].append({
                "forecast_id": forecast_id, "cutoff": cutoff, "target_close": target_close,
                "expected": expected, "actual": actual, "dispersion": dispersion,
                "normalized_error": abs(actual - expected) / dispersion,
                "direction_hit": row.get("direction_hit"),
                "forecast_direction": row.get("forecast_direction"),
                "outcome_direction": row.get("outcome_direction"),
                "snapshot_sha256": row["snapshot_sha256"],
                "anchor_version_id": row["anchor_version_id"],
                "target_version_id": row["target_version_id"],
            })

        by_horizon = {}
        for horizon in HORIZONS:
            rows = sorted(accepted[horizon], key=lambda x: (x["cutoff"], x["forecast_id"]))
            by_horizon[horizon] = self._validate_horizon(rows, horizon)
        validated = sum(v["status"] == "WALK_FORWARD_EVALUATED" for v in by_horizon.values())
        status = "AVAILABLE" if validated == len(HORIZONS) else "PARTIAL" if validated else "BLOCKED"
        identity = {
            "engine": self.VERSION, "replay_id": replay["replay_id"],
            "source_history_sha256": replay["source_history_sha256"],
            "minimum_training_samples": self.minimum_training_samples,
            "test_window_samples": self.test_window_samples,
            "maximum_training_samples": self.maximum_training_samples,
            "minimum_folds": self.minimum_folds, "by_horizon": by_horizon,
        }
        return {
            "report_type": "EURUSD_WALK_FORWARD_VALIDATION",
            "engine_version": self.VERSION, "status": status,
            "validation_id": sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
            "replay_id": replay["replay_id"], "source_history_sha256": replay["source_history_sha256"],
            "symbol": "EURUSD", "timeframe": "M5",
            "configuration": {
                "minimum_training_samples": self.minimum_training_samples,
                "test_window_samples": self.test_window_samples,
                "maximum_training_samples": self.maximum_training_samples,
                "minimum_folds": self.minimum_folds,
                "training_window": "ROLLING_LATEST_ELIGIBLE_COMPLETED_OUTCOMES",
                "fold_step": "NON_OVERLAPPING_CHRONOLOGICAL_TEST_WINDOWS",
                "training_label_purge": "TRAINING_TARGET_CLOSE_MUST_BE_AT_OR_BEFORE_TEST_WINDOW_START",
            },
            "replay_records_received": len(records),
            "accepted_completed_records": sum(len(v) for v in accepted.values()),
            "rejected_counts": dict(sorted(rejected.items())),
            "by_horizon": by_horizon,
            "methodology": {
                "forecast_model": "PHASE44_FIXED_BASELINE_NO_PARAMETER_TUNING",
                "folding": "Each test fold follows its training outcomes chronologically; no forecast cutoff is split across partitions.",
                "label_availability": "Training outcomes whose target close is later than the test start are purged, preventing unavailable future labels from entering training.",
                "interval_calibration": "Per fold, fit normalized absolute residual multipliers on the eligible training partition only; evaluate on the next untouched test window.",
                "horizons": "15M, 1H and 4H are evaluated independently and never pooled.",
                "directional_metrics": "Descriptive UP/DOWN/NEUTRAL agreement only; no probabilities are estimated.",
            },
            "limitations": [
                "Phase44 is a fixed transparent baseline; this phase validates it but does not tune or train model parameters.",
                "Forecasts and outcomes may overlap in time; sample counts are not independent-trial counts and metrics can be serially dependent.",
                "Fold-to-fold variation is descriptive and does not prove stationarity or future performance.",
                "Interval multipliers are fold-local research outputs and are not applied to live forecasts.",
                "No spread, slippage, execution, P/L, profitability or trade performance is evaluated.",
                "A separate later phase is required for cross-domain attribution and model-selection governance.",
            ],
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    def _validate_horizon(self, rows: list[dict[str, Any]], horizon: str) -> dict[str, Any]:
        cutoffs = sorted({r["cutoff"] for r in rows})
        horizon_gap = HORIZON_MINUTES[horizon]
        start_index = self.minimum_training_samples + (horizon_gap // 5) + 1
        folds = []
        fold_start = start_index
        while fold_start < len(cutoffs):
            test_cutoffs = cutoffs[fold_start:fold_start + self.test_window_samples]
            if len(test_cutoffs) < self.test_window_samples:
                break
            test_start = test_cutoffs[0]
            test_end = test_cutoffs[-1]
            training = [r for r in rows if r["cutoff"] < test_start and r["target_close"] <= test_start]
            training = training[-self.maximum_training_samples:]
            test = [r for r in rows if test_start <= r["cutoff"] <= test_end]
            if len(training) >= self.minimum_training_samples and len(test) >= self.test_window_samples:
                folds.append(self._score_fold(len(folds) + 1, training, test, test_start, test_end))
            fold_start += self.test_window_samples

        if len(folds) < self.minimum_folds:
            return {
                "status": "BLOCKED_INSUFFICIENT_WALK_FORWARD_FOLDS",
                "completed_outcome_count": len(rows), "distinct_forecast_cutoffs": len(cutoffs),
                "fold_count": len(folds), "minimum_folds": self.minimum_folds,
                "reason_codes": ["MINIMUM_TRAINING_HISTORY_OR_NONOVERLAPPING_TEST_FOLDS_NOT_MET"],
                "folds": folds,
            }
        return {
            "status": "WALK_FORWARD_EVALUATED",
            "completed_outcome_count": len(rows), "distinct_forecast_cutoffs": len(cutoffs),
            "fold_count": len(folds), "minimum_folds": self.minimum_folds,
            "aggregate": self._aggregate(folds),
            "fold_stability": self._stability(folds),
            "folds": folds,
        }

    def _score_fold(self, fold_number, training, test, test_start, test_end):
        ordered = sorted(r["normalized_error"] for r in training)
        interval_results = {}
        for coverage in TARGET_COVERAGES:
            rank = ceil((len(ordered) + 1) * coverage)
            if rank > len(ordered):
                interval_results[f"{coverage:.2f}"] = {"status": "BLOCKED_TRAINING_SAMPLE_TOO_SMALL"}
                continue
            multiplier = ordered[rank - 1]
            hits = [r["normalized_error"] <= multiplier for r in test]
            widths = [2 * multiplier * r["dispersion"] for r in test]
            interval_results[f"{coverage:.2f}"] = {
                "target_coverage": coverage,
                "training_multiplier": round(multiplier, 8),
                "test_empirical_coverage": mean(1.0 if x else 0.0 for x in hits),
                "coverage_gap": mean(1.0 if x else 0.0 for x in hits) - coverage,
                "mean_test_interval_width_pips": mean(widths),
            }
        errors = [r["actual"] - r["expected"] for r in test]
        directional = [r for r in test if r["direction_hit"] is not None]
        baseline = {
            "1_sigma_empirical_coverage": mean(1.0 if r["normalized_error"] <= 1 else 0.0 for r in test),
            "2_sigma_empirical_coverage": mean(1.0 if r["normalized_error"] <= 2 else 0.0 for r in test),
        }
        return {
            "fold": fold_number,
            "training_count": len(training), "test_count": len(test),
            "training_cutoff_start_utc": min(r["cutoff"] for r in training).isoformat().replace("+00:00", "Z"),
            "training_cutoff_end_utc": max(r["cutoff"] for r in training).isoformat().replace("+00:00", "Z"),
            "test_start_utc": test_start.isoformat().replace("+00:00", "Z"),
            "test_end_utc": test_end.isoformat().replace("+00:00", "Z"),
            "training_labels_available_by_test_start": all(r["target_close"] <= test_start for r in training),
            "strict_temporal_separation": max(r["cutoff"] for r in training) < test_start,
            "mean_absolute_error_pips": mean(abs(x) for x in errors),
            "root_mean_squared_error_pips": sqrt(mean(x * x for x in errors)),
            "mean_signed_error_pips": mean(errors),
            "directional_accuracy_including_neutral": mean(1.0 if r["direction_hit"] else 0.0 for r in directional) if directional else None,
            "direction_sample_count": len(directional),
            "baseline_descriptive_band_coverage": baseline,
            "training_fitted_interval_results": interval_results,
        }

    @staticmethod
    def _aggregate(folds):
        total = sum(f["test_count"] for f in folds)
        weighted = lambda key: sum(f[key] * f["test_count"] for f in folds) / total
        return {
            "test_sample_count": total,
            "mean_fold_mae_pips": mean(f["mean_absolute_error_pips"] for f in folds),
            "weighted_mean_absolute_error_pips": weighted("mean_absolute_error_pips"),
            "weighted_mean_signed_error_pips": weighted("mean_signed_error_pips"),
            "weighted_mean_directional_accuracy": (
                sum((f["directional_accuracy_including_neutral"] or 0) * f["direction_sample_count"] for f in folds)
                / max(1, sum(f["direction_sample_count"] for f in folds))
            ),
            "direction_sample_count": sum(f["direction_sample_count"] for f in folds),
        }

    @staticmethod
    def _stability(folds):
        values = [f["mean_absolute_error_pips"] for f in folds]
        return {
            "fold_mae_min_pips": min(values), "fold_mae_max_pips": max(values),
            "fold_mae_population_stddev_pips": pstdev(values) if len(values) > 1 else 0.0,
            "interpretation": "DESCRIPTIVE_FOLD_VARIATION_NOT_A_STATIONARITY_OR_FUTURE_PERFORMANCE_GUARANTEE",
        }

    def _blocked(self, replay, reason):
        return {
            "report_type": "EURUSD_WALK_FORWARD_VALIDATION",
            "engine_version": self.VERSION, "status": "BLOCKED",
            "reason_codes": [reason], "replay_id": replay.get("replay_id"),
            "symbol": replay.get("symbol"), "timeframe": replay.get("timeframe"),
            "accepted_completed_records": 0,
            "by_horizon": {h: {"status": "BLOCKED_NO_VALID_REPLAY"} for h in HORIZONS},
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

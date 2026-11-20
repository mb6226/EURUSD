from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from math import ceil, isfinite
import json
from statistics import mean, median
from typing import Any, Mapping

HORIZONS = ("15M", "1H", "4H")
TARGET_COVERAGES = (0.80, 0.90, 0.95)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _close(a: float, b: float, tolerance: float = 1e-6) -> bool:
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


class UncertaintyCalibrationEngine:
    """Chronological split-calibration of descriptive forecast bands; never emits probabilities."""

    VERSION = "uncertainty-calibration-v1"

    def __init__(
        self, *, minimum_calibration_samples: int = 50,
        minimum_evaluation_samples: int = 30, calibration_fraction: float = 0.60,
    ):
        for name, value in (("minimum_calibration_samples", minimum_calibration_samples),
                            ("minimum_evaluation_samples", minimum_evaluation_samples)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 10:
                raise ValueError(f"{name} must be an integer >= 10")
        if (isinstance(calibration_fraction, bool) or not isinstance(calibration_fraction, (int, float))
            or not isfinite(float(calibration_fraction)) or not 0.50 <= float(calibration_fraction) <= 0.80):
            raise ValueError("calibration_fraction must be between 0.50 and 0.80")
        self.minimum_calibration_samples = minimum_calibration_samples
        self.minimum_evaluation_samples = minimum_evaluation_samples
        self.calibration_fraction = float(calibration_fraction)

    def calibrate(self, replay: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(replay, Mapping):
            raise TypeError("replay must be a mapping")
        if replay.get("report_type") != "EURUSD_POINT_IN_TIME_FORECAST_REPLAY":
            raise ValueError("UNSUPPORTED_REPLAY_REPORT_TYPE")
        if replay.get("status") != "COMPLETE":
            return self._blocked(replay, "REPLAY_NOT_COMPLETE")
        if replay.get("symbol") != "EURUSD" or replay.get("timeframe") != "M5":
            raise ValueError("REPLAY_STREAM_IDENTITY_UNSUPPORTED")
        policy = replay.get("integrity_policy")
        required = (
            "forecast_inputs_filtered_by_observed_and_as_of_at_each_cutoff",
            "only_closed_candles_used",
            "target_outcome_uses_first_closed_version_observed_after_target_close",
            "later_revisions_never_rewrite_forecast_or_target_version",
            "future_outcomes_excluded_from_forecast_snapshot",
            "system_knowledge_replay_only",
        )
        if not isinstance(policy, Mapping) or any(policy.get(k) is not True for k in required):
            raise ValueError("REPLAY_POINT_IN_TIME_INTEGRITY_POLICY_UNVERIFIED")
        records = replay.get("records")
        if not isinstance(records, list):
            raise ValueError("REPLAY_RECORDS_MISSING")

        rejected = Counter()
        accepted: dict[str, list[dict[str, Any]]] = {h: [] for h in HORIZONS}
        seen: set[str] = set()
        replay_id = replay.get("replay_id")
        for row in records:
            if not isinstance(row, Mapping):
                rejected["RECORD_NOT_A_MAPPING"] += 1
                continue
            horizon = row.get("horizon")
            if horizon not in HORIZONS:
                rejected["HORIZON_UNSUPPORTED"] += 1
                continue
            identity = row.get("forecast_id")
            if not isinstance(identity, str) or not identity:
                rejected["FORECAST_ID_MISSING"] += 1
                continue
            if identity in seen:
                rejected["DUPLICATE_FORECAST_ID"] += 1
                continue
            seen.add(identity)
            if row.get("replay_id") != replay_id:
                rejected["REPLAY_ID_MISMATCH"] += 1
                continue
            if row.get("forecast_status") != "AVAILABLE":
                rejected["FORECAST_NOT_AVAILABLE"] += 1
                continue
            if not row.get("snapshot_sha256") or not row.get("anchor_version_id") or not row.get("target_version_id"):
                rejected["FORECAST_OR_TARGET_PROVENANCE_MISSING"] += 1
                continue
            cutoff, target_close = _utc(row.get("forecast_cutoff_utc")), _utc(row.get("target_close_time_utc"))
            if cutoff is None or target_close is None or target_close <= cutoff:
                rejected["FORECAST_TARGET_TIME_INVALID"] += 1
                continue
            expected = _finite(row.get("expected_move_pips"))
            actual = _finite(row.get("actual_move_pips"))
            payload = row.get("forecast_json")
            if expected is None or actual is None or not isinstance(payload, Mapping):
                rejected["FORECAST_OR_OUTCOME_INVALID"] += 1
                continue
            dispersion = _finite(payload.get("historical_dispersion_pips"))
            payload_expected = _finite(payload.get("expected_move_pips_baseline"))
            if dispersion is None or dispersion <= 0 or payload_expected is None or not _close(expected, payload_expected):
                rejected["DISPERSION_OR_EXPECTED_MOVE_INVALID"] += 1
                continue
            if payload.get("numeric_probability") is not None or payload.get("calibrated_confidence") is not None:
                rejected["UNSUPPORTED_PROBABILITY_OR_CONFIDENCE_PAYLOAD"] += 1
                continue
            one = payload.get("descriptive_band_1_sigma_pips")
            two = payload.get("descriptive_band_2_sigma_pips")
            if (not isinstance(one, list) or len(one) != 2 or not isinstance(two, list) or len(two) != 2):
                rejected["DESCRIPTIVE_BANDS_MISSING"] += 1
                continue
            one_values = [_finite(x) for x in one]
            two_values = [_finite(x) for x in two]
            if (any(x is None for x in one_values + two_values)
                or not _close(one_values[0], expected - dispersion)
                or not _close(one_values[1], expected + dispersion)
                or not _close(two_values[0], expected - 2 * dispersion)
                or not _close(two_values[1], expected + 2 * dispersion)):
                rejected["DESCRIPTIVE_BANDS_INCONSISTENT"] += 1
                continue
            accepted[horizon].append({
                "forecast_id": identity, "cutoff": cutoff, "expected": expected,
                "actual": actual, "dispersion": dispersion,
                "normalized_absolute_error": abs(actual - expected) / dispersion,
                "snapshot_sha256": row["snapshot_sha256"],
                "anchor_version_id": row["anchor_version_id"],
                "target_version_id": row["target_version_id"],
            })

        results = {}
        for horizon in HORIZONS:
            rows = sorted(accepted[horizon], key=lambda r: (r["cutoff"], r["forecast_id"]))
            results[horizon] = self._calibrate_horizon(rows)
        available = sum(1 for v in results.values() if v.get("status") == "CALIBRATED_ON_HOLDOUT")
        status = "AVAILABLE" if available == len(HORIZONS) else "PARTIAL" if available else "BLOCKED"
        identity = {
            "engine": self.VERSION, "replay_id": replay_id,
            "source_history_sha256": replay.get("source_history_sha256"),
            "minimum_calibration_samples": self.minimum_calibration_samples,
            "minimum_evaluation_samples": self.minimum_evaluation_samples,
            "calibration_fraction": self.calibration_fraction,
            "horizons": results,
        }
        calibration_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        return {
            "report_type": "EURUSD_UNCERTAINTY_CALIBRATION",
            "engine_version": self.VERSION, "status": status,
            "calibration_id": calibration_id, "replay_id": replay_id,
            "source_history_sha256": replay.get("source_history_sha256"),
            "symbol": "EURUSD", "timeframe": "M5",
            "minimum_calibration_samples": self.minimum_calibration_samples,
            "minimum_evaluation_samples": self.minimum_evaluation_samples,
            "calibration_fraction": self.calibration_fraction,
            "replay_records_received": len(records),
            "accepted_completed_records": sum(len(v) for v in accepted.values()),
            "rejected_counts": dict(sorted(rejected.items())),
            "by_horizon": results,
            "calibration_contract": {
                "method": "CHRONOLOGICAL_SPLIT_CONFORMAL_ABSOLUTE_RESIDUAL_NORMALIZED_BY_BASELINE_DISPERSION",
                "target_coverages": list(TARGET_COVERAGES),
                "fit_partition_precedes_evaluation_partition": True,
                "evaluation_partition_never_used_to_fit_multipliers": True,
                "horizons_calibrated_separately": True,
                "probability_or_directional_confidence_emitted": False,
                "phase44_forecast_engine_modified": False,
                "multipliers_applied_to_live_forecasts": False,
            },
            "limitations": [
                "Empirical holdout coverage is descriptive and does not guarantee future coverage under serial dependence or regime change.",
                "Overlapping forecast horizons and repeated anchors can make samples dependent; raw counts are not independent-trial counts.",
                "Calibration is interval-width scaling only; no directional probability, calibrated confidence, or trading edge is estimated.",
                "Calibration multipliers are research outputs only and are not applied to Phase44 or live decisions.",
                "The evaluation partition is a single chronological holdout; a later walk-forward phase is required for stability assessment.",
            ],
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    def _calibrate_horizon(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        unique_cutoffs = sorted({r["cutoff"] for r in rows})
        if len(rows) < self.minimum_calibration_samples + self.minimum_evaluation_samples or len(unique_cutoffs) < 2:
            return {"status": "BLOCKED_INSUFFICIENT_COMPLETED_SAMPLES", "sample_count": len(rows),
                    "calibration_sample_count": 0, "evaluation_sample_count": 0,
                    "reason_codes": ["MINIMUM_CALIBRATION_AND_EVALUATION_SAMPLES_NOT_MET"]}
        split_index = int(len(unique_cutoffs) * self.calibration_fraction)
        split_index = max(1, min(len(unique_cutoffs) - 1, split_index))
        split_cutoff = unique_cutoffs[split_index - 1]
        calibration = [r for r in rows if r["cutoff"] <= split_cutoff]
        evaluation = [r for r in rows if r["cutoff"] > split_cutoff]
        if (len(calibration) < self.minimum_calibration_samples
            or len(evaluation) < self.minimum_evaluation_samples):
            return {"status": "BLOCKED_INSUFFICIENT_COMPLETED_SAMPLES", "sample_count": len(rows),
                    "calibration_sample_count": len(calibration), "evaluation_sample_count": len(evaluation),
                    "reason_codes": ["CHRONOLOGICAL_SPLIT_SAMPLE_MINIMUM_NOT_MET"]}
        normalized = sorted(r["normalized_absolute_error"] for r in calibration)
        metrics = {}
        for coverage in TARGET_COVERAGES:
            # Finite-sample split-conformal order statistic, using calibration data only.
            rank = ceil((len(normalized) + 1) * coverage)
            if rank > len(normalized):
                metrics[f"{coverage:.2f}"] = {"status": "BLOCKED_CALIBRATION_SAMPLE_TOO_SMALL"}
                continue
            multiplier = normalized[rank - 1]
            widths = [2 * multiplier * r["dispersion"] for r in evaluation]
            covered = [abs(r["actual"] - r["expected"]) <= multiplier * r["dispersion"] for r in evaluation]
            metrics[f"{coverage:.2f}"] = {
                "status": "EVALUATED", "target_coverage": coverage,
                "calibration_multiplier": round(multiplier, 8),
                "evaluation_sample_count": len(evaluation),
                "empirical_holdout_coverage": mean(1.0 if x else 0.0 for x in covered),
                "coverage_gap": mean(1.0 if x else 0.0 for x in covered) - coverage,
                "mean_interval_width_pips": mean(widths),
                "median_interval_width_pips": median(widths),
                "holdout_mean_absolute_error_pips": mean(abs(r["actual"] - r["expected"]) for r in evaluation),
            }
        baseline = {}
        for multiple in (1.0, 2.0):
            hits = [abs(r["actual"] - r["expected"]) <= multiple * r["dispersion"] for r in evaluation]
            baseline[f"{multiple:.0f}_sigma"] = {
                "empirical_holdout_coverage": mean(1.0 if x else 0.0 for x in hits),
                "evaluation_sample_count": len(evaluation),
            }
        return {
            "status": "CALIBRATED_ON_HOLDOUT",
            "sample_count": len(rows), "calibration_sample_count": len(calibration),
            "evaluation_sample_count": len(evaluation),
            "calibration_cutoff_start_utc": min(r["cutoff"] for r in calibration).isoformat().replace("+00:00", "Z"),
            "calibration_cutoff_end_utc": split_cutoff.isoformat().replace("+00:00", "Z"),
            "evaluation_cutoff_start_utc": min(r["cutoff"] for r in evaluation).isoformat().replace("+00:00", "Z"),
            "evaluation_cutoff_end_utc": max(r["cutoff"] for r in evaluation).isoformat().replace("+00:00", "Z"),
            "baseline_descriptive_band_coverage": baseline,
            "target_coverage_results": metrics,
            "fit_evaluation_cutoffs_strictly_separated": max(r["cutoff"] for r in calibration) < min(r["cutoff"] for r in evaluation),
        }

    def _blocked(self, replay: Mapping[str, Any], reason: str) -> dict[str, Any]:
        return {
            "report_type": "EURUSD_UNCERTAINTY_CALIBRATION",
            "engine_version": self.VERSION, "status": "BLOCKED",
            "reason_codes": [reason], "replay_id": replay.get("replay_id"),
            "symbol": replay.get("symbol"), "timeframe": replay.get("timeframe"),
            "accepted_completed_records": 0, "by_horizon": {
                h: {"status": "BLOCKED_NO_VALID_REPLAY"} for h in HORIZONS
            },
            "calibration_contract": {
                "fit_partition_precedes_evaluation_partition": True,
                "probability_or_directional_confidence_emitted": False,
                "phase44_forecast_engine_modified": False,
                "multipliers_applied_to_live_forecasts": False,
            },
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

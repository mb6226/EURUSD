from __future__ import annotations

from collections import Counter, defaultdict
from math import sqrt
from statistics import mean, median
from typing import Any, Mapping


HORIZONS = ("15M", "1H", "4H")
DIRECTIONS = ("UP", "DOWN", "NEUTRAL")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    from math import isfinite
    return number if isfinite(number) else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * q + 0.999999)))
    return ordered[index]


class ForecastErrorAnalysisEngine:
    """Descriptive analysis of completed Phase45 point-in-time replay records."""

    VERSION = "forecast-error-analysis-v1"

    def analyze(self, replay: Mapping[str, Any], *, minimum_samples: int = 30) -> dict[str, Any]:
        if not isinstance(replay, Mapping):
            raise TypeError("replay must be a mapping")
        if isinstance(minimum_samples, bool) or not isinstance(minimum_samples, int) or minimum_samples < 1:
            raise ValueError("minimum_samples must be a positive integer")
        report_type = replay.get("report_type")
        if report_type != "EURUSD_POINT_IN_TIME_FORECAST_REPLAY":
            raise ValueError("UNSUPPORTED_REPLAY_REPORT_TYPE")
        if replay.get("status") != "COMPLETE":
            return self._empty(replay, "REPLAY_NOT_COMPLETE", minimum_samples)
        if replay.get("timeframe") != "M5" or replay.get("symbol") != "EURUSD":
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
        if not isinstance(policy, Mapping) or any(policy.get(key) is not True for key in required):
            raise ValueError("REPLAY_POINT_IN_TIME_INTEGRITY_POLICY_UNVERIFIED")
        records = replay.get("records")
        if not isinstance(records, list):
            raise ValueError("REPLAY_RECORDS_MISSING")

        rejected = Counter()
        accepted: dict[str, list[dict[str, Any]]] = {h: [] for h in HORIZONS}
        seen = set()
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
            if row.get("forecast_status") != "AVAILABLE":
                rejected["FORECAST_NOT_AVAILABLE"] += 1
                continue
            if not row.get("snapshot_sha256") or not row.get("anchor_version_id"):
                rejected["FORECAST_PROVENANCE_MISSING"] += 1
                continue
            if row.get("actual_move_pips") is None:
                rejected["OUTCOME_NOT_YET_AVAILABLE"] += 1
                continue
            if not row.get("target_version_id"):
                rejected["TARGET_VERSION_ID_MISSING"] += 1
                continue
            expected = _finite(row.get("expected_move_pips"))
            actual = _finite(row.get("actual_move_pips"))
            if expected is None or actual is None:
                rejected["NONFINITE_FORECAST_OR_OUTCOME"] += 1
                continue
            forecast_direction = row.get("forecast_direction")
            outcome_direction = row.get("outcome_direction")
            if forecast_direction not in DIRECTIONS or outcome_direction not in DIRECTIONS:
                rejected["DIRECTION_LABEL_INVALID"] += 1
                continue
            target_time = row.get("target_close_time_utc")
            forecast_time = row.get("forecast_cutoff_utc")
            if not isinstance(target_time, str) or not isinstance(forecast_time, str):
                rejected["CUTOFF_OR_TARGET_TIME_MISSING"] += 1
                continue
            accepted[horizon].append({
                "forecast_id": identity,
                "forecast_direction": forecast_direction,
                "outcome_direction": outcome_direction,
                "expected_move_pips": expected,
                "actual_move_pips": actual,
                "signed_error_pips": actual - expected,
                "absolute_error_pips": abs(actual - expected),
                "direction_hit": forecast_direction == outcome_direction,
                "forecast_cutoff_utc": forecast_time,
                "target_close_time_utc": target_time,
                "snapshot_sha256": row["snapshot_sha256"],
                "anchor_version_id": row["anchor_version_id"],
                "target_version_id": row["target_version_id"],
                "dispersion_pips": _finite((row.get("forecast_json") or {}).get("historical_dispersion_pips"))
                    if isinstance(row.get("forecast_json"), Mapping) else None,
            })

        horizon_results = {}
        for horizon in HORIZONS:
            rows = accepted[horizon]
            n = len(rows)
            errors = [r["signed_error_pips"] for r in rows]
            absolute = [abs(x) for x in errors]
            actuals = [r["actual_move_pips"] for r in rows]
            expected = [r["expected_move_pips"] for r in rows]
            directional = [r for r in rows if r["forecast_direction"] in {"UP", "DOWN"}]
            confusion = {d: {a: 0 for a in DIRECTIONS} for d in DIRECTIONS}
            by_direction = defaultdict(list)
            for row in rows:
                confusion[row["forecast_direction"]][row["outcome_direction"]] += 1
                by_direction[row["forecast_direction"]].append(row)
            direction_metrics = {}
            for direction in DIRECTIONS:
                group = by_direction[direction]
                direction_metrics[direction] = {
                    "sample_count": len(group),
                    "mean_signed_error_pips": mean(x["signed_error_pips"] for x in group) if group else None,
                    "mean_absolute_error_pips": mean(x["absolute_error_pips"] for x in group) if group else None,
                    "directional_accuracy": mean(1.0 if x["direction_hit"] else 0.0 for x in group) if group else None,
                }
            dispersion_groups = self._dispersion_groups(rows)
            horizon_results[horizon] = {
                "status": "AVAILABLE" if n else "NO_COMPLETED_OUTCOMES",
                "sample_count": n,
                "sample_sufficiency": "MEETS_CONFIGURED_MINIMUM" if n >= minimum_samples else "BELOW_CONFIGURED_MINIMUM",
                "directional_accuracy_including_neutral": mean(1.0 if r["direction_hit"] else 0.0 for r in rows) if rows else None,
                "directional_accuracy_non_neutral_only": mean(1.0 if r["direction_hit"] else 0.0 for r in directional) if directional else None,
                "non_neutral_direction_sample_count": len(directional),
                "mean_absolute_error_pips": mean(absolute) if absolute else None,
                "root_mean_squared_error_pips": sqrt(mean(x*x for x in errors)) if errors else None,
                "mean_signed_error_pips_bias_actual_minus_forecast": mean(errors) if errors else None,
                "median_absolute_error_pips": median(absolute) if absolute else None,
                "p90_absolute_error_pips": _quantile(absolute, 0.90),
                "p95_absolute_error_pips": _quantile(absolute, 0.95),
                "mean_actual_move_pips": mean(actuals) if actuals else None,
                "mean_forecast_move_pips": mean(expected) if expected else None,
                "mean_absolute_actual_move_pips": mean(abs(x) for x in actuals) if actuals else None,
                "mean_absolute_forecast_move_pips": mean(abs(x) for x in expected) if expected else None,
                "confusion_matrix_forecast_rows_realized_columns": confusion,
                "by_forecast_direction": direction_metrics,
                "by_forecast_dispersion_tercile": dispersion_groups,
                "probability_metrics": "NOT_AVAILABLE_NO_CALIBRATED_PROBABILITIES",
            }

        total = sum(len(v) for v in accepted.values())
        available_count = sum(1 for r in records if isinstance(r, Mapping) and r.get("actual_move_pips") is not None)
        return {
            "report_type": "EURUSD_FORECAST_ERROR_ANALYSIS",
            "engine_version": self.VERSION,
            "status": "AVAILABLE" if total else "NO_COMPLETED_OUTCOMES",
            "replay_id": replay.get("replay_id"),
            "source_history_sha256": replay.get("source_history_sha256"),
            "broker_server": replay.get("broker_server"),
            "symbol": "EURUSD",
            "timeframe": "M5",
            "forecast_engine_version": "multi-horizon-forecast-v1",
            "replay_engine_version": replay.get("engine_version"),
            "minimum_samples": minimum_samples,
            "replay_forecast_records_received": len(records),
            "records_with_outcomes_reported": available_count,
            "accepted_completed_forecasts": total,
            "rejected_counts": dict(sorted(rejected.items())),
            "by_horizon": horizon_results,
            "regime_attribution": {
                "status": "UNAVAILABLE_NO_POINT_IN_TIME_REGIME_LABELS_IN_REPLAY_RECORDS",
                "note": "No regime is inferred from forecast errors or retrospective price behavior.",
            },
            "methodology": {
                "signed_error": "actual_move_pips - expected_move_pips; positive means the baseline under-forecasted the move.",
                "direction": "Categorical comparison of replay direction and replay-resolved realized close-to-close direction; neutral forecasts are reported separately.",
                "dispersion_buckets": "Within each horizon, completed records are sorted by the forecast's historical dispersion and split into up to three sample terciles. These are not market-regime labels.",
                "horizons": "15M, 1H and 4H are scored separately; no pooling across horizons.",
                "point_in_time": "Consumes only a COMPLETE Phase45 strict system-knowledge replay with all six integrity flags true.",
            },
            "limitations": [
                "Metrics describe this replay sample only; they do not establish out-of-sample predictive skill.",
                "MAE/RMSE/bias are in pips and do not represent execution costs, spread, slippage, P/L or profitability.",
                "No calibrated probabilities exist, so Brier score, log loss and calibration metrics are not computed.",
                "Market-regime attribution is unavailable because replay records do not carry a contemporaneous Phase39 regime label.",
                "Dispersion terciles are forecast-uncertainty strata, not inferred market regimes.",
                "Sample counts below the configured minimum are exploratory and should not drive model changes.",
                "Missing future outcomes are counted but never imputed.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _dispersion_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
        available = [r for r in rows if r["dispersion_pips"] is not None]
        available.sort(key=lambda r: (r["dispersion_pips"], r["forecast_id"]))
        if not available:
            return {"status": "UNAVAILABLE_NO_DISPERSION_VALUES", "groups": {}}
        chunks = [available[i::3] for i in range(3)]
        groups = {}
        for label, chunk in zip(("LOW", "MID", "HIGH"), chunks):
            if not chunk:
                continue
            errors = [r["signed_error_pips"] for r in chunk]
            groups[label] = {
                "sample_count": len(chunk),
                "dispersion_min_pips": min(r["dispersion_pips"] for r in chunk),
                "dispersion_max_pips": max(r["dispersion_pips"] for r in chunk),
                "mean_absolute_error_pips": mean(abs(x) for x in errors),
                "mean_signed_error_pips": mean(errors),
            }
        return {"status": "DESCRIPTIVE_TERCILES_NOT_MARKET_REGIMES", "groups": groups}

    def _empty(self, replay: Mapping[str, Any], reason: str, minimum_samples: int) -> dict[str, Any]:
        return {
            "report_type": "EURUSD_FORECAST_ERROR_ANALYSIS",
            "engine_version": self.VERSION, "status": "BLOCKED",
            "reason_codes": [reason], "replay_id": replay.get("replay_id"),
            "minimum_samples": minimum_samples, "accepted_completed_forecasts": 0,
            "by_horizon": {h: {"status": "NO_COMPLETED_OUTCOMES", "sample_count": 0} for h in HORIZONS},
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE", "order_execution": "DISABLED",
        }

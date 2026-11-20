from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
from statistics import median, stdev
from typing import Any, Mapping

VERSION = "multi-horizon-forecast-v1"
HORIZONS = {"15M": 3, "1H": 12, "4H": 48}


def _time(value: Any):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _num(value: Any):
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


class MultiHorizonForecastingEngine:
    """Transparent, uncalibrated baseline forecast over strict PIT EURUSD M5 data."""
    VERSION = VERSION

    def __init__(self, *, lookback_bars: int = 120, minimum_bars: int = 60,
                 pip_size: float = 0.0001):
        if isinstance(lookback_bars, bool) or not isinstance(lookback_bars, int) or lookback_bars < 10:
            raise ValueError("lookback_bars must be an integer >= 10")
        if isinstance(minimum_bars, bool) or not isinstance(minimum_bars, int) or minimum_bars < 10:
            raise ValueError("minimum_bars must be an integer >= 10")
        if minimum_bars > lookback_bars:
            raise ValueError("minimum_bars cannot exceed lookback_bars")
        pip = _num(pip_size)
        if pip is None or pip <= 0:
            raise ValueError("pip_size must be finite and positive")
        self.lookback_bars, self.minimum_bars, self.pip_size = lookback_bars, minimum_bars, pip

    def assess(self, snapshot: Mapping[str, Any],
               central_scenario: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise TypeError("snapshot must be a unified historical data-plane mapping")
        as_of = _time(snapshot.get("as_of_utc"))
        base = {
            "report_type": "EURUSD_MULTI_HORIZON_FORECAST",
            "engine_version": self.VERSION, "algorithm_version": self.VERSION,
            "as_of_utc": as_of.isoformat().replace("+00:00", "Z") if as_of else None,
            "snapshot_sha256": snapshot.get("snapshot_sha256"),
            "registry_sha256": snapshot.get("registry_sha256"),
            "read_mode": snapshot.get("read_mode"), "symbol": "EURUSD",
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        scenario, warning = self._scenario_context(central_scenario, as_of)
        if as_of is None:
            return self._empty(base, "INVALID_OR_MISSING_AS_OF_TIMESTAMP", scenario, warning)
        if snapshot.get("read_mode") != "STRICT_SYSTEM_KNOWLEDGE":
            return self._empty(base, "NON_STRICT_READ_MODE_BLOCKED", scenario, warning)
        archive = snapshot.get("spot_market_archive")
        streams = archive.get("streams") if isinstance(archive, Mapping) else None
        candidates = [s for s in (streams or []) if isinstance(s, Mapping)
                      and s.get("symbol") == "EURUSD" and s.get("timeframe") == "M5"]
        eligible = [s for s in candidates if s.get("status") == "PASS"
                    and s.get("eligible_for_analytics") is True]
        if not eligible:
            reason = "NO_QUALITY_ELIGIBLE_M5_STREAM" if candidates else "M5_STREAM_NOT_REGISTERED"
            return self._empty(base, reason, scenario, warning)
        if len(eligible) != 1:
            return self._empty(base, "AMBIGUOUS_MULTIPLE_ELIGIBLE_M5_STREAMS", scenario, warning)
        parsed, reason = self._validated_window(eligible[0].get("candles"), as_of)
        if reason:
            return self._empty(base, reason, scenario, warning)
        if len(parsed) < self.minimum_bars:
            return self._empty(base, "HISTORY_TOO_SHORT", scenario, warning)

        returns = [(b["close"] - a["close"]) / self.pip_size for a, b in zip(parsed, parsed[1:])]
        sigma = stdev(returns) if len(returns) > 1 else 0.0
        drift = median(returns[-12:]) if returns else 0.0
        forecasts = {}
        for label, bars in HORIZONS.items():
            expected, dispersion = drift * bars, sigma * sqrt(bars)
            threshold = max(0.05, dispersion * 0.25)
            direction = "UP" if expected > threshold else "DOWN" if expected < -threshold else "NEUTRAL"
            scenario_direction = scenario["directional_state"]
            alignment = ("ALIGNED" if direction == scenario_direction else
                         "DIVERGENT" if direction in {"UP", "DOWN"} and scenario_direction in {"UP", "DOWN"}
                         else "NOT_COMPARABLE")
            forecasts[label] = {
                "status": "AVAILABLE", "horizon_minutes": bars * 5, "horizon_bars": bars,
                "direction": direction, "expected_move_pips_baseline": round(expected, 5),
                "historical_dispersion_pips": round(dispersion, 5),
                "descriptive_band_1_sigma_pips": [round(expected-dispersion, 5), round(expected+dispersion, 5)],
                "descriptive_band_2_sigma_pips": [round(expected-2*dispersion, 5), round(expected+2*dispersion, 5)],
                "numeric_probability": None, "calibrated_confidence": None,
                "method": "RECENT_12_BAR_MEDIAN_RETURN_DRIFT_WITH_SQRT_TIME_HISTORICAL_DISPERSION",
                "scenario_alignment": alignment,
            }
        return {
            **base, "status": "AVAILABLE", "forecast_scope": "BASELINE_PRICE_SERIES_CONDITIONAL_OUTLOOK",
            "forecasts": forecasts, "scenario_context": scenario, "scenario_context_warning": warning,
            "provenance": {
                "source_id": eligible[0].get("source_id"), "broker_server": eligible[0].get("broker_server"),
                "timeframe": "M5", "price_basis": eligible[0].get("price_basis"),
                "bar_time_basis": "UTC", "closed_bars_only": True,
                "candle_version_ids": [r["version_id"] for r in parsed],
                "window_start_utc": parsed[0]["open_time"].isoformat(),
                "window_end_utc": parsed[-1]["open_time"].isoformat(),
                "sample_bars": len(parsed), "return_sample_size": len(returns),
            },
            "uncertainty_policy": {
                "bands_are_calibrated_prediction_intervals": False,
                "bands_are_descriptive_historical_dispersion_only": True,
                "numeric_probabilities_emitted": False,
                "confidence_calibration": "PENDING_OUT_OF_SAMPLE_EVALUATION",
            },
            "methodology": {
                "anchor": "Latest verified closed M5 candle at the strict system-knowledge cutoff.",
                "drift": "Median of the latest 12 close-to-close M5 returns multiplied by horizon bars.",
                "dispersion": "Sample standard deviation of bounded lookback returns scaled by square root of horizon bars.",
                "horizons": "15 minutes, 1 hour and 4 hours, reported separately.",
                "scenario_use": "Central scenario is comparison context only; it does not alter the baseline.",
            },
            "interpretation_limits": self._limits(),
        }

    def _validated_window(self, rows: Any, as_of: datetime):
        if not isinstance(rows, list):
            return [], "CANDLE_HISTORY_MISSING"
        parsed, previous = [], None
        for row in rows[-self.lookback_bars:]:
            if not isinstance(row, Mapping) or not isinstance(row.get("values"), Mapping):
                return [], "CANDLE_RECORD_INVALID"
            opened, observed, row_as_of = (_time(row.get(k)) for k in
                ("candle_open_time_utc", "observed_at_utc", "as_of_utc"))
            if opened is None or observed is None or row_as_of is None:
                return [], "CANDLE_TIMESTAMP_INVALID"
            if opened + timedelta(minutes=5) > as_of or observed > as_of or row_as_of > as_of or row.get("is_closed") is False:
                return [], "FUTURE_OR_FORMING_CANDLE"
            if previous is not None and opened - previous != timedelta(minutes=5):
                return [], "CANDLE_HISTORY_GAP"
            provenance = row.get("provenance")
            basis = (provenance.get("price_basis") or {}).get("price_basis") if isinstance(provenance, Mapping) else None
            if (row.get("source_id") not in {"MT5_COPY_RATES", "MT5_COPY_RATES_RANGE"}
                or basis not in {"BID", "LAST"} or provenance.get("bar_time_basis") != "UTC"):
                return [], "PRICE_OR_TIME_BASIS_UNVERIFIED"
            vals = [_num(row["values"].get(k)) for k in ("open", "high", "low", "close")]
            if any(v is None for v in vals):
                return [], "INVALID_OHLC_VALUES"
            o, h, l, c = vals
            if h < max(o, l, c) or l > min(o, h, c):
                return [], "INVALID_OHLC_VALUES"
            version = row.get("version_id")
            if not isinstance(version, str) or not version:
                return [], "CANDLE_VERSION_ID_MISSING"
            parsed.append({"open_time": opened, "close": c, "version_id": version})
            previous = opened
        if parsed and as_of - (parsed[-1]["open_time"] + timedelta(minutes=5)) > timedelta(minutes=15):
            return [], "SPOT_STREAM_STALE_FOR_FORECAST"
        return parsed, None

    @staticmethod
    def _scenario_context(report, as_of):
        empty = {"status": "NOT_SUPPLIED", "directional_state": "UNRESOLVED",
                 "numeric_probability": None}
        if report is None:
            return empty, None
        if not isinstance(report, Mapping) or report.get("report_type") != "CENTRAL_MULTI_DOMAIN_SCENARIO_INTELLIGENCE":
            return {**empty, "status": "REJECTED"}, "CENTRAL_SCENARIO_REPORT_INVALID"
        if as_of is None or _time(report.get("evaluated_at_utc")) != as_of:
            return {**empty, "status": "REJECTED"}, "CENTRAL_SCENARIO_CUTOFF_MISMATCH"
        assessment = report.get("directional_assessment")
        state = assessment.get("state") if isinstance(assessment, Mapping) else "UNRESOLVED"
        if state not in {"UP", "DOWN", "RANGE", "CONFLICTED", "MIXED", "UNRESOLVED"}:
            state = "UNRESOLVED"
        context, coverage = report.get("cross_domain_context"), {}
        if isinstance(context, Mapping):
            coverage = {k: v.get("status", "UNKNOWN") for k, v in context.items() if isinstance(v, Mapping)}
        return {
            "status": report.get("status", "UNKNOWN"), "directional_state": state,
            "numeric_probability": None, "scenario_hypotheses": report.get("scenario_hypotheses", []),
            "domain_coverage": coverage, "evidence_dependency_map": report.get("evidence_dependency_map", {}),
            "directional_authority_used_to_modify_forecast": False,
        }, None

    @staticmethod
    def _limits():
        return [
            "Transparent baseline extrapolation, not a trained or validated predictive model.",
            "Dispersion bands are descriptive, not calibrated prediction intervals.",
            "No numeric probability, calibrated confidence, profitability, trading signal or execution recommendation.",
            "Central scenario is comparison context only and cannot override the baseline.",
            "Correlated views are not independent confirmations; association is not causation.",
            "Out-of-sample replay and evaluation are required before model selection or confidence calibration.",
        ]

    def _empty(self, base, reason, scenario=None, warning=None):
        return {
            **base, "status": "INSUFFICIENT_EVIDENCE", "reason_codes": [reason],
            "forecasts": {k: {"status": "INSUFFICIENT_EVIDENCE", "direction": "UNRESOLVED",
                "numeric_probability": None, "calibrated_confidence": None} for k in HORIZONS},
            "scenario_context": scenario or {"status": "NOT_EVALUATED", "directional_state": "UNRESOLVED"},
            "scenario_context_warning": warning,
            "uncertainty_policy": {"bands_are_calibrated_prediction_intervals": False,
                "numeric_probabilities_emitted": False, "confidence_calibration": "PENDING_OUT_OF_SAMPLE_EVALUATION"},
            "interpretation_limits": self._limits(),
        }

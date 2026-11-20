from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
from statistics import mean, median, stdev
from typing import Any, Mapping


QUANTITATIVE_PIT_ALGORITHM_VERSION = "pit-quantitative-statistics-v1"
DEFAULT_PIP_SIZE = 0.0001
TIMEFRAME_MINUTES = {"M1": 1, "M5": 5}


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


def _quantile_nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((percentile * len(ordered) + 0.999999)) - 1))
    return ordered[index]


class PointInTimeQuantitativeStatisticsEngine:
    """Descriptive quantitative statistics over Phase 38 strict PIT spot candles.

    No network, forecast, signal, execution, or performance authority.
    """

    def __init__(
        self,
        *,
        lookback_bars: int = 250,
        minimum_bars: int = 60,
        pip_size: float = DEFAULT_PIP_SIZE,
    ) -> None:
        if isinstance(lookback_bars, bool) or not isinstance(lookback_bars, int) or lookback_bars < 3:
            raise ValueError("lookback_bars must be an integer >= 3")
        if isinstance(minimum_bars, bool) or not isinstance(minimum_bars, int) or minimum_bars < 3:
            raise ValueError("minimum_bars must be an integer >= 3")
        if minimum_bars > lookback_bars:
            raise ValueError("minimum_bars cannot exceed lookback_bars")
        parsed_pip = _number(pip_size)
        if parsed_pip is None or parsed_pip <= 0:
            raise ValueError("pip_size must be finite and positive")
        self.lookback_bars = lookback_bars
        self.minimum_bars = minimum_bars
        self.pip_size = parsed_pip

    def assess(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise TypeError("snapshot must be a unified data-plane mapping")
        as_of = _timestamp(snapshot.get("as_of_utc"))
        base = {
            "report_type": "POINT_IN_TIME_QUANTITATIVE_STATISTICS",
            "algorithm_version": QUANTITATIVE_PIT_ALGORITHM_VERSION,
            "as_of_utc": as_of.isoformat().replace("+00:00", "Z") if as_of else None,
            "snapshot_sha256": snapshot.get("snapshot_sha256"),
            "registry_sha256": snapshot.get("registry_sha256"),
            "read_mode": snapshot.get("read_mode"),
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        if as_of is None:
            return self._insufficient(base, "INVALID_OR_MISSING_AS_OF_TIMESTAMP")
        if snapshot.get("read_mode") != "STRICT_SYSTEM_KNOWLEDGE":
            return self._insufficient(base, "NON_STRICT_READ_MODE_BLOCKED")

        archive = snapshot.get("spot_market_archive")
        if not isinstance(archive, Mapping):
            return self._insufficient(base, "SPOT_MARKET_ARCHIVE_UNAVAILABLE")
        streams = archive.get("streams")
        if not isinstance(streams, list):
            return self._insufficient(base, "SPOT_STREAM_METADATA_UNAVAILABLE")

        reports: dict[str, dict[str, Any]] = {}
        exclusions: dict[str, str] = {}
        for timeframe in ("M1", "M5"):
            candidates = [
                item for item in streams
                if isinstance(item, Mapping)
                and item.get("symbol") == "EURUSD"
                and item.get("timeframe") == timeframe
            ]
            eligible = [
                item for item in candidates
                if item.get("status") == "PASS"
                and item.get("eligible_for_analytics") is True
            ]
            if len(eligible) == 0:
                exclusions[timeframe] = (
                    "NO_QUALITY_ELIGIBLE_STREAM" if candidates
                    else "STREAM_NOT_REGISTERED"
                )
                continue
            if len(eligible) != 1:
                exclusions[timeframe] = "AMBIGUOUS_MULTIPLE_ELIGIBLE_STREAMS"
                continue
            rows = eligible[0].get("candles")
            parsed, reason = self._validated_window(rows, timeframe, as_of)
            if reason:
                exclusions[timeframe] = reason
                continue
            if len(parsed) < self.minimum_bars:
                exclusions[timeframe] = "HISTORY_TOO_SHORT"
                continue
            reports[timeframe] = self._summarize(parsed, timeframe)

        if not reports:
            return {
                **base,
                "status": "INSUFFICIENT_EVIDENCE",
                "reason_codes": sorted(set(exclusions.values())) or ["NO_ELIGIBLE_PRICE_SERIES"],
                "timeframes": {},
                "excluded_timeframes": exclusions,
                "sample_policy": {
                    "minimum_bars": self.minimum_bars,
                    "lookback_bars": self.lookback_bars,
                },
                "interpretation_limits": self._limits(),
            }

        return {
            **base,
            "status": "AVAILABLE" if not exclusions else "PARTIAL",
            "timeframes": reports,
            "excluded_timeframes": exclusions,
            "sample_policy": {
                "minimum_bars": self.minimum_bars,
                "lookback_bars": self.lookback_bars,
                "pip_size": self.pip_size,
                "quantile_method": "NEAREST_RANK",
                "return_basis": "CLOSE_TO_CLOSE",
            },
            "provenance": {
                timeframe: {
                    "source_id": report["source_id"],
                    "broker_server": report["broker_server"],
                    "symbol": "EURUSD",
                    "timeframe": timeframe,
                    "price_basis": report["price_basis"],
                    "bar_time_basis": "UTC",
                    "closed_bars_only": True,
                    "candle_version_ids": report["candle_version_ids"],
                    "window_start_utc": report["window_start_utc"],
                    "window_end_utc": report["window_end_utc"],
                }
                for timeframe, report in reports.items()
            },
            "interpretation_limits": self._limits(),
        }

    def _validated_window(self, rows: Any, timeframe: str, as_of: datetime):
        if not isinstance(rows, list):
            return [], "CANDLE_HISTORY_MISSING"
        rows = rows[-self.lookback_bars:]
        duration = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        parsed = []
        previous_open = None
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("values"), Mapping):
                return [], "CANDLE_RECORD_INVALID"
            opened = _timestamp(row.get("candle_open_time_utc"))
            observed = _timestamp(row.get("observed_at_utc"))
            cutoff = _timestamp(row.get("as_of_utc"))
            values = row["values"]
            o, h, low, close = (_number(values.get(k)) for k in ("open", "high", "low", "close"))
            if (opened is None or observed is None or cutoff is None
                    or any(v is None for v in (o, h, low, close))):
                return [], "CANDLE_FIELDS_INVALID"
            if observed > as_of or cutoff > as_of or opened + duration > as_of:
                return [], "FUTURE_OR_FORMING_CANDLE"
            if previous_open is not None:
                delta = opened - previous_open
                if delta <= timedelta(0):
                    return [], "CANDLE_ORDER_INVALID"
                if delta != duration:
                    return [], "CANDLE_HISTORY_GAP"
            if h < max(o, low, close) or low > min(o, h, close):
                return [], "INVALID_OHLC_BOUNDS"
            if not row.get("version_id"):
                return [], "CANDLE_VERSION_ID_MISSING"
            if row.get("source_id") not in {"MT5_COPY_RATES", "MT5_COPY_RATES_RANGE"}:
                return [], "UNVERIFIED_CANDLE_SOURCE"
            provenance = row.get("provenance")
            if not isinstance(provenance, Mapping):
                return [], "CANDLE_PROVENANCE_MISSING"
            basis = provenance.get("price_basis")
            if isinstance(basis, Mapping):
                basis = basis.get("price_basis")
            if basis not in {"BID", "LAST"} or provenance.get("bar_time_basis") != "UTC":
                return [], "PRICE_OR_TIME_BASIS_UNVERIFIED"
            parsed.append({
                "open": o, "high": h, "low": low, "close": close,
                "open_time": opened,
                "close_time": opened + duration,
                "version_id": row["version_id"],
                "source_id": row["source_id"],
                "broker_server": row.get("broker_server"),
                "price_basis": basis,
            })
            previous_open = opened
        if not parsed:
            return [], "CANDLE_HISTORY_EMPTY"
        return parsed, None

    def _summarize(self, candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
        closes = [item["close"] for item in candles]
        returns = [
            (right - left) / self.pip_size
            for left, right in zip(closes, closes[1:])
        ]
        if not returns or not all(isfinite(value) for value in returns):
            raise ValueError("non-finite return series")
        absolute = [abs(value) for value in returns]
        q05 = _quantile_nearest_rank(returns, 0.05)
        q01 = _quantile_nearest_rank(returns, 0.01)
        tail05 = [value for value in returns if value <= q05]
        tail01 = [value for value in returns if value <= q01]
        mean_return = mean(returns)
        volatility = stdev(returns) if len(returns) > 1 else 0.0
        downside = [min(value, 0.0) for value in returns]
        upside = [max(value, 0.0) for value in returns]
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in returns:
            equity += value
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        lag_pairs = list(zip(returns[:-1], returns[1:]))
        lag1 = self._correlation(
            [pair[0] for pair in lag_pairs],
            [pair[1] for pair in lag_pairs],
        )
        true_ranges = []
        for index, candle in enumerate(candles):
            previous_close = closes[index - 1] if index else candle["open"]
            true_ranges.append(max(
                candle["high"] - candle["low"],
                abs(candle["high"] - previous_close),
                abs(candle["low"] - previous_close),
            ) / self.pip_size)
        return {
            "sample_size": {
                "candles": len(candles),
                "close_to_close_returns": len(returns),
            },
            "returns_pips": {
                "mean": self._round(mean_return),
                "median": self._round(median(returns)),
                "sample_stddev": self._round(volatility),
                "minimum": self._round(min(returns)),
                "maximum": self._round(max(returns)),
                "p01": self._round(_quantile_nearest_rank(returns, 0.01)),
                "p05": self._round(q05),
                "p25": self._round(_quantile_nearest_rank(returns, 0.25)),
                "p75": self._round(_quantile_nearest_rank(returns, 0.75)),
                "p95": self._round(_quantile_nearest_rank(returns, 0.95)),
                "p99": self._round(_quantile_nearest_rank(returns, 0.99)),
                "positive_pct": self._round(100 * sum(v > 0 for v in returns) / len(returns)),
                "negative_pct": self._round(100 * sum(v < 0 for v in returns) / len(returns)),
                "zero_pct": self._round(100 * sum(v == 0 for v in returns) / len(returns)),
            },
            "realized_risk": {
                "realized_volatility_pips": self._round(sqrt(sum(v * v for v in returns))),
                "mean_absolute_return_pips": self._round(mean(absolute)),
                "downside_semideviation_pips": self._round(sqrt(mean(v * v for v in downside))),
                "upside_semideviation_pips": self._round(sqrt(mean(v * v for v in upside))),
                "historical_var_95_loss_pips": self._round(max(0.0, -q05)),
                "historical_var_99_loss_pips": self._round(max(0.0, -q01)),
                "historical_expected_shortfall_95_pips": self._round(max(0.0, -mean(tail05))),
                "historical_expected_shortfall_99_pips": self._round(max(0.0, -mean(tail01))),
                "maximum_close_to_close_drawdown_pips": self._round(max_drawdown),
                "mean_true_range_pips": self._round(mean(true_ranges)),
                "p95_true_range_pips": self._round(_quantile_nearest_rank(true_ranges, 0.95)),
            },
            "dependence": {
                "lag1_return_autocorrelation": self._round(lag1) if lag1 is not None else None,
                "sign_persistence_pct": self._round(
                    100 * sum((a > 0 and b > 0) or (a < 0 and b < 0)
                              for a, b in lag_pairs) / len(lag_pairs)
                ) if lag_pairs else None,
            },
            "window_start_utc": candles[0]["open_time"].isoformat().replace("+00:00", "Z"),
            "window_end_utc": candles[-1]["close_time"].isoformat().replace("+00:00", "Z"),
            "candle_version_ids": [item["version_id"] for item in candles],
            "source_id": candles[-1]["source_id"],
            "broker_server": candles[-1]["broker_server"],
            "price_basis": candles[-1]["price_basis"],
        }

    @staticmethod
    def _correlation(left: list[float], right: list[float]) -> float | None:
        if len(left) < 2:
            return None
        left_mean, right_mean = mean(left), mean(right)
        left_var = sum((v - left_mean) ** 2 for v in left)
        right_var = sum((v - right_mean) ** 2 for v in right)
        denominator = sqrt(left_var * right_var)
        if denominator == 0:
            return None
        result = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / denominator
        return result if isfinite(result) else None

    @staticmethod
    def _round(value: float) -> float:
        if not isfinite(value):
            raise ValueError("statistic must be finite")
        return round(value, 8)

    @staticmethod
    def _limits() -> list[str]:
        return [
            "Statistics describe the supplied historical sample; they are not forecasts or calibrated probabilities.",
            "Historical VaR and expected shortfall are empirical sample summaries, not guarantees or forward risk limits.",
            "Close-to-close drawdown is not an intrabar or executable trading drawdown.",
            "M1 and M5 are overlapping, dependent views and must not be pooled as independent samples.",
            "No strategy profitability, win rate, entry/exit quality, or execution performance is inferred.",
            "Only strict system-knowledge point-in-time, quality-eligible, closed and versioned EURUSD spot candles are accepted.",
        ]

    @staticmethod
    def _insufficient(base: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            **base,
            "status": "INSUFFICIENT_EVIDENCE",
            "reason_codes": [reason],
            "timeframes": {},
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

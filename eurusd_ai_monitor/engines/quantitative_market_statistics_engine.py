from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.market_data_store import Candle, TIMEFRAME_SECONDS


QUANTITATIVE_ALGORITHM_VERSION = "quantitative-market-statistics-v1"


@dataclass(frozen=True)
class QuantitativeThresholds:
    lookback_bars: int = 120
    minimum_bars: int = 30
    pip_size: Decimal = Decimal("0.0001")

    def __post_init__(self) -> None:
        for name in ("lookback_bars", "minimum_bars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                raise ValueError(f"{name} must be an integer >= 2")
        if self.minimum_bars > self.lookback_bars:
            raise ValueError("minimum_bars cannot exceed lookback_bars")
        try:
            pip = self.pip_size if isinstance(self.pip_size, Decimal) else Decimal(str(self.pip_size))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("pip_size must be a finite positive decimal") from exc
        if not pip.is_finite() or pip <= 0:
            raise ValueError("pip_size must be finite and positive")
        object.__setattr__(self, "pip_size", pip)


class QuantitativeMarketStatisticsEngine:
    """Deterministic descriptive market statistics over closed M1/M5 candles.

    This specialist measures distributions and realized price behavior. It does
    not forecast, infer trade probabilities, or authorize a trading decision.
    """

    def __init__(self, thresholds: QuantitativeThresholds | None = None) -> None:
        if thresholds is not None and not isinstance(thresholds, QuantitativeThresholds):
            raise TypeError("thresholds must be QuantitativeThresholds or None")
        self._thresholds = thresholds or QuantitativeThresholds()

    def assess(self, snapshot: MarketSnapshot) -> dict[str, Any]:
        if not isinstance(snapshot, MarketSnapshot):
            raise TypeError("snapshot must be a MarketSnapshot")
        base = {
            "report_type": "QUANTITATIVE_MARKET_STATISTICS",
            "algorithm_version": QUANTITATIVE_ALGORITHM_VERSION,
            "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
            "broker_server": snapshot.broker_server,
            "symbol": snapshot.symbol,
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        if not snapshot.quality.is_valid:
            return self._unavailable(
                base, "BLOCKED", "MARKET_CONTEXT_QUALITY_FAILED",
                quality_issues=list(snapshot.quality.issues),
            )

        reports: dict[str, Any] = {}
        for timeframe, candles in (("M1", snapshot.m1_candles), ("M5", snapshot.m5_candles)):
            reason = self._validate_series(candles, timeframe, snapshot)
            if reason:
                return self._unavailable(
                    base, "DEGRADED", reason, timeframe=timeframe
                )
            window = tuple(candles[-self._thresholds.lookback_bars:])
            if len(window) < self._thresholds.minimum_bars:
                return self._unavailable(
                    base, "INSUFFICIENT_DATA", f"{timeframe}_HISTORY_TOO_SHORT",
                    timeframe=timeframe,
                    required_bars=self._thresholds.minimum_bars,
                    available_bars=len(window),
                )
            reports[timeframe] = self._summarize(window, timeframe)

        return {
            **base,
            "status": "AVAILABLE",
            "status_reason": "BOTH_TIMEFRAMES_VALID",
            "timeframes": reports,
            "provenance": {
                "source": snapshot.source,
                "m1_candle_ids": reports["M1"]["candle_ids"],
                "m5_candle_ids": reports["M5"]["candle_ids"],
                "closed_bars_only": True,
            },
            "interpretation_limits": [
                "All values are descriptive statistics of the supplied closed-candle windows.",
                "Realized volatility is not a forecast or implied volatility.",
                "Return frequencies and quantiles are empirical sample descriptions, not calibrated probabilities.",
                "M1 and M5 windows are separate observations and must not be treated as independent samples.",
                "No directional signal, strategy profitability, entry, exit, position size, or execution authority is produced.",
            ],
        }

    def _validate_series(self, candles: tuple[Candle, ...], timeframe: str,
                         snapshot: MarketSnapshot) -> str | None:
        if not candles:
            return f"{timeframe}_SERIES_EMPTY"
        previous = None
        duration = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
        for candle in candles:
            if not isinstance(candle, Candle) or candle.timeframe != timeframe:
                return f"{timeframe}_CANDLE_TYPE_OR_TIMEFRAME_INVALID"
            if candle.symbol != snapshot.symbol or candle.broker_server != snapshot.broker_server:
                return f"{timeframe}_CANDLE_IDENTITY_MISMATCH"
            opened = candle.candle_open_time_utc
            if previous is not None and opened <= previous:
                return f"{timeframe}_CANDLE_ORDER_INVALID"
            if opened + duration > snapshot.timestamp_utc:
                return f"{timeframe}_FORMING_OR_FUTURE_CANDLE"
            previous = opened
        return None

    def _summarize(self, candles: tuple[Candle, ...], timeframe: str) -> dict[str, Any]:
        pip = self._thresholds.pip_size
        closes = [c.close for c in candles]
        returns = [(right - left) / pip for left, right in zip(closes, closes[1:])]
        true_ranges = []
        for index, candle in enumerate(candles):
            previous_close = closes[index - 1] if index else candle.open
            true_range = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
            true_ranges.append(true_range / pip)
        ranges = [(c.high - c.low) / pip for c in candles]
        path = sum((abs(value) for value in returns), Decimal("0"))
        displacement = abs(closes[-1] - closes[0]) / pip
        efficiency = Decimal("0") if path == 0 else min(Decimal("1"), displacement / path)
        positive = sum(value > 0 for value in returns)
        negative = sum(value < 0 for value in returns)
        zero = len(returns) - positive - negative

        return {
            "timeframe": timeframe,
            "candle_count": len(candles),
            "return_count": len(returns),
            "return_distribution_pips": self._distribution(returns),
            "positive_return_pct": self._percent(positive, len(returns)),
            "negative_return_pct": self._percent(negative, len(returns)),
            "zero_return_pct": self._percent(zero, len(returns)),
            "candle_range_pips": self._distribution(ranges),
            "true_range_pips": self._distribution(true_ranges),
            "directional_efficiency_ratio": self._number(efficiency),
            "window_start_utc": candles[0].candle_open_time_utc.isoformat(),
            "window_end_utc": (
                candles[-1].candle_open_time_utc
                + timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
            ).isoformat(),
            "candle_ids": [self._candle_id(c) for c in candles],
        }

    @classmethod
    def _distribution(cls, values: list[Decimal]) -> dict[str, str]:
        if not values:
            return {"sample_size": "0"}
        ordered = sorted(values)
        count = len(ordered)
        mean = sum(ordered, Decimal("0")) / Decimal(count)
        if count > 1:
            variance = sum(((item - mean) ** 2 for item in ordered), Decimal("0")) / Decimal(count - 1)
            stddev = variance.sqrt()
        else:
            stddev = Decimal("0")

        def nearest_rank(percent: int) -> Decimal:
            index = max(0, (percent * count + 99) // 100 - 1)
            return ordered[index]

        middle = count // 2
        median = (ordered[middle] if count % 2 else
                  (ordered[middle - 1] + ordered[middle]) / Decimal("2"))
        return {
            "sample_size": str(count),
            "mean": cls._number(mean),
            "median": cls._number(median),
            "sample_stddev": cls._number(stddev),
            "p05": cls._number(nearest_rank(5)),
            "p25": cls._number(nearest_rank(25)),
            "p75": cls._number(nearest_rank(75)),
            "p95": cls._number(nearest_rank(95)),
            "min": cls._number(ordered[0]),
            "max": cls._number(ordered[-1]),
        }

    @staticmethod
    def _percent(count: int, total: int) -> str:
        return "0" if total == 0 else format(
            (Decimal(count) * Decimal("100") / Decimal(total)).normalize(), "f"
        )

    @staticmethod
    def _number(value: Decimal) -> str:
        if not value.is_finite():
            raise ValueError("statistic must be finite")
        return format(value.normalize(), "f")

    @staticmethod
    def _candle_id(candle: Candle) -> str:
        timestamp = candle.candle_open_time_utc.astimezone(timezone.utc)
        return (
            f"{candle.broker_server}|{candle.symbol}|{candle.timeframe}|"
            + timestamp.isoformat().replace("+00:00", "Z")
        )

    @staticmethod
    def _unavailable(base: dict, status: str, reason: str, **details) -> dict:
        return {
            **base,
            "status": status,
            "reason_codes": [reason],
            **details,
        }

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from decimal import Decimal
from math import isfinite
from typing import Any

from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.market_data_store import TIMEFRAME_SECONDS

REGIME_ALGORITHM_VERSION = "market-regime-m5-m1-v1"


@dataclass(frozen=True)
class RegimeThresholds:
    lookback_bars: int = 20
    atr_period: int = 14
    baseline_bars: int = 50
    trending_efficiency_min: float = 0.35
    ranging_efficiency_max: float = 0.20
    high_volatility_ratio: float = 1.50
    low_volatility_ratio: float = 0.65

    def __post_init__(self):
        for name in ("lookback_bars", "atr_period", "baseline_bars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("trending_efficiency_min", "ranging_efficiency_max",
                     "high_volatility_ratio", "low_volatility_ratio"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0 <= self.ranging_efficiency_max < self.trending_efficiency_min <= 1:
            raise ValueError("efficiency thresholds must satisfy 0 <= ranging < trending <= 1")
        if not 0 < self.low_volatility_ratio < 1 < self.high_volatility_ratio:
            raise ValueError("volatility thresholds must straddle 1")


class MarketRegimeEngine:
    """Deterministic, closed-candle regime assessment; never emits a trade signal."""

    def __init__(self, *, pip_size: Decimal | str = Decimal("0.0001"),
                 thresholds: RegimeThresholds | None = None):
        self._pip_size = pip_size if isinstance(pip_size, Decimal) else Decimal(str(pip_size))
        if not self._pip_size.is_finite() or self._pip_size <= 0:
            raise ValueError("pip_size must be finite and positive")
        self._thresholds = thresholds or RegimeThresholds()

    def assess(self, snapshot: MarketSnapshot, technical_structure: Any | None = None) -> dict:
        base = {
            "report_type": "MARKET_REGIME_ASSESSMENT",
            "algorithm_version": REGIME_ALGORITHM_VERSION,
            "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        if not snapshot.quality.is_valid:
            return self._unavailable(base, "BLOCKED", "MARKET_CONTEXT_QUALITY_FAILED")
        m5, m1 = tuple(snapshot.m5_candles), tuple(snapshot.m1_candles)
        if not self._valid_closed_series(m5, "M5", snapshot):
            return self._unavailable(base, "DEGRADED", "M5_CLOSED_CANDLE_SERIES_INVALID")
        t = self._thresholds
        required = t.baseline_bars + t.lookback_bars + 1
        if len(m5) < required:
            return self._unavailable(base, "INSUFFICIENT_DATA", "M5_HISTORY_TOO_SHORT",
                                     required_m5_bars=required, available_m5_bars=len(m5))

        recent = m5[-t.lookback_bars:]
        previous = m5[-2 * t.lookback_bars:-t.lookback_bars]
        atr_recent = self._atr(m5[-t.atr_period:], m5[-t.atr_period - 1])
        baseline_start = len(m5) - t.atr_period - t.baseline_bars
        baseline_candles = m5[baseline_start:len(m5) - t.atr_period]
        atr_baseline = self._atr(baseline_candles, m5[baseline_start - 1])
        if atr_baseline <= 0:
            return self._unavailable(base, "DEGRADED", "ATR_BASELINE_NOT_POSITIVE")
        volatility_ratio = atr_recent / atr_baseline
        efficiency = self._efficiency(recent)
        previous_efficiency = self._efficiency(previous)
        direction = self._trend_direction(technical_structure)
        structure_break = bool(technical_structure is not None and
                               getattr(technical_structure, "protected_swing_break", None) is not None)

        if structure_break:
            regime, reason = "TRANSITIONAL", "PROTECTED_STRUCTURE_BREAK"
        elif efficiency >= t.trending_efficiency_min and direction in {"UP", "DOWN"}:
            regime, reason = "TRENDING", "DIRECTIONAL_EFFICIENCY_AND_M5_STRUCTURE_AGREE"
        elif efficiency <= t.ranging_efficiency_max:
            regime, reason = "RANGING", "LOW_DIRECTIONAL_EFFICIENCY"
        else:
            regime, reason = "TRANSITIONAL", "EFFICIENCY_IN_TRANSITION_BAND"

        volatility = ("HIGH" if volatility_ratio >= t.high_volatility_ratio else
                      "LOW" if volatility_ratio <= t.low_volatility_ratio else "NORMAL")
        flags = []
        if structure_break:
            flags.append("STRUCTURE_BREAK_CONFIRMED")
        if volatility == "HIGH":
            flags.append("VOLATILITY_EXPANSION")
        elif volatility == "LOW":
            flags.append("VOLATILITY_CONTRACTION")
        if efficiency >= t.trending_efficiency_min and previous_efficiency <= t.ranging_efficiency_max:
            flags.append("RANGE_TO_TREND_CANDIDATE")
        alignment = self._m1_alignment(m1, snapshot, direction)

        return {
            **base, "status": "AVAILABLE", "regime": regime, "trend_direction": direction,
            "volatility_state": volatility, "lower_timeframe_alignment": alignment,
            "regime_reason": reason, "transition_flags": flags,
            "features": {
                "directional_efficiency_ratio": self._number(efficiency),
                "previous_efficiency_ratio": self._number(previous_efficiency),
                "atr_pips": self._number(atr_recent / float(self._pip_size)),
                "baseline_atr_pips": self._number(atr_baseline / float(self._pip_size)),
                "atr_expansion_ratio": self._number(volatility_ratio),
            },
            "thresholds": {
                "trending_efficiency_min": t.trending_efficiency_min,
                "ranging_efficiency_max": t.ranging_efficiency_max,
                "high_volatility_ratio": t.high_volatility_ratio,
                "low_volatility_ratio": t.low_volatility_ratio,
                "lookback_bars": t.lookback_bars, "atr_period": t.atr_period,
                "baseline_bars": t.baseline_bars,
            },
            "provenance": {
                "symbol": snapshot.symbol, "broker_server": snapshot.broker_server,
                "timeframe": "M5",
                "m5_window_start_utc": recent[0].candle_open_time_utc.isoformat(),
                "m5_window_end_utc": (recent[-1].candle_open_time_utc +
                    timedelta(seconds=TIMEFRAME_SECONDS["M5"])).isoformat(),
                "m5_candle_ids": [self._candle_id(c) for c in recent],
                "m1_confirmation_candle_ids": [
                    self._candle_id(c) for c in m1[-t.lookback_bars:]
                ] if alignment != "UNAVAILABLE" else [],
                "m1_window_end_utc": (
                    m1[-1].candle_open_time_utc +
                    timedelta(seconds=TIMEFRAME_SECONDS["M1"])
                ).isoformat() if alignment != "UNAVAILABLE" else None,
                "m1_is_context_only": True,
            },
            "interpretation_limits": [
                "Regime labels are deterministic descriptive classifications, not probabilities.",
                "M5 structure remains the sole trend-direction authority; M1 alignment is context-only.",
                "ATR expansion is relative to the supplied recent baseline, not a forecast.",
                "A range-to-trend candidate is a transition flag, not a breakout or entry signal.",
                "No regime label authorizes entries, exits, position sizing, or strategy changes.",
            ],
        }

    @staticmethod
    def _valid_closed_series(candles, timeframe, snapshot):
        if not candles:
            return False
        duration = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
        previous_open = None
        for candle in candles:
            opened = candle.candle_open_time_utc
            if candle.timeframe != timeframe or opened.tzinfo is None or opened.utcoffset() is None:
                return False
            if previous_open is not None and opened <= previous_open:
                return False
            if opened + duration > snapshot.timestamp_utc:
                return False
            previous_open = opened
        return True

    @staticmethod
    def _atr(candles, preceding_candle):
        previous_close = float(preceding_candle.close)
        ranges = []
        for candle in candles:
            high, low, close = float(candle.high), float(candle.low), float(candle.close)
            ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
            previous_close = close
        return sum(ranges) / len(ranges)

    @staticmethod
    def _efficiency(candles):
        closes = [float(c.close) for c in candles]
        path = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
        return 0.0 if path <= 0 else min(1.0, abs(closes[-1] - closes[0]) / path)

    @staticmethod
    def _trend_direction(structure):
        trend = getattr(structure, "trend", None) if structure is not None else None
        direction = getattr(trend, "direction", None)
        value = getattr(direction, "value", direction)
        return value if value in {"UP", "DOWN"} else "UNKNOWN"

    def _m1_alignment(self, candles, snapshot, direction):
        if direction not in {"UP", "DOWN"} or len(candles) < self._thresholds.lookback_bars:
            return "UNAVAILABLE"
        if not self._valid_closed_series(candles, "M1", snapshot):
            return "UNAVAILABLE"
        recent = candles[-self._thresholds.lookback_bars:]
        displacement = float(recent[-1].close) - float(recent[0].close)
        if abs(displacement) <= float(self._pip_size) * 0.1:
            return "NEUTRAL"
        return "ALIGNED" if ((displacement > 0) == (direction == "UP")) else "OPPOSED"

    @staticmethod
    def _candle_id(candle):
        return (f"{candle.broker_server}|{candle.symbol}|{candle.timeframe}|" +
                candle.candle_open_time_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))

    @staticmethod
    def _number(value):
        return format(Decimal(str(value)).normalize(), "f")

    @staticmethod
    def _unavailable(base, status, reason, **details):
        return {**base, "status": status, "regime": "UNKNOWN", "trend_direction": "UNKNOWN",
                "volatility_state": "UNKNOWN", "lower_timeframe_alignment": "UNAVAILABLE",
                "reason_codes": [reason], **details}

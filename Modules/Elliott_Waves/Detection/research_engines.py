"""Independent research components for alternative Elliott swing analysis.

This module is a clean-room implementation for EURUSD-AI. It does not copy
third-party source code. All pivots are timestamped at the candle where the
reversal becomes knowable, while retaining the time of the price extreme.
Wave diagnostics report measured ratios; they do not impose Fibonacci cutoffs.
"""
from __future__ import annotations

from typing import Sequence

from eurusd_ai.market_data import Candle
from .detector import Pivot


def _true_ranges(candles: Sequence[Candle]) -> list[float]:
    values: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        if previous_close is None:
            tr = candle.high - candle.low
        else:
            tr = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        values.append(tr)
        previous_close = candle.close
    return values


def wilder_atr(candles: Sequence[Candle], period: int = 14) -> list[float | None]:
    """Return causal Wilder ATR values; entries before the seed are None."""
    if period < 1:
        raise ValueError("period must be >= 1")
    if not candles:
        return []
    true_ranges = _true_ranges(candles)
    atr: list[float | None] = [None] * len(candles)
    if len(candles) < period:
        return atr
    current = sum(true_ranges[:period]) / period
    atr[period - 1] = current
    for i in range(period, len(candles)):
        current = ((current * (period - 1)) + true_ranges[i]) / period
        atr[i] = current
    return atr


def detect_atr_pivots(
    candles: Sequence[Candle],
    atr_period: int = 14,
    atr_multiplier: float = 1.5,
    min_bars: int = 2,
    include_provisional: bool = False,
) -> list[Pivot]:
    """Detect ATR-reversal pivots with explicit, causal confirmation timestamps.

    A pivot's time is the timestamp of its extreme. confirmation_time is the
    close time of the candle that first confirms the ATR-sized reversal.
    No pivot is marked confirmed before that confirmation candle.
    """
    if atr_multiplier <= 0 or min_bars < 1:
        raise ValueError("atr_multiplier must be > 0 and min_bars >= 1")
    if len(candles) < max(2, atr_period):
        return []

    atr = wilder_atr(candles, atr_period)
    first = atr_period - 1
    high_i = low_i = first
    high = candles[first].high
    low = candles[first].low
    direction = 0
    pivots: list[Pivot] = []

    for i in range(first + 1, len(candles)):
        candle = candles[i]
        threshold = float(atr[i] or 0.0) * atr_multiplier
        if threshold <= 0:
            continue

        if direction == 0:
            if candle.high >= high:
                high_i, high = i, candle.high
            if candle.low <= low:
                low_i, low = i, candle.low
            if high - low >= threshold:
                if high_i < low_i:
                    pivots.append(Pivot(high_i, candles[high_i].time, high, "H", True, i, candle.time))
                    direction = -1
                    low_i, low = i, candle.low
                elif low_i < high_i:
                    pivots.append(Pivot(low_i, candles[low_i].time, low, "L", True, i, candle.time))
                    direction = 1
                    high_i, high = i, candle.high
        elif direction > 0:
            if candle.high >= high:
                high_i, high = i, candle.high
            if i - high_i >= min_bars and high - candle.low >= threshold:
                pivots.append(Pivot(high_i, candles[high_i].time, high, "H", True, i, candle.time))
                direction = -1
                low_i, low = i, candle.low
        else:
            if candle.low <= low:
                low_i, low = i, candle.low
            if i - low_i >= min_bars and candle.high - low >= threshold:
                pivots.append(Pivot(low_i, candles[low_i].time, low, "L", True, i, candle.time))
                direction = 1
                high_i, high = i, candle.high

    if include_provisional and direction:
        if direction > 0:
            pivots.append(Pivot(high_i, candles[high_i].time, high, "H", False, None, None))
        else:
            pivots.append(Pivot(low_i, candles[low_i].time, low, "L", False, None, None))

    result: list[Pivot] = []
    for pivot in pivots:
        if not result or pivot.index > result[-1].index:
            if not result or pivot.kind != result[-1].kind:
                result.append(pivot)
    return result


def measure_wave_structure(
    pivots: Sequence[Pivot],
    pip_size: float = 0.0001,
) -> dict[str, object]:
    """Measure an impulse (six pivots) or ABC (four pivots) without Fib filters.

    Ratios are raw observed price-length ratios. The function deliberately
    reports measurements and rule diagnostics separately from any probability.
    """
    if pip_size <= 0:
        raise ValueError("pip_size must be > 0")
    if len(pivots) not in (4, 6):
        raise ValueError("expected 4 pivots for ABC or 6 pivots for impulse")
    if any(pivots[i].kind == pivots[i + 1].kind for i in range(len(pivots) - 1)):
        raise ValueError("pivot kinds must alternate")
    legs = [pivots[i + 1].price - pivots[i].price for i in range(len(pivots) - 1)]
    lengths = [abs(x) / pip_size for x in legs]
    direction = 1 if legs[0] > 0 else -1
    bars = [pivots[i + 1].index - pivots[i].index for i in range(len(pivots) - 1)]

    if len(pivots) == 4:
        a, b, c = lengths
        return {
            "pattern": "abc_measurement",
            "direction": "up" if direction > 0 else "down",
            "leg_pips": {"A": round(a, 4), "B": round(b, 4), "C": round(c, 4)},
            "retracement_B_vs_A": b / a if a else None,
            "extension_C_vs_A": c / a if a else None,
            "duration_bars": {"A": bars[0], "B": bars[1], "C": bars[2]},
            "hard_valid": None,
            "reasons": ["ABC lengths are measured; subtype is not inferred from ratios alone."],
        }

    w1, w2, w3, w4, w5 = lengths
    eps = pip_size * 0.05
    hard_checks = {
        "wave2_does_not_break_wave1_origin": (pivots[2].price - pivots[0].price) * direction > eps,
        "wave3_passes_wave1_end": (pivots[3].price - pivots[1].price) * direction > eps,
        "wave3_not_shortest_motive_wave": w3 + 0.05 >= min(w1, w5),
        "wave4_no_wave1_overlap": (
            pivots[4].price > pivots[1].price + eps
            if direction > 0 else pivots[4].price < pivots[1].price - eps
        ),
        "alternating_impulse_leg_directions": all(
            legs[i] * direction > 0 if i % 2 == 0 else legs[i] * direction < 0
            for i in range(5)
        ),
    }
    return {
        "pattern": "impulse_measurement",
        "direction": "up" if direction > 0 else "down",
        "leg_pips": {f"W{i + 1}": round(value, 4) for i, value in enumerate(lengths)},
        "retracement_W2_vs_W1": w2 / w1 if w1 else None,
        "retracement_W4_vs_W3": w4 / w3 if w3 else None,
        "extension_W3_vs_W1": w3 / w1 if w1 else None,
        "extension_W5_vs_W1": w5 / w1 if w1 else None,
        "duration_bars": {f"W{i + 1}": value for i, value in enumerate(bars)},
        "hard_checks": hard_checks,
        "hard_valid": all(hard_checks.values()),
        "reasons": [name for name, passed in hard_checks.items() if not passed],
    }

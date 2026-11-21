"""Multi-scale, causally confirmed ZigZag pivots for Elliott Wave research."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence
from eurusd_ai.market_data import Candle

@dataclass(frozen=True)
class Pivot:
    index: int
    time: str                 # time of the price extreme (not when it became knowable)
    price: float
    kind: str                 # H or L
    confirmed: bool = True
    confirmation_index: int | None = None
    confirmation_time: str | None = None

def _known_at(candle: Candle, delay_seconds: int) -> str:
    if delay_seconds <= 0:
        return candle.time
    try:
        return (datetime.fromisoformat(candle.time.replace("Z", "+00:00")) + timedelta(seconds=delay_seconds)).isoformat()
    except ValueError:
        return candle.time

def detect_pivots(candles: Sequence[Candle], min_leg_pips: float = 5.0,
                  pip_size: float = 0.0001, include_provisional: bool = False,
                  confirmation_delay_seconds: int = 0) -> list[Pivot]:
    """Directional-change pivots; availability is at the confirming candle close."""
    if min_leg_pips <= 0 or pip_size <= 0 or confirmation_delay_seconds < 0:
        raise ValueError("thresholds must be positive and confirmation delay non-negative")
    if len(candles) < 2:
        return []
    threshold = min_leg_pips * pip_size
    pivots: list[Pivot] = []
    direction = 0
    high_i, high = 0, candles[0].high
    low_i, low = 0, candles[0].low
    for i, candle in enumerate(candles[1:], 1):
        if direction == 0:
            if candle.high >= high:
                high_i, high = i, candle.high
            if candle.low <= low:
                low_i, low = i, candle.low
            if high - low >= threshold and high_i != low_i:
                if high_i < low_i:
                    pivots.append(Pivot(high_i, candles[high_i].time, high, "H", True, i, _known_at(candle, confirmation_delay_seconds)))
                    direction = -1
                    low_i, low = i, candle.low
                else:
                    pivots.append(Pivot(low_i, candles[low_i].time, low, "L", True, i, _known_at(candle, confirmation_delay_seconds)))
                    direction = 1
                    high_i, high = i, candle.high
        elif direction == 1:
            if candle.high >= high:
                high_i, high = i, candle.high
            if high - candle.low >= threshold:
                pivots.append(Pivot(high_i, candles[high_i].time, high, "H", True, i, _known_at(candle, confirmation_delay_seconds)))
                direction = -1
                low_i, low = i, candle.low
        else:
            if candle.low <= low:
                low_i, low = i, candle.low
            if candle.high - low >= threshold:
                pivots.append(Pivot(low_i, candles[low_i].time, low, "L", True, i, _known_at(candle, confirmation_delay_seconds)))
                direction = 1
                high_i, high = i, candle.high
    if include_provisional and direction:
        if direction == 1:
            pivots.append(Pivot(high_i, candles[high_i].time, high, "H", False, None, None))
        else:
            pivots.append(Pivot(low_i, candles[low_i].time, low, "L", False, None, None))
    result: list[Pivot] = []
    for pivot in pivots:
        if not result or pivot.index > result[-1].index:
            result.append(pivot)
    return result

def find_five_wave_candidates(pivots: Sequence[Pivot]) -> list[tuple[Pivot, ...]]:
    """Compatibility API: geometrically valid rolling six-pivot impulses."""
    from .engine import ElliottEngine
    return [c.pivots for c in ElliottEngine().analyze_pivots(pivots)
            if c.pattern == "impulse" and c.hard_valid]

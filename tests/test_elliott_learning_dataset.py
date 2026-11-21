from eurusd_ai.market_data import Candle
from Modules.Elliott_Waves.Detection.detector import detect_pivots


def test_pivot_has_separate_confirmation_time_and_no_provisional_label():
    prices = [1.1000, 1.1010, 1.1020, 1.1010, 1.1000, 1.0990, 1.1000, 1.1015]
    candles = [Candle(f"2026-01-01T00:{i:02d}:00+00:00", p, p + 0.00005, p - 0.00005, p, 1) for i, p in enumerate(prices)]
    pivots = detect_pivots(candles, min_leg_pips=10, include_provisional=False)
    assert pivots
    assert all(p.confirmed and p.confirmation_time for p in pivots)
    assert all(p.confirmation_index >= p.index for p in pivots)
    assert any(p.confirmation_index > p.index for p in pivots)


def test_provisional_pivot_has_no_confirmation_timestamp():
    candles = [Candle(str(i), p, p + 0.00005, p - 0.00005, p, 1)
               for i, p in enumerate([1.1000, 1.1010, 1.1020, 1.1010])]
    pivots = detect_pivots(candles, min_leg_pips=10, include_provisional=True)
    provisional = [p for p in pivots if not p.confirmed]
    assert provisional
    assert provisional[-1].confirmation_time is None


def test_confirmation_availability_is_after_bucket_open():
    from datetime import datetime
    candles = [Candle(f"2026-01-01T00:{i:02d}:00+00:00", p, p + 0.00005, p - 0.00005, p, 1)
               for i, p in enumerate([1.1000, 1.1010, 1.1020, 1.1010, 1.1000, 1.0990, 1.1000, 1.1015])]
    pivots = detect_pivots(candles, min_leg_pips=10, confirmation_delay_seconds=60)
    assert pivots
    for pivot in pivots:
        known = datetime.fromisoformat(pivot.confirmation_time)
        candle_open = datetime.fromisoformat(candles[pivot.confirmation_index].time)
        assert (known - candle_open).total_seconds() == 60

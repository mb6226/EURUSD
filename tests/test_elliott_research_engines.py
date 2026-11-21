from eurusd_ai.market_data import Candle
from Modules.Elliott_Waves.Detection.detector import Pivot
from Modules.Elliott_Waves.Detection.research_engines import (
    detect_atr_pivots,
    measure_wave_structure,
    wilder_atr,
)


def _candles(prices):
    return [
        Candle(str(i), p, p + 0.0001, p - 0.0001, p, 1.0)
        for i, p in enumerate(prices)
    ]


def test_wilder_atr_is_causal_and_seeded_after_period():
    candles = _candles([1.1000, 1.1010, 1.1005, 1.1020, 1.1010])
    values = wilder_atr(candles, period=3)
    assert values[:2] == [None, None]
    assert values[2] is not None
    assert values[3] is not None


def test_atr_pivots_have_later_confirmation_time():
    prices = [
        1.1000, 1.1010, 1.1020, 1.1030, 1.1025, 1.1020,
        1.1010, 1.1000, 1.0990, 1.1000, 1.1010, 1.1020,
    ]
    pivots = detect_atr_pivots(_candles(prices), atr_period=2, atr_multiplier=1.0, min_bars=1)
    assert len(pivots) >= 2
    assert all(p.confirmed for p in pivots)
    assert all(p.confirmation_index is not None and p.confirmation_index > p.index for p in pivots)
    assert all(p.confirmation_time is not None for p in pivots)


def test_impulse_measurements_are_raw_ratios_and_hard_checks():
    prices = [1.1000, 1.1100, 1.1050, 1.1180, 1.1130, 1.1220]
    kinds = ["L", "H", "L", "H", "L", "H"]
    pivots = [Pivot(i * 10, str(i), p, k) for i, (p, k) in enumerate(zip(prices, kinds))]
    result = measure_wave_structure(pivots)
    assert result["pattern"] == "impulse_measurement"
    assert round(result["leg_pips"]["W1"]) == 100
    assert round(result["retracement_W2_vs_W1"], 2) == 0.50
    assert result["hard_valid"] is True


def test_abc_measurements_do_not_force_fibonacci_subtype():
    prices = [1.1200, 1.1100, 1.1150, 1.1030]
    kinds = ["H", "L", "H", "L"]
    pivots = [Pivot(i, str(i), p, k) for i, (p, k) in enumerate(zip(prices, kinds))]
    result = measure_wave_structure(pivots)
    assert result["pattern"] == "abc_measurement"
    assert round(result["retracement_B_vs_A"], 2) == 0.50
    assert round(result["extension_C_vs_A"], 2) == 1.20

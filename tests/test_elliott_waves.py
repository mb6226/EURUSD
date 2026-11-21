from eurusd_ai.market_data import Candle
from Modules.Elliott_Waves.Detection.detector import Pivot, find_five_wave_candidates, detect_pivots
from Modules.Elliott_Waves.Detection.features import candidate_features
from Modules.Elliott_Waves.Detection.engine import ElliottEngine


def test_five_wave_candidate_and_features():
    prices = [1.1000, 1.1100, 1.1050, 1.1180, 1.1130, 1.1220]
    kinds = ["L", "H", "L", "H", "L", "H"]
    pivots = tuple(Pivot(i * 10, str(i), p, k) for i, (p, k) in enumerate(zip(prices, kinds)))
    candidates = find_five_wave_candidates(pivots)
    assert len(candidates) == 1
    f = candidate_features(candidates[0])
    assert f["direction"] == 1
    assert round(f["wave1_pips"]) == 100
    assert round(f["wave2_retrace"], 2) == 0.50
    assert round(f["wave3_pips"]) == 130


def test_candle_validation():
    c = Candle("t", 1.1, 1.2, 1.0, 1.15, 100)
    assert c.high == 1.2


def test_dukascopy_timestamp_csv_loads_as_utc(tmp_path):
    from eurusd_ai.market_data import load_ohlcv_csv
    p = tmp_path / "dukascopy.csv"
    p.write_text("timestamp,open,high,low,close,volume\n1763596800000,1.1000,1.1010,1.0990,1.1005,12.5\n", encoding="utf-8")
    rows = load_ohlcv_csv(p)
    assert rows[0].time == "2025-11-20T00:00:00+00:00"
    assert rows[0].volume == 12.5


def test_engine_flags_invalid_wave_three_shortest():
    prices = [1.1000, 1.1100, 1.1060, 1.1110, 1.1080, 1.1150]
    kinds = ["L", "H", "L", "H", "L", "H"]
    pivots = [Pivot(i, str(i), p, k) for i, (p, k) in enumerate(zip(prices, kinds))]
    candidates = ElliottEngine(min_score=0).analyze_pivots(pivots)
    impulse = next(c for c in candidates if c.pattern == "impulse")
    assert not impulse.hard_valid
    assert any("shortest" in reason for reason in impulse.reasons)


def test_engine_finds_abc_zigzag_candidate():
    prices = [1.1200, 1.1100, 1.1150, 1.1030]
    kinds = ["H", "L", "H", "L"]
    pivots = [Pivot(i, str(i), p, k) for i, (p, k) in enumerate(zip(prices, kinds))]
    candidates = ElliottEngine().analyze_pivots(pivots)
    assert candidates
    assert candidates[0].pattern == "zigzag"
    assert candidates[0].direction == "up"


def test_pivot_detector_returns_alternating_confirmed_swings():
    candles = []
    prices = [1.1000, 1.1010, 1.1020, 1.1015, 1.1000, 1.0990, 1.1000, 1.1015]
    for i, price in enumerate(prices):
        candles.append(Candle(str(i), price, price + 0.0001, price - 0.0001, price, 1))
    pivots = detect_pivots(candles, min_leg_pips=10)
    assert len(pivots) >= 2
    assert all(pivots[i].kind != pivots[i + 1].kind for i in range(len(pivots) - 1))
    assert all(p.confirmed for p in pivots)

def test_elliott_engine_rejects_invalid_optimization_thresholds():
    import pytest
    with pytest.raises(ValueError):
        ElliottEngine(impulse_w2_soft_max=0)
    with pytest.raises(ValueError):
        ElliottEngine(abc_b_max_ratio=2.5)


def test_elliott_engine_accepts_optimized_morphology_thresholds():
    engine = ElliottEngine(min_score=15, impulse_w2_soft_max=0.8,
                           abc_b_max_ratio=1.15, abc_c_min_ratio=0.4)
    assert engine.min_score == 15
    assert engine.impulse_w2_soft_max == 0.8
    assert engine.abc_b_max_ratio == 1.15
    assert engine.abc_c_min_ratio == 0.4

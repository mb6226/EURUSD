import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from eurusd_ai_monitor.engines.market_regime_engine import MarketRegimeEngine, RegimeThresholds
from eurusd_ai_monitor.models.context_quality import ContextQuality
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.market_data_store import Candle

BASE = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def make_candles(timeframe, count, *, mode="trend", start=BASE - timedelta(hours=12),
                 volatile_from=None):
    step = 5 if timeframe == "M5" else 1
    values, previous = [], Decimal("1.10000")
    for i in range(count):
        if mode == "trend":
            close = previous + Decimal("0.00010")
        elif mode == "down":
            close = previous - Decimal("0.00010")
        elif mode == "range":
            close = previous + (Decimal("0.00010") if i % 2 == 0 else Decimal("-0.00010"))
        else:
            close = previous + (Decimal("0.00010") if i % 3 else Decimal("-0.00010"))
        width = Decimal("0.00005") if volatile_from is None or i < volatile_from else Decimal("0.00060")
        opened = start + timedelta(minutes=step * i)
        values.append(Candle("Broker", "EURUSD", timeframe, opened, previous,
            max(previous, close) + width, min(previous, close) - width, close, 10, 1, 0))
        previous = close
    return tuple(values)


def make_snapshot(*, m5=(), m1=(), valid=True, at=BASE):
    return MarketSnapshot("EURUSD", at, "Broker", tuple(m1), tuple(m5), None, None,
        ContextQuality(is_valid=valid, issues=() if valid else ("bad feed",)))


def make_structure(direction="UP", broken=False):
    return SimpleNamespace(
        trend=SimpleNamespace(direction=SimpleNamespace(value=direction)),
        protected_swing_break=object() if broken else None,
    )


class MarketRegimeEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = MarketRegimeEngine(pip_size=Decimal("0.0001"))

    def test_trend_requires_m5_structure_and_efficiency(self):
        m5 = make_candles("M5", 100, start=BASE - timedelta(minutes=500))
        m1 = make_candles("M1", 40, start=BASE - timedelta(minutes=40))
        report = self.engine.assess(make_snapshot(m5=m5, m1=m1), make_structure("UP"))
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(report["regime"], "TRENDING")
        self.assertEqual(report["trend_direction"], "UP")
        self.assertEqual(report["lower_timeframe_alignment"], "ALIGNED")
        self.assertEqual(report["trade_authority"], "NONE")

    def test_low_efficiency_classifies_range(self):
        m5 = make_candles("M5", 100, mode="range", start=BASE - timedelta(minutes=500))
        report = self.engine.assess(make_snapshot(m5=m5), make_structure("UNKNOWN"))
        self.assertEqual(report["regime"], "RANGING")

    def test_direction_is_unknown_without_m5_structure(self):
        m5 = make_candles("M5", 100, start=BASE - timedelta(minutes=500))
        report = self.engine.assess(make_snapshot(m5=m5))
        self.assertEqual(report["regime"], "TRANSITIONAL")
        self.assertEqual(report["trend_direction"], "UNKNOWN")

    def test_protected_structure_break_marks_transition(self):
        m5 = make_candles("M5", 100, start=BASE - timedelta(minutes=500))
        report = self.engine.assess(make_snapshot(m5=m5), make_structure("UP", broken=True))
        self.assertEqual(report["regime"], "TRANSITIONAL")
        self.assertIn("STRUCTURE_BREAK_CONFIRMED", report["transition_flags"])

    def test_recent_atr_expansion_is_separate_volatility_dimension(self):
        m5 = make_candles("M5", 100, start=BASE - timedelta(minutes=500), volatile_from=86)
        report = self.engine.assess(make_snapshot(m5=m5), make_structure("UP"))
        self.assertEqual(report["volatility_state"], "HIGH")
        self.assertIn("VOLATILITY_EXPANSION", report["transition_flags"])

    def test_invalid_quality_fails_closed(self):
        m5 = make_candles("M5", 100, start=BASE - timedelta(minutes=500))
        report = self.engine.assess(make_snapshot(m5=m5, valid=False), make_structure("UP"))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["regime"], "UNKNOWN")

    def test_short_history_is_insufficient(self):
        m5 = make_candles("M5", 30, start=BASE - timedelta(minutes=150))
        report = self.engine.assess(make_snapshot(m5=m5), make_structure("UP"))
        self.assertEqual(report["status"], "INSUFFICIENT_DATA")

    def test_forming_m5_candle_is_rejected(self):
        m5 = make_candles("M5", 100, start=BASE - timedelta(minutes=495))
        report = self.engine.assess(make_snapshot(m5=m5), make_structure("UP"))
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn("M5_CLOSED_CANDLE_SERIES_INVALID", report["reason_codes"])

    def test_opposed_m1_context_does_not_override_m5(self):
        m5 = make_candles("M5", 100, start=BASE - timedelta(minutes=500))
        m1 = make_candles("M1", 40, mode="down", start=BASE - timedelta(minutes=40))
        report = self.engine.assess(make_snapshot(m5=m5, m1=m1), make_structure("UP"))
        self.assertEqual(report["regime"], "TRENDING")
        self.assertEqual(report["trend_direction"], "UP")
        self.assertEqual(report["lower_timeframe_alignment"], "OPPOSED")

    def test_provenance_and_output_are_deterministic(self):
        m5 = make_candles("M5", 100, start=BASE - timedelta(minutes=500))
        snap = make_snapshot(m5=m5)
        one = self.engine.assess(snap, make_structure("UP"))
        two = self.engine.assess(snap, make_structure("UP"))
        self.assertEqual(one, two)
        self.assertEqual(len(one["provenance"]["m5_candle_ids"]), 20)
        self.assertTrue(one["provenance"]["m1_is_context_only"])

    def test_threshold_contract_rejects_overlapping_efficiency_bands(self):
        with self.assertRaises(ValueError):
            RegimeThresholds(trending_efficiency_min=0.2, ranging_efficiency_max=0.3)


if __name__ == "__main__":
    unittest.main()

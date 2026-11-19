import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.engines.setup_pattern_engine import SetupPatternEngine, SetupStage
from eurusd_ai_monitor.models.price_action import TrendDirection
from eurusd_ai_monitor.storage.market_data_store import Candle
from eurusd_ai_monitor.strategy_config import load_strategy_config

BASE = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)

def c(i, o, h, l, cl):
    return Candle("Mock", "EURUSD", "M1", BASE + timedelta(minutes=i),
                  Decimal(o), Decimal(h), Decimal(l), Decimal(cl), 10, 1, 0)

class SetupPatternEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = SetupPatternEngine(load_strategy_config())

    def test_bullish_rejection_requires_touch_close_location_and_wick_ratio(self):
        # Lower wick 0.00030 / body 0.00010 = 3; close location = 0.80.
        rejection = self.engine.find_rejection(
            (c(0, "1.10010", "1.10030", "1.09980", "1.10020"),),
            TrendDirection.UP, Decimal("1.10000"), "alg", "params",
        )
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection.level, Decimal("1.10000"))

    def test_bearish_rejection_is_mirror_image(self):
        rejection = self.engine.find_rejection(
            (c(0, "1.10020", "1.10050", "1.10000", "1.10010"),),
            TrendDirection.DOWN, Decimal("1.10030"), "alg", "params",
        )
        self.assertIsNotNone(rejection)

    def test_rejection_rejects_zero_body_and_weak_wick(self):
        self.assertIsNone(self.engine.find_rejection(
            (c(0, "1.10010", "1.10030", "1.09980", "1.10010"),),
            TrendDirection.UP, Decimal("1.10000"), "alg", "params",
        ))
        self.assertIsNone(self.engine.find_rejection(
            (c(0, "1.10000", "1.10020", "1.09990", "1.10010"),),
            TrendDirection.UP, Decimal("1.10000"), "alg", "params",
        ))

    def test_bullish_breakout_and_retest(self):
        rejection = self.engine.find_rejection(
            (c(0, "1.10010", "1.10030", "1.09980", "1.10020"),),
            TrendDirection.UP, Decimal("1.10000"), "alg", "params",
        )
        result = self.engine.find_pullback(
            (c(1, "1.10020", "1.10050", "1.10010", "1.10040"),
             c(2, "1.10040", "1.10045", "1.10025", "1.10035")),
            TrendDirection.UP, rejection, Decimal("0.00020"), "alg", "params",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.trigger_level, Decimal("1.10030"))
        self.assertEqual(result.confirmed_at_utc, BASE + timedelta(minutes=3))

    def test_no_retest_means_no_pullback(self):
        rejection = self.engine.find_rejection(
            (c(0, "1.10010", "1.10030", "1.09980", "1.10020"),),
            TrendDirection.UP, Decimal("1.10000"), "alg", "params",
        )
        self.assertIsNone(self.engine.find_pullback(
            (c(1, "1.10020", "1.10050", "1.10010", "1.10040"),
             c(2, "1.10050", "1.10070", "1.10045", "1.10060")),
            TrendDirection.UP, rejection, Decimal("0.00020"), "alg", "params",
        ))

    def test_retest_must_follow_breakout(self):
        rejection = self.engine.find_rejection(
            (c(0, "1.10010", "1.10030", "1.09980", "1.10020"),),
            TrendDirection.UP, Decimal("1.10000"), "alg", "params",
        )
        result = self.engine.find_pullback(
            (c(1, "1.10020", "1.10025", "1.10010", "1.10020"),
             c(2, "1.10020", "1.10050", "1.10010", "1.10040")),
            TrendDirection.UP, rejection, Decimal("0.00020"), "alg", "params",
        )
        self.assertIsNone(result)
 
    def test_bearish_breakout_and_retest(self):
        rejection = self.engine.find_rejection(
            (c(0, "1.10020", "1.10050", "1.10000", "1.10010"),),
            TrendDirection.DOWN, Decimal("1.10030"), "alg", "params",
        )
        result = self.engine.find_pullback(
            (c(1, "1.10010", "1.10020", "1.09990", "1.10000"),
             c(2, "1.10000", "1.10025", "1.09980", "1.09990")),
            TrendDirection.DOWN, rejection, Decimal("0.00020"), "alg", "params",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.trigger_level, Decimal("1.10000"))

    def test_retest_beyond_tolerance_is_rejected(self):
        rejection = self.engine.find_rejection(
            (c(0, "1.10010", "1.10030", "1.09980", "1.10020"),),
            TrendDirection.UP, Decimal("1.10000"), "alg", "params",
        )
        result = self.engine.find_pullback(
            (c(1, "1.10020", "1.10050", "1.10010", "1.10040"),
             c(2, "1.10040", "1.10045", "1.10000", "1.10035")),
            TrendDirection.UP, rejection, Decimal("0.00020"), "alg", "params",
        )
        self.assertIsNone(result)

    def test_assessment_is_never_trade_authority(self):
        from eurusd_ai_monitor.engines.setup_pattern_engine import SetupAssessment
        result = SetupAssessment(SetupStage.BLOCKED, None, None, None, None, BASE,
                                 ("NO_ACTIVE_CORRECTION_LIFECYCLE",))
        self.assertEqual(result.trade_authority, "NONE")
        self.assertEqual(result.entry_eligibility, "BLOCKED")
        with self.assertRaises(ValueError):
            SetupAssessment(SetupStage.BLOCKED, None, None, None, None, BASE,
                            ("blocked",), trade_authority="BUY")

    def test_open_m1_candle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "closed"):
            self.engine.assess(None, (c(0, "1.1", "1.2", "1.0", "1.1"),),
                               BASE + timedelta(seconds=30))


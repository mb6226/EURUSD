from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from eurusd_ai_monitor.engines.correction_detector import CorrectionDetector
from eurusd_ai_monitor.engines.impulse_detector import ImpulseDetector
from eurusd_ai_monitor.engines.technical_engine import TechnicalEngine
from eurusd_ai_monitor.models.correction_lifecycle import (
    LifecycleState,
    LifecycleWarning,
)
from eurusd_ai_monitor.models.price_action import MarketContext, TrendDirection
from eurusd_ai_monitor.storage.market_data_store import Candle
from eurusd_ai_monitor.strategy_config import load_strategy_config


BASE = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
BROKER = "Mock-Broker"
SYMBOL = "EURUSD"


def candle(index, high, low):
    high = Decimal(str(high))
    low = Decimal(str(low))
    close = (high + low) / Decimal(2)
    return Candle(
        broker_server=BROKER,
        symbol=SYMBOL,
        timeframe="M5",
        candle_open_time_utc=BASE + timedelta(minutes=5 * index),
        open=close,
        high=high,
        low=low,
        close=close,
        tick_volume=10,
        spread=2,
        real_volume=0,
    )


def uptrend_candles():
    centers = tuple(
        Decimal(value)
        for value in (
            "1.10000", "1.10100", "1.10500", "1.10300", "1.10200",
            "1.10300", "1.10800", "1.10500", "1.10400", "1.10500",
            "1.11100", "1.10800", "1.10700",
        )
    )
    return tuple(
        candle(i, center + Decimal("0.00050"), center - Decimal("0.00050"))
        for i, center in enumerate(centers)
    )


class CorrectionDetectorTests(unittest.TestCase):
    def setUp(self):
        self.config = load_strategy_config()
        self.technical = TechnicalEngine(self.config)
        self.impulse_detector = ImpulseDetector()
        self.detector = CorrectionDetector()
        self.candles = uptrend_candles()
        context = MarketContext(
            symbol=SYMBOL,
            source_id=BROKER,
            as_of_utc=self.candles[-1].candle_open_time_utc + timedelta(minutes=5),
            m1_candles=(),
            m5_candles=self.candles,
        )
        structure = self.technical.analyze_m5(context)
        self.impulse = self.impulse_detector.detect(structure, self.config.pip_size)

    def test_creates_candidate_on_first_closed_candle_reaching_threshold(self):
        first_correction = candle(13, "1.10800", "1.10650")
        candles = self.candles + (first_correction,)
        lifecycle = self.detector.detect_candidate(
            self.impulse,
            TrendDirection.UP,
            candles,
            candles[-1].candle_open_time_utc + timedelta(minutes=5),
            Decimal("5"),
            Decimal("0.80"),
        )

        self.assertIsNotNone(lifecycle)
        self.assertEqual(lifecycle.state, LifecycleState.CANDIDATE)
        self.assertEqual(lifecycle.age_bars, 1)
        self.assertEqual(lifecycle.candidate_start_evidence.candle, first_correction)
        self.assertEqual(lifecycle.last_processed_m5_utc, first_correction.candle_open_time_utc)
        self.assertEqual(lifecycle.depth_pips, Decimal("50"))
        self.assertEqual(lifecycle.retracement_ratio, Decimal("0.625"))
        self.assertEqual(lifecycle.warnings, ())

    def test_deep_correction_is_warning_not_rejection(self):
        deep = self.candles + (
            candle(13, "1.10900", "1.10650"),
            candle(14, "1.10800", "1.10000"),
        )
        lifecycle = self.detector.detect_candidate(
            self.impulse,
            TrendDirection.UP,
            deep,
            deep[-1].candle_open_time_utc + timedelta(minutes=5),
            Decimal("5"),
            Decimal("0.40"),
        )
        self.assertIsNotNone(lifecycle)
        self.assertEqual(lifecycle.state, LifecycleState.CANDIDATE)
        self.assertEqual(lifecycle.warnings, (LifecycleWarning.DEEP_CORRECTION,))
        self.assertEqual(lifecycle.age_bars, 2)

    def test_returns_none_when_threshold_is_not_reached(self):
        shallow = tuple(
            candle(i, "1.11200", "1.11120")
            for i in range(13, 16)
        )
        lifecycle = self.detector.detect_candidate(
            self.impulse,
            TrendDirection.UP,
            self.candles + shallow,
            shallow[-1].candle_open_time_utc + timedelta(minutes=5),
            Decimal("5"),
            Decimal("0.80"),
        )
        self.assertIsNone(lifecycle)

    def test_rejects_open_candle(self):
        open_candle = candle(13, "1.10800", "1.10000")
        with self.assertRaises(ValueError):
            self.detector.detect_candidate(
                self.impulse,
                TrendDirection.UP,
                self.candles + (open_candle,),
                open_candle.candle_open_time_utc + timedelta(minutes=1),
                Decimal("5"),
                Decimal("0.80"),
            )

    def test_rejects_unsorted_candles(self):
        with self.assertRaises(ValueError):
            self.detector.detect_candidate(
                self.impulse,
                TrendDirection.UP,
                tuple(reversed(self.candles)),
                self.candles[-1].candle_open_time_utc + timedelta(minutes=5),
                Decimal("5"),
                Decimal("0.80"),
            )


if __name__ == "__main__":
    unittest.main()

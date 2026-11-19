from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from eurusd_ai_monitor.engines.impulse_detector import ImpulseDetector
from eurusd_ai_monitor.engines.technical_engine import (
    Pivot,
    PivotKind,
    TechnicalEngine,
)
from eurusd_ai_monitor.models.price_action import TrendDirection
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


class ImpulseDetectorTests(unittest.TestCase):
    def setUp(self):
        self.config = load_strategy_config()
        self.engine = TechnicalEngine(self.config)
        self.detector = ImpulseDetector()

    def test_selects_latest_completed_up_impulse_from_confirmed_pivots(self):
        candles = uptrend_candles()
        context = self._context(candles)
        structure = self.engine.analyze_m5(context)

        impulse = self.detector.detect(structure, self.config.pip_size)

        self.assertIsNotNone(impulse)
        self.assertEqual(impulse.direction.value, "UP")
        self.assertEqual(impulse.start_pivot.candle.low, Decimal("1.10350"))
        self.assertEqual(impulse.end_pivot.candle.high, Decimal("1.11150"))
        self.assertEqual(impulse.size_pips, Decimal("80"))
        self.assertEqual(impulse.confirmed_at_utc, impulse.end_pivot.confirmed_at_utc)
        self.assertLessEqual(impulse.confirmed_at_utc, structure.evaluated_at_utc)

    def test_returns_none_for_non_directional_structure(self):
        candles = uptrend_candles()
        context = self._context(candles)
        structure = self.engine.analyze_m5(context)
        from dataclasses import replace
        from eurusd_ai_monitor.models.price_action import Trend, TrendDirection

        non_directional = replace(
            structure,
            trend=Trend(
                direction=TrendDirection.RANGE,
                confirmed_at_utc=structure.evaluated_at_utc,
                swing_highs=structure.trend.swing_highs,
                swing_lows=structure.trend.swing_lows,
            ),
            structure_time_utc=None,
        )
        self.assertIsNone(self.detector.detect(non_directional, self.config.pip_size))

    def test_rejects_invalid_pip_size(self):
        structure = self.engine.analyze_m5(self._context(uptrend_candles()))
        with self.assertRaises(ValueError):
            self.detector.detect(structure, Decimal("0"))

    @staticmethod
    def _context(candles):
        from eurusd_ai_monitor.models.price_action import MarketContext

        return MarketContext(
            symbol=SYMBOL,
            source_id=BROKER,
            as_of_utc=candles[-1].candle_open_time_utc + timedelta(minutes=5),
            m1_candles=(),
            m5_candles=candles,
        )


if __name__ == "__main__":
    unittest.main()

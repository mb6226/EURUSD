from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from eurusd_ai_monitor.engines.price_action_coordinator import PriceActionCoordinator
from eurusd_ai_monitor.engines.technical_engine import TechnicalEngine
from eurusd_ai_monitor.models.correction_lifecycle import TransitionType
from eurusd_ai_monitor.models.price_action import MarketContext
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


class PriceActionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.config = load_strategy_config()
        self.engine = TechnicalEngine(self.config)
        self.coordinator = PriceActionCoordinator()

    def structure(self, candles):
        context = MarketContext(
            symbol=SYMBOL,
            source_id=BROKER,
            as_of_utc=candles[-1].candle_open_time_utc + timedelta(minutes=5),
            m1_candles=(),
            m5_candles=candles,
        )
        return self.engine.analyze_m5(context)

    def test_output_never_grants_trade_authority(self):
        centers = tuple(
            Decimal(value)
            for value in (
                "1.10000", "1.10100", "1.10500", "1.10300", "1.10200",
                "1.10300", "1.10800", "1.10500", "1.10400", "1.10500",
                "1.11100", "1.10800", "1.10700",
            )
        )
        candles = tuple(
            candle(i, center + Decimal("0.00050"), center - Decimal("0.00050"))
            for i, center in enumerate(centers)
        )
        result = self.coordinator.process(
            structure=self.structure(candles),
            m5_candles=candles,
            active_lifecycle=None,
            pip_size=self.config.pip_size,
            min_correction_pips=Decimal("5"),
            max_correction_ratio=Decimal("0.80"),
        )

        self.assertEqual(result.trade_authority, "NONE")
        self.assertEqual(result.transition.transition_type, TransitionType.NO_TRANSITION)
        self.assertIsNone(result.transition.lifecycle)

    def test_creates_candidate_without_creating_a_trade_signal(self):
        centers = tuple(
            Decimal(value)
            for value in (
                "1.10000", "1.10100", "1.10500", "1.10300", "1.10200",
                "1.10300", "1.10800", "1.10500", "1.10400", "1.10500",
                "1.11100", "1.10800", "1.10700",
            )
        )
        history = tuple(
            candle(i, center + Decimal("0.00050"), center - Decimal("0.00050"))
            for i, center in enumerate(centers)
        )
        correction = candle(13, "1.10800", "1.10650")
        candles = history + (correction,)
        result = self.coordinator.process(
            structure=self.structure(candles),
            m5_candles=candles,
            active_lifecycle=None,
            pip_size=self.config.pip_size,
            min_correction_pips=Decimal("5"),
            max_correction_ratio=Decimal("0.80"),
        )

        self.assertEqual(result.trade_authority, "NONE")
        self.assertEqual(result.transition.transition_type, TransitionType.CREATED)
        self.assertEqual(result.transition.current_state.value, "CANDIDATE")


if __name__ == "__main__":
    unittest.main()

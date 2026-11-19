from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from eurusd_ai_monitor.engines.correction_detector import CorrectionDetector
from eurusd_ai_monitor.engines.impulse_detector import ImpulseDetector
from eurusd_ai_monitor.engines.lifecycle_state_machine import LifecycleStateMachine
from eurusd_ai_monitor.engines.technical_engine import TechnicalEngine
from eurusd_ai_monitor.models.correction_lifecycle import (
    LifecycleState,
    TransitionType,
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


class LifecycleStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.config = load_strategy_config()
        self.technical = TechnicalEngine(self.config)
        self.machine = LifecycleStateMachine()
        self.candles = uptrend_candles()
        base_context = self.context(self.candles)
        structure = self.technical.analyze_m5(base_context)
        impulse = ImpulseDetector().detect(structure, self.config.pip_size)
        first_correction = candle(13, "1.10800", "1.10650")
        self.history = self.candles + (first_correction,)
        self.lifecycle = CorrectionDetector().detect_candidate(
            impulse,
            TrendDirection.UP,
            self.history,
            self.history[-1].candle_open_time_utc + timedelta(minutes=5),
            Decimal("5"),
            Decimal("0.80"),
        )
        self.assertIsNotNone(self.lifecycle)

    @staticmethod
    def context(candles):
        return MarketContext(
            symbol=SYMBOL,
            source_id=BROKER,
            as_of_utc=candles[-1].candle_open_time_utc + timedelta(minutes=5),
            m1_candles=(),
            m5_candles=candles,
        )

    def test_no_new_closed_candle_is_idempotent(self):
        structure = self.technical.analyze_m5(self.context(self.history))
        result = self.machine.advance(self.lifecycle, structure, self.history)

        self.assertEqual(result.transition_type, TransitionType.NO_TRANSITION)
        self.assertEqual(result.lifecycle, self.lifecycle)
        self.assertEqual(result.current_state, LifecycleState.CANDIDATE)

    def test_candidate_advances_using_actual_new_closed_bar(self):
        next_bar = candle(14, "1.10750", "1.10500")
        candles = self.history + (next_bar,)
        structure = self.technical.analyze_m5(self.context(candles))
        result = self.machine.advance(self.lifecycle, structure, candles)

        self.assertEqual(result.transition_type, TransitionType.NO_TRANSITION)
        self.assertEqual(result.lifecycle.age_bars, 2)
        self.assertEqual(result.lifecycle.last_processed_m5_utc, next_bar.candle_open_time_utc)
        self.assertEqual(result.lifecycle.extreme_evidence.candle, next_bar)

    def test_expiry_is_checked_after_candidate_extreme_update(self):
        next_bar = candle(14, "1.10750", "1.10500")
        candles = self.history + (next_bar,)
        structure = self.technical.analyze_m5(self.context(candles))
        result = self.machine.advance(
            self.lifecycle, structure, candles, expiry_bars=2
        )

        self.assertEqual(result.transition_type, TransitionType.EXPIRED)
        self.assertEqual(result.current_state, LifecycleState.EXPIRED)
        self.assertEqual(result.lifecycle.age_bars, 2)

    def test_terminal_states_are_irreversible(self):
        terminal = replace(
            self.lifecycle,
            state=LifecycleState.INVALIDATED,
            state_version=1,
        )
        next_bar = candle(14, "1.10750", "1.10500")
        candles = self.history + (next_bar,)
        structure = self.technical.analyze_m5(self.context(candles))
        result = self.machine.advance(terminal, structure, candles)

        self.assertEqual(result.transition_type, TransitionType.NO_TRANSITION)
        self.assertIs(result.lifecycle, terminal)
        self.assertEqual(result.current_state, LifecycleState.INVALIDATED)


if __name__ == "__main__":
    unittest.main()

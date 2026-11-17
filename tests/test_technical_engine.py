from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from eurusd_ai_monitor.engines.technical_engine import (
    MARKET_STRUCTURE_ALGORITHM_VERSION,
    PivotKind,
    TechnicalEngine,
)
from eurusd_ai_monitor.models.price_action import (
    MarketContext,
    TrendDirection,
)
from eurusd_ai_monitor.storage.market_data_store import Candle
from eurusd_ai_monitor.strategy_config import load_strategy_config


BASE = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
BROKER = "Mock-Broker"
SYMBOL = "EURUSD"


def candle(index, high, low, close=None):
    high = Decimal(str(high))
    low = Decimal(str(low))
    if close is None:
        close = (high + low) / Decimal(2)
    else:
        close = Decimal(str(close))
    return Candle(
        broker_server=BROKER,
        symbol=SYMBOL,
        timeframe="M5",
        candle_open_time_utc=BASE + timedelta(minutes=5 * index),
        open=close,
        high=high,
        close=close,
        low=low,
        tick_volume=10,
        spread=2,
        real_volume=0,
    )


def context(candles, as_of=None):
    candles = tuple(candles)
    if as_of is None:
        as_of = candles[-1].candle_open_time_utc + timedelta(minutes=5)
    return MarketContext(
        symbol=SYMBOL,
        source_id=BROKER,
        as_of_utc=as_of,
        m1_candles=(),
        m5_candles=candles,
    )


def uptrend_candles():
    centers = [
        Decimal(value)
        for value in (
            "1.10000", "1.10100", "1.10500", "1.10300", "1.10200",
            "1.10300", "1.10800", "1.10500", "1.10400", "1.10500",
            "1.11100", "1.10800", "1.10700",
        )
    ]
    return tuple(
        candle(i, center + Decimal("0.00050"), center - Decimal("0.00050"))
        for i, center in enumerate(centers)
    )


def downtrend_candles():
    centers = [
        Decimal("2.20000") - (value - Decimal("1.10000"))
        for value in (
            Decimal("1.10000"), Decimal("1.10100"), Decimal("1.10500"),
            Decimal("1.10300"), Decimal("1.10200"), Decimal("1.10300"),
            Decimal("1.10800"), Decimal("1.10500"), Decimal("1.10400"),
            Decimal("1.10500"), Decimal("1.11100"), Decimal("1.10800"),
            Decimal("1.10700"),
        )
    ]
    return tuple(
        candle(i, center + Decimal("0.00050"), center - Decimal("0.00050"))
        for i, center in enumerate(centers)
    )


class TechnicalEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_strategy_config()
        cls.engine = TechnicalEngine(cls.config)

    def test_detects_simple_pivot_high(self):
        highs = ["1.101", "1.102", "1.105", "1.103", "1.102"]
        lows = ["1.0990", "1.0995", "1.0992", "1.0996", "1.0994"]
        result = self.engine.analyze_m5(
            context(
                candle(i, high, low)
                for i, (high, low) in enumerate(zip(highs, lows))
            )
        )
        pivots = [p for p in result.pivots if p.kind is PivotKind.HIGH]
        self.assertEqual(len(pivots), 1)
        self.assertEqual(pivots[0].evidence.candle.candle_open_time_utc, BASE + timedelta(minutes=10))

    def test_detects_simple_pivot_low(self):
        highs = ["1.102", "1.103", "1.104", "1.105", "1.106"]
        lows = ["1.099", "1.0985", "1.097", "1.098", "1.099"]
        result = self.engine.analyze_m5(
            context(
                candle(i, high, low)
                for i, (high, low) in enumerate(zip(highs, lows))
            )
        )
        pivots = [p for p in result.pivots if p.kind is PivotKind.LOW]
        self.assertEqual(len(pivots), 1)
        self.assertEqual(pivots[0].evidence.candle.low, Decimal("1.097"))

    def test_pivot_waits_for_two_closed_right_bars(self):
        candles = [
            candle(i, high, low)
            for i, (high, low) in enumerate(
                zip(
                    ["1.101", "1.102", "1.105", "1.103", "1.102"],
                    ["1.0990", "1.0995", "1.0992", "1.0996", "1.0994"],
                )
            )
        ]
        before_confirmation = self.engine.analyze_m5(
            context(candles[:4], BASE + timedelta(minutes=20))
        )
        after_confirmation = self.engine.analyze_m5(context(candles))
        self.assertFalse(before_confirmation.pivots)
        high_pivot = next(p for p in after_confirmation.pivots if p.kind is PivotKind.HIGH)
        self.assertEqual(
            high_pivot.evidence.confirmed_at_utc,
            BASE + timedelta(minutes=25),
        )
        self.assertEqual(
            high_pivot.evidence.supporting_candle_ids,
            tuple(
                f"{BROKER}|{SYMBOL}|M5|{(BASE + timedelta(minutes=5 * i)).isoformat().replace('+00:00', 'Z')}"
                for i in (3, 4)
            ),
        )

    def test_analysis_prefix_does_not_use_future_pivot_data(self):
        candles = uptrend_candles()
        prefix = self.engine.analyze_m5(
            context(candles[:4], BASE + timedelta(minutes=20))
        )
        full = self.engine.analyze_m5(context(candles))
        self.assertFalse(prefix.pivots)
        self.assertTrue(full.pivots)
        self.assertTrue(
            all(p.evidence.confirmed_at_utc <= full.evaluated_at_utc for p in full.pivots)
        )

    def test_historical_snapshot_is_stable_when_future_candles_are_added(self):
        base = list(uptrend_candles())
        target = base[12].candle_open_time_utc + timedelta(minutes=10)
        historical = base + [candle(13, "1.102", "1.100", "1.101")]
        extended = historical + [
            candle(14, "1.105", "1.101", "1.103"),
            candle(15, "1.106", "1.102", "1.104"),
            candle(16, "1.107", "1.103", "1.105"),
        ]
        past_result = self.engine.analyze_m5_at(context(historical), target)
        extended_result = self.engine.analyze_m5_at(context(extended), target)

        self.assertEqual(past_result.pivots, extended_result.pivots)
        self.assertEqual(past_result.trend, extended_result.trend)
        self.assertEqual(past_result.structure_time_utc, extended_result.structure_time_utc)
        self.assertEqual(
            past_result.protected_swing_break,
            extended_result.protected_swing_break,
        )
        self.assertEqual(past_result.trend.direction, TrendDirection.RANGE)

    def test_classifies_higher_highs_and_higher_lows_as_up(self):
        result = self.engine.analyze_m5(context(uptrend_candles()))
        self.assertEqual(result.trend.direction, TrendDirection.UP)
        self.assertEqual(len(result.trend.swing_highs), 2)
        self.assertEqual(len(result.trend.swing_lows), 2)
        self.assertEqual(result.trend.protected_swing, result.trend.swing_lows[-1])

    def test_classifies_lower_highs_and_lower_lows_as_down(self):
        result = self.engine.analyze_m5(context(downtrend_candles()))
        self.assertEqual(result.trend.direction, TrendDirection.DOWN)
        self.assertEqual(len(result.trend.swing_highs), 2)
        self.assertEqual(len(result.trend.swing_lows), 2)
        self.assertEqual(result.trend.protected_swing, result.trend.swing_highs[-1])

    def test_contradictory_swing_structure_is_range(self):
        highs = [
            "1.101", "1.102", "1.105", "1.103", "1.102", "1.103",
            "1.108", "1.105", "1.104", "1.105", "1.110", "1.108", "1.107",
        ]
        lows = [
            "1.099", "1.0985", "1.098", "1.097", "1.095", "1.096",
            "1.097", "1.094", "1.092", "1.093", "1.094", "1.0935", "1.093",
        ]
        result = self.engine.analyze_m5(
            context(candle(i, high, low) for i, (high, low) in enumerate(zip(highs, lows)))
        )
        self.assertEqual(result.trend.direction, TrendDirection.RANGE)

    def test_non_alternating_last_four_swings_do_not_form_a_trend(self):
        highs = [
            "1.101", "1.102", "1.110", "1.105", "1.103", "1.104",
            "1.112", "1.106", "1.105", "1.106", "1.114", "1.108",
            "1.107", "1.106", "1.105", "1.104", "1.103", "1.102",
            "1.101", "1.100",
        ]
        lows = [
            "1.099", "1.098", "1.097", "1.096", "1.095", "1.096",
            "1.097", "1.098", "1.099", "1.098", "1.097", "1.096",
            "1.090", "1.095", "1.094", "1.093", "1.092", "1.094",
            "1.095", "1.096",
        ]
        result = self.engine.analyze_m5(
            context(candle(i, high, low) for i, (high, low) in enumerate(zip(highs, lows)))
        )
        self.assertEqual(result.trend.direction, TrendDirection.RANGE)
        self.assertEqual(
            [ref.candle.candle_open_time_utc for ref in result.trend.swing_highs],
            [BASE + timedelta(minutes=30), BASE + timedelta(minutes=50)],
        )
        self.assertEqual(
            [ref.candle.candle_open_time_utc for ref in result.trend.swing_lows],
            [BASE + timedelta(minutes=60), BASE + timedelta(minutes=80)],
        )

    def test_insufficient_data_is_unknown(self):
        result = self.engine.analyze_m5(
            context(
                (
                    candle(0, "1.101", "1.099"),
                    candle(1, "1.102", "1.098"),
                    candle(2, "1.103", "1.097"),
                )
            )
        )
        self.assertEqual(result.trend.direction, TrendDirection.UNKNOWN)

    def test_protected_swing_break_starts_after_structure_confirmation(self):
        base = list(uptrend_candles())
        structure_time = base[12].candle_open_time_utc + timedelta(minutes=5)

        before_confirmation = list(base)
        before_confirmation[11] = candle(
            11,
            base[11].high,
            "1.100",
            "1.101",
        )
        before = self.engine.analyze_m5(context(before_confirmation))
        self.assertEqual(before.structure_time_utc, structure_time)
        self.assertIsNone(before.protected_swing_break)
        self.assertEqual(before.trend.direction, TrendDirection.UP)

        exactly_at_confirmation = list(base)
        exactly_at_confirmation[12] = candle(
            12,
            base[12].high,
            "1.100",
            "1.101",
        )
        at_time = self.engine.analyze_m5(context(exactly_at_confirmation))
        self.assertEqual(at_time.structure_time_utc, structure_time)
        self.assertIsNone(at_time.protected_swing_break)
        self.assertEqual(at_time.trend.direction, TrendDirection.UP)

        after_confirmation = list(base)
        after_confirmation.append(candle(13, "1.102", "1.100", "1.101"))
        after = self.engine.analyze_m5(context(after_confirmation))
        self.assertEqual(after.structure_time_utc, structure_time)
        self.assertIsNotNone(after.protected_swing_break)
        self.assertEqual(after.protected_swing_break.break_candle, after_confirmation[13])
        self.assertEqual(
            after.protected_swing_break.confirmed_at_utc,
            structure_time + timedelta(minutes=5),
        )
        self.assertEqual(after.protected_swing_break.structure_time_utc, structure_time)
        self.assertEqual(after.trend.direction, TrendDirection.RANGE)

    def test_equal_high_low_and_plateau_are_not_pivots(self):
        equal_highs = self.engine.analyze_m5(
            context(
                candle(i, high, low)
                for i, (high, low) in enumerate(
                    zip(
                        ["1.101", "1.105", "1.105", "1.103", "1.102"],
                        ["1.099", "1.0995", "1.0992", "1.0996", "1.0994"],
                    )
                )
            )
        )
        self.assertFalse(any(p.kind is PivotKind.HIGH for p in equal_highs.pivots))

        equal_lows = self.engine.analyze_m5(
            context(
                candle(i, high, low)
                for i, (high, low) in enumerate(
                    zip(
                        ["1.101", "1.102", "1.103", "1.104", "1.105"],
                        ["1.099", "1.097", "1.095", "1.095", "1.096"],
                    )
                )
            )
        )
        self.assertFalse(any(p.kind is PivotKind.LOW for p in equal_lows.pivots))

        high_plateau = self.engine.analyze_m5(
            context(
                candle(i, high, low)
                for i, (high, low) in enumerate(
                    zip(
                        ["1.101", "1.105", "1.105", "1.105", "1.102", "1.101", "1.100"],
                        ["1.099", "1.098", "1.097", "1.096", "1.095", "1.094", "1.093"],
                    )
                )
            )
        )
        self.assertFalse(any(p.kind is PivotKind.HIGH for p in high_plateau.pivots))

        low_plateau = self.engine.analyze_m5(
            context(
                candle(i, high, low)
                for i, (high, low) in enumerate(
                    zip(
                        ["1.101", "1.102", "1.103", "1.104", "1.105", "1.106", "1.107"],
                        ["1.100", "1.095", "1.095", "1.095", "1.099", "1.100", "1.101"],
                    )
                )
            )
        )
        self.assertFalse(any(p.kind is PivotKind.LOW for p in low_plateau.pivots))

    def test_algorithm_and_parameter_versions_are_separate_and_consistent(self):
        result = self.engine.analyze_m5(context(uptrend_candles()))
        self.assertEqual(result.algorithm_version, MARKET_STRUCTURE_ALGORITHM_VERSION)
        self.assertTrue(result.parameter_version.startswith(self.config.strategy_version + ":"))
        self.assertTrue(
            all(
                pivot.evidence.algorithm_version == result.algorithm_version
                and pivot.evidence.parameter_version == result.parameter_version
                for pivot in result.pivots
            )
        )
        different_algorithm_label = TechnicalEngine(
            replace(self.config, algorithm_version="unrelated-config-label")
        ).analyze_m5(context(uptrend_candles()))
        changed_parameters = TechnicalEngine(
            replace(self.config, pivot_left_bars=self.config.pivot_left_bars + 1)
        ).analyze_m5(context(uptrend_candles()))
        self.assertEqual(
            result.parameter_version,
            different_algorithm_label.parameter_version,
        )
        self.assertNotEqual(result.parameter_version, changed_parameters.parameter_version)

    def test_open_candle_is_rejected_by_market_context(self):
        candle_open = candle(0, "1.101", "1.099")
        with self.assertRaisesRegex(ValueError, "not closed"):
            context((candle_open,), candle_open.candle_open_time_utc + timedelta(minutes=4))

    def test_unsorted_or_duplicate_timestamps_are_rejected(self):
        candles = uptrend_candles()
        with self.assertRaisesRegex(ValueError, "sorted"):
            context(
                (candles[1], candles[0]),
                candles[1].candle_open_time_utc + timedelta(minutes=5),
            )
        with self.assertRaisesRegex(ValueError, "sorted"):
            context((candles[0], candles[0]))


if __name__ == "__main__":
    unittest.main()

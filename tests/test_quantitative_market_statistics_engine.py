import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.engines.quantitative_market_statistics_engine import (
    QuantitativeMarketStatisticsEngine,
    QuantitativeThresholds,
)
from eurusd_ai_monitor.models.context_quality import ContextQuality
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.market_data_store import Candle


NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def make_candles(timeframe, count, *, start=None, step_pips="1", broker="Broker"):
    minutes = 1 if timeframe == "M1" else 5
    start = start or NOW - timedelta(minutes=minutes * count)
    values = []
    previous = Decimal("1.10000")
    step = Decimal(step_pips) * Decimal("0.0001")
    half = Decimal("0.00005")
    for index in range(count):
        close = previous + step
        values.append(Candle(
            broker, "EURUSD", timeframe,
            start + timedelta(minutes=minutes * index),
            previous, max(previous, close) + half,
            min(previous, close) - half, close, 10, 1, 0,
        ))
        previous = close
    return tuple(values)


def snapshot(m1=None, m5=None, *, valid=True, at=NOW):
    return MarketSnapshot(
        "EURUSD", at, "Broker", tuple(m1 or ()), tuple(m5 or ()),
        None, None,
        ContextQuality(is_valid=valid, issues=() if valid else ("feed invalid",)),
    )


class QuantitativeMarketStatisticsEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = QuantitativeMarketStatisticsEngine(
            QuantitativeThresholds(lookback_bars=40, minimum_bars=30)
        )

    def test_reports_closed_m1_and_m5_descriptive_statistics(self):
        report = self.engine.assess(snapshot(
            make_candles("M1", 40), make_candles("M5", 40)
        ))
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(report["report_type"], "QUANTITATIVE_MARKET_STATISTICS")
        self.assertEqual(report["timeframes"]["M1"]["candle_count"], 40)
        self.assertEqual(report["timeframes"]["M1"]["return_count"], 39)
        self.assertEqual(report["timeframes"]["M1"]["return_distribution_pips"]["mean"], "1")
        self.assertEqual(report["timeframes"]["M1"]["return_distribution_pips"]["sample_stddev"], "0")
        self.assertEqual(report["timeframes"]["M1"]["positive_return_pct"], "100")
        self.assertEqual(report["timeframes"]["M1"]["directional_efficiency_ratio"], "1")
        self.assertEqual(report["timeframes"]["M5"]["return_count"], 39)
        self.assertEqual(report["decision_authority"], "ASSESSMENT_ONLY")
        self.assertEqual(report["trade_authority"], "NONE")
        self.assertEqual(report["order_execution"], "DISABLED")

    def test_negative_and_zero_return_frequencies_are_descriptive(self):
        candles = list(make_candles("M1", 40))
        # Rebuild a deterministic sequence with alternating close changes.
        rebuilt = []
        previous = Decimal("1.10000")
        changes = [Decimal("0.0001"), Decimal("-0.0001"), Decimal("0")] * 13
        for index, change in enumerate(changes[:40]):
            close = previous + change
            rebuilt.append(Candle(
                "Broker", "EURUSD", "M1", NOW - timedelta(minutes=40-index),
                previous, max(previous, close) + Decimal("0.00005"),
                min(previous, close) - Decimal("0.00005"), close, 10, 1, 0,
            ))
            previous = close
        # The M1 series ends before NOW; the M5 window is independently aligned.
        report = self.engine.assess(snapshot(
            rebuilt, make_candles("M5", 40),
        ))
        stats = report["timeframes"]["M1"]
        self.assertGreater(Decimal(stats["positive_return_pct"]), 0)
        self.assertGreater(Decimal(stats["negative_return_pct"]), 0)
        self.assertGreater(Decimal(stats["zero_return_pct"]), 0)

    def test_invalid_market_quality_blocks_statistics(self):
        report = self.engine.assess(snapshot(
            make_candles("M1", 40), make_candles("M5", 40), valid=False
        ))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("MARKET_CONTEXT_QUALITY_FAILED", report["reason_codes"])

    def test_short_history_is_insufficient_not_zero_filled(self):
        report = self.engine.assess(snapshot(
            make_candles("M1", 20), make_candles("M5", 40)
        ))
        self.assertEqual(report["status"], "INSUFFICIENT_DATA")
        self.assertEqual(report["reason_codes"], ["M1_HISTORY_TOO_SHORT"])
        self.assertEqual(report["available_bars"], 20)

    def test_forming_candle_is_rejected(self):
        m1 = list(make_candles("M1", 40))
        last = m1[-1]
        m1[-1] = Candle(
            "Broker", "EURUSD", "M1", NOW,
            last.open, last.high, last.low, last.close, 10, 1, 0,
        )
        report = self.engine.assess(snapshot(m1, make_candles("M5", 40)))
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn("M1_FORMING_OR_FUTURE_CANDLE", report["reason_codes"])

    def test_non_chronological_series_is_rejected(self):
        m1 = list(make_candles("M1", 40))
        m1[-1], m1[-2] = m1[-2], m1[-1]
        report = self.engine.assess(snapshot(m1, make_candles("M5", 40)))
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn("M1_CANDLE_ORDER_INVALID", report["reason_codes"])

    def test_duplicate_candle_time_is_rejected(self):
        m1 = list(make_candles("M1", 40))
        m1[-1] = m1[-2]
        report = self.engine.assess(snapshot(m1, make_candles("M5", 40)))
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn("M1_CANDLE_ORDER_INVALID", report["reason_codes"])

    def test_output_is_deterministic_and_has_complete_provenance(self):
        snap = snapshot(make_candles("M1", 40), make_candles("M5", 40))
        one = self.engine.assess(snap)
        two = self.engine.assess(snap)
        self.assertEqual(one, two)
        self.assertEqual(len(one["provenance"]["m1_candle_ids"]), 40)
        self.assertEqual(len(one["provenance"]["m5_candle_ids"]), 40)
        self.assertTrue(one["provenance"]["closed_bars_only"])

    def test_lookback_is_capped_to_latest_configured_bars(self):
        report = self.engine.assess(snapshot(
            make_candles("M1", 60), make_candles("M5", 60)
        ))
        self.assertEqual(report["timeframes"]["M1"]["candle_count"], 40)
        self.assertEqual(report["timeframes"]["M5"]["candle_count"], 40)

    def test_invalid_thresholds_are_rejected(self):
        with self.assertRaises(ValueError):
            QuantitativeThresholds(lookback_bars=10, minimum_bars=11)
        with self.assertRaises(ValueError):
            QuantitativeThresholds(pip_size=Decimal("0"))

    def test_non_snapshot_input_is_rejected(self):
        with self.assertRaises(TypeError):
            self.engine.assess({})


if __name__ == "__main__":
    unittest.main()

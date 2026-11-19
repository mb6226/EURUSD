import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.engines.liquidity_microstructure_engine import LiquidityMicrostructureEngine
from eurusd_ai_monitor.storage.market_data_store import Candle

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
BROKER = "Broker-Demo"


def sample(index, timeframe="M1", *, spread=Decimal("0.8"), volume=100):
    minutes = 1 if timeframe == "M1" else 5
    opened = NOW - timedelta(minutes=minutes * (index + 1))
    candle = Candle(
        broker_server=BROKER, symbol="EURUSD", timeframe=timeframe,
        candle_open_time_utc=opened, open=Decimal("1.08000"),
        high=Decimal("1.08020"), low=Decimal("1.07990"),
        close=Decimal("1.08010"), tick_volume=volume + index,
        spread=8, real_volume=0,
    )
    return {"candle": candle, "pip_size": Decimal("0.0001"),
            "spread_pips": spread,
            "retrieved_at_utc": NOW - timedelta(seconds=1)}


class LiquidityMicrostructureEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = LiquidityMicrostructureEngine(minimum_samples=10,
                                                    comparison_window=3)

    def test_both_timeframes_available_with_provenance_and_no_trade_authority(self):
        rows = [sample(i, tf) for tf in ("M1", "M5") for i in range(10)]
        result = self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                     symbol="EURUSD", samples=rows)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["timeframes"]["M1"]["status"], "AVAILABLE")
        self.assertEqual(result["timeframes"]["M5"]["status"], "AVAILABLE")
        self.assertEqual(result["timeframes"]["M1"]["spread"]["unit"], "pips")
        self.assertEqual(result["decision_authority"], "CONTEXT_ONLY")
        self.assertEqual(result["trade_authority"], "NONE")
        self.assertEqual(result["order_execution"], "DISABLED")
        self.assertIn("provenance", result["timeframes"]["M1"])

    def test_missing_spread_is_partial_not_fabricated(self):
        rows = [sample(i, tf, spread=None) for tf in ("M1", "M5") for i in range(10)]
        result = self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                     symbol="EURUSD", samples=rows)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIsNone(result["timeframes"]["M1"]["spread"]["median"])
        self.assertIn("SPREAD_OBSERVATIONS_MISSING",
                      result["timeframes"]["M1"]["reason_codes"])

    def test_stale_timeframe_is_not_used_as_available(self):
        rows = [sample(i, "M1") for i in range(10)]
        result = self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                     symbol="EURUSD", samples=rows)
        self.assertEqual(result["timeframes"]["M1"]["status"], "STALE")
        self.assertEqual(result["status"], "UNAVAILABLE")

    def test_unclosed_future_candle_is_excluded(self):
        rows = [sample(i, "M1") for i in range(10)]
        future = sample(0, "M1")
        future["candle"] = Candle(
            broker_server=BROKER, symbol="EURUSD", timeframe="M1",
            candle_open_time_utc=NOW, open=Decimal("1.08"),
            high=Decimal("1.081"), low=Decimal("1.079"),
            close=Decimal("1.08"), tick_volume=1, spread=8, real_volume=0)
        rows.append(future)
        result = self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                     symbol="EURUSD", samples=rows)
        self.assertEqual(result["excluded_unclosed_candle_count"], 1)

    def test_future_retrieval_time_rejected(self):
        rows = [sample(i) for i in range(10)]
        rows[0]["retrieved_at_utc"] = NOW + timedelta(seconds=1)
        with self.assertRaises(ValueError):
            self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                symbol="EURUSD", samples=rows)

    def test_identity_mismatch_rejected(self):
        rows = [sample(i) for i in range(10)]
        rows[0]["candle"] = Candle(
            broker_server=BROKER, symbol="GBPUSD", timeframe="M1",
            candle_open_time_utc=rows[0]["candle"].candle_open_time_utc,
            open=Decimal("1.08"), high=Decimal("1.081"),
            low=Decimal("1.079"), close=Decimal("1.08"),
            tick_volume=1, spread=8, real_volume=0)
        with self.assertRaises(ValueError):
            self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                symbol="EURUSD", samples=rows)

    def test_duplicate_timestamp_rejected(self):
        rows = [sample(i) for i in range(10)]
        rows.append(rows[0])
        with self.assertRaises(ValueError):
            self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                symbol="EURUSD", samples=rows)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.analyze(evaluated_at_utc=datetime(2026, 11, 19, 12),
                                broker_server=BROKER, symbol="EURUSD",
                                samples=[sample(i) for i in range(10)])

    def test_invalid_pip_size_rejected(self):
        rows = [sample(i) for i in range(10)]
        rows[0]["pip_size"] = Decimal("0")
        with self.assertRaises(ValueError):
            self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                symbol="EURUSD", samples=rows)

    def test_deterministic_output(self):
        rows = [sample(i, tf) for tf in ("M1", "M5") for i in range(10)]
        first = self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                    symbol="EURUSD", samples=rows)
        second = self.engine.analyze(evaluated_at_utc=NOW, broker_server=BROKER,
                                     symbol="EURUSD", samples=rows)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from eurusd_ai_monitor.engines.historical_dataset_validation_engine import (
    HistoricalDatasetValidationEngine,
)
from eurusd_ai_monitor.storage.market_data_store import Candle, MarketDataStore


UTC = timezone.utc
BASE = datetime(2026, 11, 1, tzinfo=UTC)


def make_candle(minute, close="1.1000"):
    price = Decimal(close)
    return Candle(
        broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
        candle_open_time_utc=BASE + timedelta(minutes=minute),
        open=price, high=price + Decimal("0.0001"),
        low=price - Decimal("0.0001"), close=price,
        tick_volume=10, spread=2, real_volume=0,
    )


def report(minute):
    return {
        "evaluated_at_utc": (BASE + timedelta(minutes=minute)).isoformat(),
        "directional_assessment": {"state": "UP"},
    }


class HistoricalDatasetValidationEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketDataStore(Path(self.temp.name) / "market.sqlite")
        self.engine = HistoricalDatasetValidationEngine(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def audit(self, start=0, end=5, max_revision_scan=100):
        return self.engine.audit(
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE + timedelta(minutes=start),
            end_utc=BASE + timedelta(minutes=end),
            max_revision_scan=max_revision_scan,
        )

    def insert(self, minutes, observed=20):
        self.store.upsert_candles(
            [make_candle(i) for i in minutes],
            as_of_utc=BASE + timedelta(minutes=observed),
            observed_at_utc=BASE + timedelta(minutes=observed),
        )

    def test_complete_dataset_passes_with_full_coverage(self):
        self.insert(range(5))
        result = self.audit()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["coverage_ratio"], "1.000000")
        self.assertEqual(result["missing_bar_count"], 0)

    def test_missing_bars_are_reported_including_edges(self):
        self.insert([1, 2, 4])
        result = self.audit()
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["missing_bar_count"], 2)
        self.assertEqual(result["coverage_ratio"], "0.600000")
        self.assertEqual(result["missing_ranges"][0]["missing_bars"], 1)
        self.assertEqual(result["leading_or_trailing_missing_bar_count"], 1)

    def test_historical_revisions_degrade_integrity(self):
        self.insert(range(5))
        self.store.upsert_candles(
            [make_candle(2, "1.1010")],
            as_of_utc=BASE + timedelta(minutes=30),
            observed_at_utc=BASE + timedelta(minutes=30),
        )
        result = self.audit()
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["revision_event_count_in_range"], 1)

    def test_revision_scan_limit_fails_closed(self):
        self.insert(range(5))
        for i in range(3):
            self.store.upsert_candles(
                [make_candle(2, str(Decimal("1.1010") + Decimal(i) * Decimal("0.0001")))],
                as_of_utc=BASE + timedelta(minutes=30 + i),
                observed_at_utc=BASE + timedelta(minutes=30 + i),
            )
        result = self.audit(max_revision_scan=2)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertFalse(result["revision_scan_complete"])

    def test_invalid_range_and_unaligned_start_are_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.audit(
                broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
                start_utc=BASE, end_utc=BASE,
            )
        with self.assertRaises(ValueError):
            self.engine.audit(
                broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
                start_utc=BASE + timedelta(seconds=1),
                end_utc=BASE + timedelta(minutes=1),
            )

    def test_walk_forward_is_chronological_and_embargoes_boundaries(self):
        reports = [report(i) for i in range(100)]
        result = self.engine.walk_forward_split(
            reports, max_horizon_bars=5, timeframe="M1",
            train_fraction=0.6, validation_fraction=0.2,
            minimum_samples_per_partition=1,
        )
        self.assertEqual(result["status"], "READY")
        parts = result["partitions"]
        self.assertLess(parts["train"]["end_utc"], parts["validation"]["start_utc"])
        self.assertLess(parts["validation"]["end_utc"], parts["test"]["start_utc"])
        self.assertGreater(result["purged_boundary_reports"], 0)
        self.assertEqual(result["embargo_seconds"], 300)

    def test_walk_forward_rejects_bad_timestamps_and_small_partitions(self):
        reports = [report(i) for i in range(5)] + [{"evaluated_at_utc": "bad"}]
        result = self.engine.walk_forward_split(
            reports, max_horizon_bars=10, timeframe="M5"
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["rejected_counts"]["INVALID_EVALUATION_TIMESTAMP"], 1)

    def test_walk_forward_requires_aware_timestamps_and_valid_fractions(self):
        naive = self.engine.walk_forward_split(
            [{"evaluated_at_utc": "2026-11-01T00:00:00"}],
            max_horizon_bars=2, timeframe="M1",
        )
        self.assertEqual(naive["rejected_counts"]["INVALID_EVALUATION_TIMESTAMP"], 1)
        with self.assertRaises(ValueError):
            self.engine.walk_forward_split(
                [report(i) for i in range(10)], max_horizon_bars=2,
                timeframe="M1", train_fraction=0.8, validation_fraction=0.3,
            )


if __name__ == "__main__":
    unittest.main()

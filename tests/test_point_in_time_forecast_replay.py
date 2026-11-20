from contextlib import closing
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.storage.market_data_store import Candle, MarketDataStore
from eurusd_ai_monitor.storage.forecast_replay_store import ForecastReplayLedger
from eurusd_ai_monitor.engines.point_in_time_forecast_replay_engine import PointInTimeForecastReplayEngine


BASE = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
PROVENANCE = {
    "provider": "MT5 test fixture", "method": "copy_rates_range",
    "bar_time_basis": "UTC", "price_basis": {"price_basis": "BID"},
}


def add_series(store, count=210, step=0.00001):
    rows = []
    for i in range(count):
        opened = BASE + timedelta(minutes=5*i)
        price = Decimal("1.10000") + Decimal(str(step)) * i
        candle = Candle(
            "Headway-Real", "EURUSD", "M5", opened,
            price, price + Decimal("0.00005"), price - Decimal("0.00005"),
            price, 10, 1, 0,
        )
        seen = opened + timedelta(minutes=5, seconds=1)
        store.upsert_candles(
            [candle], as_of_utc=seen, observed_at_utc=seen,
            source_id="MT5_COPY_RATES_RANGE", provenance=PROVENANCE,
        )
        rows.append((opened, seen))
    return rows


class PointInTimeForecastReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.sqlite"
        self.writer = MarketDataStore(self.db)
        self.rows = add_series(self.writer)
        self.reader = MarketDataStore.open_read_only(self.db)
        self.engine = PointInTimeForecastReplayEngine()

    def tearDown(self):
        self.reader = None
        self.writer = None
        self.temp.cleanup()

    def test_replay_builds_all_horizons_and_future_outcomes(self):
        start = self.rows[100][1]
        end = self.rows[120][1]
        evaluation = self.rows[200][1]
        result = self.engine.run(
            self.reader, broker_server="Headway-Real",
            start_utc=start, end_utc=end, evaluation_cutoff_utc=evaluation,
        )
        self.assertEqual(result["status"], "COMPLETE")
        self.assertGreater(result["forecast_record_count"], 0)
        self.assertEqual(set(result["horizon_metrics"]), {"15M", "1H", "4H"})
        self.assertTrue(all(r["forecast_cutoff_utc"] <= end.isoformat().replace("+00:00", "Z")
                            for r in result["records"]))
        self.assertTrue(any(r["actual_move_pips"] is not None for r in result["records"]))
        self.assertTrue(result["integrity_policy"]["future_outcomes_excluded_from_forecast_snapshot"])

    def test_cutoff_snapshot_excludes_versions_observed_later(self):
        start = self.rows[100][1]
        end = self.rows[101][1]
        result = self.engine.run(
            self.reader, broker_server="Headway-Real",
            start_utc=start, end_utc=end, evaluation_cutoff_utc=self.rows[200][1],
        )
        first = next(r for r in result["records"] if r["forecast_cutoff_utc"] == start.isoformat().replace("+00:00", "Z"))
        self.assertIsNotNone(first["snapshot_sha256"])
        self.assertTrue(first["anchor_version_id"])

    def test_later_correction_does_not_rewrite_prior_forecast_anchor(self):
        start = self.rows[100][1]
        end = self.rows[100][1]
        before = self.engine.run(
            self.reader, broker_server="Headway-Real",
            start_utc=start, end_utc=end, evaluation_cutoff_utc=self.rows[200][1],
        )
        old_anchor = before["records"][0]["anchor_version_id"]
        opened = self.rows[100][0]
        corrected = Candle(
            "Headway-Real", "EURUSD", "M5", opened,
            "1.10500", "1.10505", "1.10495", "1.10500", 12, 1, 0,
        )
        seen = self.rows[150][1]
        self.writer.upsert_candles(
            [corrected], as_of_utc=seen, observed_at_utc=seen,
            source_id="MT5_COPY_RATES_RANGE", provenance=PROVENANCE,
        )
        after = self.engine.run(
            self.reader, broker_server="Headway-Real",
            start_utc=start, end_utc=end, evaluation_cutoff_utc=self.rows[200][1],
        )
        self.assertEqual(before["records"][0]["forecast_cutoff_utc"], after["records"][0]["forecast_cutoff_utc"])
        self.assertEqual(old_anchor, after["records"][0]["anchor_version_id"])
        self.assertEqual(before["records"][0]["snapshot_sha256"], after["records"][0]["snapshot_sha256"])
        self.assertEqual(before["records"][0]["forecast_id"], after["records"][0]["forecast_id"])
        self.assertEqual(before["records"][0]["expected_move_pips"], after["records"][0]["expected_move_pips"])

    def test_identical_replay_request_has_stable_identity(self):
        start, end = self.rows[100][1], self.rows[103][1]
        kwargs = dict(
            broker_server="Headway-Real", start_utc=start, end_utc=end,
            evaluation_cutoff_utc=self.rows[200][1],
        )
        first = self.engine.run(self.reader, **kwargs)
        second = self.engine.run(self.reader, **kwargs)
        self.assertEqual(first["replay_id"], second["replay_id"])
        self.assertEqual(first["source_history_sha256"], second["source_history_sha256"])
        self.assertEqual(
            [r["forecast_id"] for r in first["records"]],
            [r["forecast_id"] for r in second["records"]],
        )

    def test_outcome_not_available_before_future_horizon(self):
        start = self.rows[100][1]
        result = self.engine.run(
            self.reader, broker_server="Headway-Real",
            start_utc=start, end_utc=start, evaluation_cutoff_utc=start,
        )
        self.assertTrue(result["records"])
        self.assertTrue(all(r["actual_move_pips"] is None for r in result["records"]))

    def test_requires_read_only_market_store(self):
        with self.assertRaisesRegex(RuntimeError, "READ_ONLY"):
            self.engine.run(
                self.writer, broker_server="Headway-Real",
                start_utc=self.rows[100][1], end_utc=self.rows[101][1],
            )

    def test_missing_version_ledger_blocks_without_migration(self):
        legacy = Path(self.temp.name) / "legacy.sqlite"
        legacy_writer = MarketDataStore(legacy)
        legacy_writer = None
        with closing(sqlite3.connect(legacy)) as connection:
            connection.execute("DROP TABLE candle_versions")
            connection.execute("DROP TABLE candle_ingestion_runs")
            connection.execute("PRAGMA user_version=3")
        reader = MarketDataStore.open_read_only(legacy)
        result = self.engine.run(
            reader, broker_server="Headway-Real",
            start_utc=self.rows[100][1], end_utc=self.rows[101][1],
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason_codes"], ["CANDLE_VERSION_LEDGER_UNAVAILABLE"])

    def test_ledger_persists_append_only_replay(self):
        start, end = self.rows[100][1], self.rows[103][1]
        replay = self.engine.run(
            self.reader, broker_server="Headway-Real",
            start_utc=start, end_utc=end, evaluation_cutoff_utc=self.rows[200][1],
        )
        path = Path(self.temp.name) / "research" / "replay.sqlite"
        ledger = ForecastReplayLedger(path)
        inserted = ledger.append_run(replay)
        self.assertEqual(inserted["runs_inserted"], 1)
        self.assertEqual(inserted["forecasts_inserted"], replay["forecast_record_count"])
        self.assertEqual(ledger.append_run(replay)["runs_inserted"], 0)
        summary = ledger.get_summary()
        self.assertEqual(summary["forecast_count"], replay["forecast_record_count"])
        self.assertEqual(summary["integrity_check"], "ok")
        with closing(sqlite3.connect(path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE replay_forecasts SET forecast_direction='DOWN'")
            connection.rollback()

    def test_ledger_load_run_round_trips_full_replay_read_only(self):
        replay = self.engine.run(
            self.reader, broker_server="Headway-Real",
            start_utc=self.rows[100][1], end_utc=self.rows[103][1],
            evaluation_cutoff_utc=self.rows[200][1],
        )
        path = Path(self.temp.name) / "research" / "replay-load.sqlite"
        ledger = ForecastReplayLedger(path)
        ledger.append_run(replay)
        loaded = ForecastReplayLedger.load_run(replay["replay_id"], path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["replay_id"], replay["replay_id"])
        self.assertEqual(loaded["source_history_sha256"], replay["source_history_sha256"])
        self.assertEqual(len(loaded["records"]), len(replay["records"]))
        self.assertEqual(loaded["records"][0]["forecast_id"], replay["records"][0]["forecast_id"])
        self.assertEqual(loaded["integrity_policy"], replay["integrity_policy"])

    def test_ledger_load_missing_is_read_only_and_does_not_create(self):
        path = Path(self.temp.name) / "missing" / "replay.sqlite"
        self.assertIsNone(ForecastReplayLedger.load_run("missing-replay", path))
        self.assertFalse(path.exists())

    def test_time_range_validation(self):
        with self.assertRaises(ValueError):
            self.engine.run(
                self.reader, broker_server="Headway-Real",
                start_utc=self.rows[120][1], end_utc=self.rows[100][1],
            )


if __name__ == "__main__":
    unittest.main()

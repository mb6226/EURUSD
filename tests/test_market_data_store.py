import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.storage.market_data_store import (
    Candle,
    MarketDataStore,
)


class MarketDataStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market_data.sqlite"
        self.store = MarketDataStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_candle(
        self,
        open_time: datetime | None = None,
        *,
        close: str = "1.08050",
        high: str = "1.08100",
        broker_server: str = "Demo-Server",
        timeframe: str = "M1",
        tick_volume: int = 12,
    ) -> Candle:
        return Candle(
            broker_server=broker_server,
            symbol="EURUSD",
            timeframe=timeframe,
            candle_open_time_utc=open_time
            or datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc),
            open=Decimal("1.08000"),
            high=Decimal(high),
            low=Decimal("1.07900"),
            close=Decimal(close),
            tick_volume=tick_volume,
            spread=8,
            real_volume=0,
        )

    def test_creates_market_schema_only_in_requested_database(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)

        self.assertEqual(
            tables,
            {
                "candles",
                "candle_revisions",
                "backfill_checkpoints",
                "pa_lifecycle_state",
                "pa_lifecycle_events",
                "pa_lifecycle_recovery",
                "sqlite_sequence",
            },
        )

    def test_backfill_checkpoint_advances_monotonically_and_completes(self):
        start = datetime(2026, 11, 17, tzinfo=timezone.utc)
        middle = start + timedelta(days=1)
        end = start + timedelta(days=2)

        initial = self.store.save_backfill_checkpoint(
            "Demo-Server",
            "EURUSD",
            "M1",
            start,
            end,
            start,
            is_complete=False,
            updated_at_utc=start,
        )
        self.assertEqual(initial.next_from_utc, start)
        self.assertFalse(initial.is_complete)

        advanced = self.store.save_backfill_checkpoint(
            "Demo-Server",
            "EURUSD",
            "M1",
            start,
            end,
            middle,
            is_complete=False,
            updated_at_utc=middle,
        )
        self.store.save_backfill_checkpoint(
            "Demo-Server",
            "EURUSD",
            "M1",
            start,
            end,
            start,
            is_complete=False,
            updated_at_utc=middle + timedelta(minutes=1),
        )
        self.assertEqual(advanced.next_from_utc, middle)
        checkpoint = self.store.get_backfill_checkpoint(
            "Demo-Server", "EURUSD", "M1", start, end
        )
        self.assertEqual(checkpoint.next_from_utc, middle)

        completed = self.store.save_backfill_checkpoint(
            "Demo-Server",
            "EURUSD",
            "M1",
            start,
            end,
            end,
            is_complete=True,
            updated_at_utc=end,
        )
        self.assertEqual(completed.next_from_utc, end)
        self.assertTrue(completed.is_complete)

    def test_v1_market_database_migrates_to_checkpoint_schema(self):
        legacy_path = Path(self.temp_dir.name) / "legacy_market.sqlite"
        MarketDataStore(legacy_path)
        with closing(sqlite3.connect(legacy_path)) as db:
            db.execute("DROP TABLE backfill_checkpoints")
            db.execute("DROP TABLE pa_lifecycle_recovery")
            db.execute("DROP TABLE pa_lifecycle_events")
            db.execute("DROP TABLE pa_lifecycle_state")
            db.execute("PRAGMA user_version = 1")
            db.commit()

        MarketDataStore(legacy_path)

        with closing(sqlite3.connect(legacy_path)) as db:
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertIn("backfill_checkpoints", tables)
        self.assertIn("pa_lifecycle_state", tables)
        self.assertIn("pa_lifecycle_events", tables)
        self.assertIn("pa_lifecycle_recovery", tables)

    def test_v2_market_database_migrates_without_losing_market_data(self):
        legacy_path = Path(self.temp_dir.name) / "v2_market.sqlite"
        legacy_store = MarketDataStore(legacy_path)
        candle = self.make_candle()
        as_of = candle.candle_open_time_utc + timedelta(minutes=1)
        legacy_store.upsert_candles(
            [candle], as_of_utc=as_of, observed_at_utc=as_of
        )
        with closing(sqlite3.connect(legacy_path)) as db:
            db.execute("DROP TABLE pa_lifecycle_recovery")
            db.execute("DROP TABLE pa_lifecycle_events")
            db.execute("DROP TABLE pa_lifecycle_state")
            db.execute("PRAGMA user_version = 2")
            db.commit()

        migrated = MarketDataStore(legacy_path)
        self.assertEqual(
            migrated.get_closed_candles("Demo-Server", "EURUSD", "M1"),
            [candle],
        )
        with closing(sqlite3.connect(legacy_path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue({
            "pa_lifecycle_state", "pa_lifecycle_events", "pa_lifecycle_recovery"
        }.issubset(tables))

    def test_lifecycle_events_are_append_only(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute(
                """
                INSERT INTO pa_lifecycle_state (
                    lifecycle_id, broker_server, symbol, state,
                    state_version, record_version, algorithm_version,
                    parameter_version, last_processed_m5_utc,
                    revision_watermark, snapshot_json, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "lifecycle-1", "Demo-Server", "EURUSD", "CANDIDATE",
                    0, 1, "algo-v1", "params-v1",
                    "2026-11-17T12:00:00.000000Z", 0, "{}", 
                    "2026-11-17T12:00:00.000000Z",
                ),
            )
            db.execute(
                """
                INSERT INTO pa_lifecycle_events (
                    event_id, lifecycle_id, event_sequence, transition_type,
                    previous_state, current_state, occurred_at_utc,
                    reason_codes_json, evidence_refs_json,
                    lifecycle_snapshot_json, revision_watermark, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "event-1", "lifecycle-1", 1, "CREATED", None, "CANDIDATE",
                    "2026-11-17T12:00:00.000000Z", "[]", "[]", "{}", 0,
                    "2026-11-17T12:00:00.000000Z",
                ),
            )
            db.commit()
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "append-only"
            ):
                db.execute(
                    "UPDATE pa_lifecycle_events SET transition_type = 'TAMPERED' "
                    "WHERE event_id = 'event-1'"
                )
            db.rollback()
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "append-only"
            ):
                db.execute(
                    "DELETE FROM pa_lifecycle_events WHERE event_id = 'event-1'"
                )
            db.rollback()
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM pa_lifecycle_events").fetchone()[0],
                1,
            )

    def test_revision_watermark_and_paged_revision_reads_are_scoped_and_ordered(self):
        open_time = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        observed = open_time + timedelta(minutes=1)
        original = self.make_candle(open_time)
        corrected_once = self.make_candle(
            open_time, close="1.08060", high="1.08110"
        )
        corrected_twice = self.make_candle(
            open_time, close="1.08070", high="1.08120"
        )
        self.store.upsert_candles(
            [original], as_of_utc=observed, observed_at_utc=observed
        )
        self.store.upsert_candles(
            [corrected_once],
            as_of_utc=observed + timedelta(minutes=1),
            observed_at_utc=observed + timedelta(minutes=1),
        )
        self.store.upsert_candles(
            [corrected_twice],
            as_of_utc=observed + timedelta(minutes=2),
            observed_at_utc=observed + timedelta(minutes=2),
        )

        watermark = self.store.get_candle_revision_watermark(
            "Demo-Server", "EURUSD", "M1"
        )
        self.assertEqual(watermark, 2)
        self.assertEqual(
            self.store.get_candle_revision_watermark(
                "Other-Server", "EURUSD", "M1"
            ),
            0,
        )
        first_page = self.store.get_candle_revisions(
            "Demo-Server", "EURUSD", "M1", limit=1
        )
        second_page = self.store.get_candle_revisions(
            "Demo-Server", "EURUSD", "M1",
            after_revision_id=first_page[-1].revision_id,
            through_revision_id=watermark,
        )
        self.assertEqual(len(first_page), 1)
        self.assertEqual(len(second_page), 1)
        self.assertLess(first_page[0].revision_id, second_page[0].revision_id)
        self.assertEqual(first_page[0].old_values["close"], "1.08050")
        self.assertEqual(first_page[0].new_values["close"], "1.08060")
        self.assertEqual(second_page[0].old_values["close"], "1.08060")
        self.assertEqual(second_page[0].new_values["close"], "1.08070")
        self.assertEqual(
            self.store.get_candle_revisions(
                "Demo-Server", "EURUSD", "M1",
                after_revision_id=watermark,
            ),
            [],
        )

    def test_revision_query_rejects_invalid_bounds_and_limit(self):
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            self.store.get_candle_revisions(
                "Demo-Server", "EURUSD", "M1", after_revision_id=-1
            )
        with self.assertRaisesRegex(ValueError, "positive integer"):
            self.store.get_candle_revisions(
                "Demo-Server", "EURUSD", "M1", limit=0
            )
        with self.assertRaisesRegex(ValueError, "through_revision_id"):
            self.store.get_candle_revisions(
                "Demo-Server", "EURUSD", "M1",
                after_revision_id=5, through_revision_id=4
            )

    def test_stores_exact_decimal_strings_and_ignores_duplicate_batch_rows(self):
        candle = self.make_candle()
        observed_at = datetime(2026, 11, 17, 12, 2, tzinfo=timezone.utc)
        summary = self.store.upsert_candles(
            [candle, candle],
            as_of_utc=observed_at,
            observed_at_utc=observed_at,
        )

        self.assertEqual(summary.inserted, 1)
        self.assertEqual(summary.duplicates_ignored, 1)
        stored = self.store.get_closed_candles(
            "Demo-Server", "EURUSD", "M1"
        )
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].open, Decimal("1.08000"))
        self.assertEqual(stored[0].close, Decimal("1.08050"))

        with closing(sqlite3.connect(self.db_path)) as db:
            row = db.execute(
                "SELECT open, close FROM candles"
            ).fetchone()
        self.assertEqual(row, ("1.08000", "1.08050"))

    def test_reingestion_is_idempotent_and_preserves_first_seen(self):
        candle = self.make_candle()
        first_seen = datetime(2026, 11, 17, 12, 2, tzinfo=timezone.utc)
        second_seen = first_seen + timedelta(seconds=10)

        self.store.upsert_candles(
            [candle],
            as_of_utc=first_seen,
            observed_at_utc=first_seen,
        )
        summary = self.store.upsert_candles(
            [candle],
            as_of_utc=second_seen,
            observed_at_utc=second_seen,
        )

        self.assertEqual(summary.unchanged, 1)
        with closing(sqlite3.connect(self.db_path)) as db:
            first, last = db.execute(
                "SELECT first_seen_at_utc, last_seen_at_utc FROM candles"
            ).fetchone()
            count = db.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        self.assertEqual(first, "2026-11-17T12:02:00.000000Z")
        self.assertEqual(last, "2026-11-17T12:02:10.000000Z")
        self.assertEqual(count, 1)

    def test_forming_candle_updates_and_is_excluded_until_closed(self):
        open_time = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        first_as_of = open_time + timedelta(seconds=30)
        first = self.make_candle(open_time)
        second = self.make_candle(
            open_time,
            close="1.08070",
            high="1.08120",
            tick_volume=19,
        )

        inserted = self.store.upsert_candles(
            [first],
            as_of_utc=first_as_of,
            observed_at_utc=first_as_of,
        )
        updated = self.store.upsert_candles(
            [second],
            as_of_utc=open_time + timedelta(seconds=45),
            observed_at_utc=open_time + timedelta(seconds=45),
        )
        self.assertEqual(inserted.inserted, 1)
        self.assertEqual(updated.updated, 1)
        self.assertEqual(
            self.store.get_closed_candles("Demo-Server", "EURUSD", "M1"),
            [],
        )

        close_time = open_time + timedelta(minutes=1)
        self.store.upsert_candles(
            [second],
            as_of_utc=close_time,
            observed_at_utc=close_time,
        )
        closed = self.store.get_closed_candles(
            "Demo-Server", "EURUSD", "M1"
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0].close, Decimal("1.08070"))

    def test_closed_candle_correction_is_recorded_before_update(self):
        open_time = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        observed_at = open_time + timedelta(minutes=1)
        original = self.make_candle(open_time)
        corrected = self.make_candle(
            open_time,
            close="1.08060",
            high="1.08110",
        )
        self.store.upsert_candles(
            [original],
            as_of_utc=observed_at,
            observed_at_utc=observed_at,
        )

        correction = self.store.upsert_candles(
            [corrected],
            as_of_utc=observed_at + timedelta(minutes=1),
            observed_at_utc=observed_at + timedelta(minutes=1),
        )

        self.assertEqual(correction.updated, 1)
        self.assertEqual(correction.revisions_recorded, 1)
        with closing(sqlite3.connect(self.db_path)) as db:
            revision = db.execute(
                """
                SELECT old_values_json, new_values_json
                FROM candle_revisions
                """
            ).fetchone()
        old_values, new_values = map(json.loads, revision)
        self.assertEqual(old_values["close"], "1.08050")
        self.assertEqual(new_values["close"], "1.08060")
        self.assertEqual(
            self.store.get_closed_candles(
                "Demo-Server", "EURUSD", "M1"
            )[0].close,
            Decimal("1.08060"),
        )

    def test_query_filters_source_time_range_and_returns_latest_limit_chronologically(self):
        base = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        candles = [
            self.make_candle(base + timedelta(minutes=minute))
            for minute in range(3)
        ]
        other_source = self.make_candle(
            base,
            broker_server="Other-Server",
        )
        as_of = base + timedelta(minutes=5)
        self.store.upsert_candles(
            candles + [other_source],
            as_of_utc=as_of,
            observed_at_utc=as_of,
        )

        result = self.store.get_closed_candles(
            "Demo-Server",
            "EURUSD",
            "M1",
            start_utc=base,
            end_utc=base + timedelta(minutes=3),
            limit=2,
        )
        self.assertEqual(
            [item.candle_open_time_utc for item in result],
            [base + timedelta(minutes=1), base + timedelta(minutes=2)],
        )

    def test_rejects_invalid_timeframe_timestamp_and_non_utc_naive_time(self):
        valid = self.make_candle()
        with self.assertRaisesRegex(ValueError, "Unsupported timeframe"):
            Candle(
                **{
                    **valid.__dict__,
                    "timeframe": "M15",
                }
            )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            Candle(
                **{
                    **valid.__dict__,
                    "candle_open_time_utc": datetime(2026, 11, 17, 12, 0),
                }
            )
        with self.assertRaisesRegex(ValueError, "aligned"):
            self.make_candle(
                datetime(2026, 11, 17, 12, 0, 30, tzinfo=timezone.utc)
            )

    def test_normalizes_aware_non_utc_timestamp_to_utc(self):
        local_time = datetime.fromisoformat("2026-11-17T15:30:00+03:30")
        candle = self.make_candle(local_time)
        self.assertEqual(
            candle.candle_open_time_utc,
            datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc),
        )

    def test_rejects_invalid_ohlc_negative_values_and_non_decimal_floats(self):
        valid = self.make_candle()
        with self.assertRaisesRegex(ValueError, "high must"):
            Candle(**{**valid.__dict__, "high": Decimal("1.08010")})
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            Candle(**{**valid.__dict__, "low": Decimal("-0.001")})
        with self.assertRaisesRegex(TypeError, "Decimal or a decimal string"):
            Candle(**{**valid.__dict__, "close": 1.0805})
        with self.assertRaisesRegex(ValueError, "tick_volume"):
            Candle(**{**valid.__dict__, "tick_volume": -1})
        with self.assertRaisesRegex(ValueError, "spread"):
            Candle(**{**valid.__dict__, "spread": -1})
        with self.assertRaisesRegex(ValueError, "real_volume"):
            Candle(**{**valid.__dict__, "real_volume": -1})

    def test_conflicting_duplicates_in_one_batch_fail_without_partial_write(self):
        open_time = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        first = self.make_candle(open_time)
        conflict = self.make_candle(open_time, close="1.08060")

        with self.assertRaisesRegex(ValueError, "Conflicting candles"):
            self.store.upsert_candles([first, conflict])

        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM candles").fetchone()[0],
                0,
            )

    def test_rejects_invalid_batch_item_before_writing_any_rows(self):
        valid = self.make_candle()
        with self.assertRaisesRegex(TypeError, "only Candle"):
            self.store.upsert_candles([valid, "not a candle"])

        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM candles").fetchone()[0],
                0,
            )

    def test_sqlite_integrity_after_insert_and_revision(self):
        open_time = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        observed_at = open_time + timedelta(minutes=1)
        self.store.upsert_candles(
            [self.make_candle(open_time)],
            as_of_utc=observed_at,
            observed_at_utc=observed_at,
        )
        self.store.upsert_candles(
            [
                self.make_candle(
                    open_time,
                    close="1.08060",
                    high="1.08110",
                )
            ],
            as_of_utc=observed_at + timedelta(minutes=1),
            observed_at_utc=observed_at + timedelta(minutes=1),
        )

        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                db.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                db.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )


if __name__ == "__main__":
    unittest.main()

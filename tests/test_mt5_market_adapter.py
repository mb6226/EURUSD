import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from eurusd_ai_monitor.engines.mt5_engine import MT5Connector
from eurusd_ai_monitor.storage.market_data_store import MarketDataStore
from eurusd_ai_monitor.storage.mt5_market_adapter import (
    BackfillStatus,
    MT5MarketDataAdapter,
    MT5MarketDataError,
)


RATE_FIELDS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)


def rate_row(
    time: datetime,
    *,
    close: float = 1.0805,
    high: float = 1.0810,
    tick_volume: int | float = 12,
) -> dict[str, object]:
    return {
        "time": pd.Timestamp(time),
        "open": np.float64(1.0800),
        "high": np.float64(high),
        "low": np.float64(1.0790),
        "close": np.float64(close),
        "tick_volume": np.int64(tick_volume) if isinstance(tick_volume, int) else tick_volume,
        "spread": np.int64(8),
        "real_volume": np.int64(0),
    }


def rates_frame(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=RATE_FIELDS)


class FakeMT5Connector:
    def __init__(self, frames=None, server="Broker-Demo"):
        self.connected = True
        self.symbol = "EURUSD"
        self.server = server
        self.frames = frames or {}
        self.bars_calls = []
        self.range_calls = []
        self.fail_timeframe = None
        self.fail_range_call = None
        self.range_response = None
        self.server_error = None

    def broker_server(self):
        if self.server_error is not None:
            raise self.server_error
        return self.server

    def bars(self, timeframe, count):
        self.bars_calls.append((timeframe, count))
        if timeframe == self.fail_timeframe:
            raise RuntimeError("mock MT5 disconnect")
        return self.frames[timeframe]

    def bars_range(self, timeframe, start_utc, end_utc):
        self.range_calls.append((timeframe, start_utc, end_utc))
        if self.fail_range_call == len(self.range_calls):
            raise RuntimeError("mock MT5 range disconnect")
        if self.range_response is not None:
            return self.range_response(timeframe, start_utc, end_utc)
        interval = timedelta(minutes=1 if timeframe == "M1" else 5)
        rows = []
        candle_time = start_utc
        while candle_time < end_utc:
            rows.append(rate_row(candle_time))
            candle_time += interval
        return rates_frame(*rows)


class MT5MarketAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market_data.sqlite"
        self.store = MarketDataStore(self.db_path)
        self.now = datetime(2026, 11, 17, 12, 5, tzinfo=timezone.utc)
        self.connector = FakeMT5Connector()
        self.adapter = MT5MarketDataAdapter(
            self.connector,
            self.store,
            clock=lambda: self.now,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def count_candles(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return db.execute("SELECT COUNT(*) FROM candles").fetchone()[0]

    def test_sync_maps_m1_m5_and_returns_only_closed_candles(self):
        m1_time = self.now - timedelta(minutes=1)
        m5_time = self.now - timedelta(minutes=5)
        self.connector.frames = {
            "M1": rates_frame(rate_row(m1_time)),
            "M5": rates_frame(rate_row(m5_time)),
        }

        result = self.adapter.sync_latest()

        self.assertEqual(result.broker_server, "Broker-Demo")
        self.assertEqual(result.timeframes, ("M1", "M5"))
        self.assertEqual(result.records_received, 2)
        self.assertEqual(result.store_summary.inserted, 2)
        m1 = self.store.get_closed_candles(
            "Broker-Demo", "EURUSD", "M1"
        )
        m5 = self.store.get_closed_candles(
            "Broker-Demo", "EURUSD", "M5"
        )
        self.assertEqual(len(m1), 1)
        self.assertEqual(len(m5), 1)
        self.assertEqual(m1[0].close, Decimal("1.0805"))

    def test_current_candle_updates_then_becomes_available_when_closed(self):
        candle_time = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        self.connector.frames = {"M1": rates_frame(rate_row(candle_time))}
        self.now = candle_time + timedelta(seconds=20)
        first = self.adapter.sync_latest(timeframes=("M1",))
        self.assertEqual(first.store_summary.inserted, 1)
        self.assertEqual(
            self.store.get_closed_candles("Broker-Demo", "EURUSD", "M1"),
            [],
        )

        self.connector.frames["M1"] = rates_frame(
            rate_row(candle_time, close=1.0807, high=1.0812, tick_volume=19)
        )
        self.now = candle_time + timedelta(seconds=45)
        second = self.adapter.sync_latest(timeframes=("M1",))
        self.assertEqual(second.store_summary.updated, 1)
        self.assertEqual(self.count_candles(), 1)

        self.now = candle_time + timedelta(minutes=1)
        self.adapter.sync_latest(timeframes=("M1",))
        closed = self.store.get_closed_candles(
            "Broker-Demo", "EURUSD", "M1"
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(str(closed[0].close), "1.0807")

    def test_second_timeframe_failure_does_not_store_first_timeframe(self):
        self.connector.frames = {
            "M1": rates_frame(rate_row(self.now - timedelta(minutes=1))),
            "M5": rates_frame(rate_row(self.now - timedelta(minutes=5))),
        }
        self.connector.fail_timeframe = "M5"

        with self.assertRaisesRegex(MT5MarketDataError, "Failed to fetch M5"):
            self.adapter.sync_latest()

        self.assertEqual(self.count_candles(), 0)

    def test_disconnected_connector_is_rejected_before_fetch(self):
        self.connector.connected = False

        with self.assertRaisesRegex(MT5MarketDataError, "not connected"):
            self.adapter.sync_latest()

        self.assertEqual(self.connector.bars_calls, [])

    def test_unknown_broker_server_is_rejected_before_fetch(self):
        self.connector.server = " "

        with self.assertRaisesRegex(MT5MarketDataError, "empty broker server"):
            self.adapter.sync_latest()

        self.assertEqual(self.connector.bars_calls, [])
        self.assertEqual(self.count_candles(), 0)

    def test_broker_lookup_failure_is_explicit(self):
        self.connector.server_error = RuntimeError("account unavailable")

        with self.assertRaisesRegex(MT5MarketDataError, "identify broker"):
            self.adapter.sync_latest()

        self.assertEqual(self.connector.bars_calls, [])

    def test_invalid_rate_rows_are_rejected_without_writing(self):
        candle_time = self.now - timedelta(minutes=1)
        self.connector.frames = {
            "M1": rates_frame(
                rate_row(candle_time, close=1.0820, high=1.0810)
            )
        }

        with self.assertRaisesRegex(MT5MarketDataError, "Invalid MT5 M1"):
            self.adapter.sync_latest(timeframes=("M1",))

        self.assertEqual(self.count_candles(), 0)

    def test_non_integer_volume_is_rejected_without_truncation(self):
        row = rate_row(self.now - timedelta(minutes=1), tick_volume=12.5)
        self.connector.frames = {"M1": rates_frame(row)}

        with self.assertRaisesRegex(MT5MarketDataError, "finite integer"):
            self.adapter.sync_latest(timeframes=("M1",))

        self.assertEqual(self.count_candles(), 0)

    def test_missing_fields_and_empty_rates_are_not_successful(self):
        self.connector.frames = {
            "M1": pd.DataFrame([{"time": pd.Timestamp(self.now)}])
        }
        with self.assertRaisesRegex(MT5MarketDataError, "missing fields"):
            self.adapter.sync_latest(timeframes=("M1",))

        self.connector.frames = {"M1": rates_frame()}
        with self.assertRaisesRegex(MT5MarketDataError, "no M1 candle"):
            self.adapter.sync_latest(timeframes=("M1",))
        self.assertEqual(self.count_candles(), 0)

    def test_repeated_sync_uses_upsert_without_duplicate_candles(self):
        candle_time = self.now - timedelta(minutes=1)
        self.connector.frames = {"M1": rates_frame(rate_row(candle_time))}

        first = self.adapter.sync_latest(timeframes=("M1",))
        second = self.adapter.sync_latest(timeframes=("M1",))

        self.assertEqual(first.store_summary.inserted, 1)
        self.assertEqual(second.store_summary.unchanged, 1)
        self.assertEqual(self.count_candles(), 1)

    def test_backfill_uses_bounded_chunks_and_persists_checkpoint(self):
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(days=3)

        result = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
            chunk_days=1,
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.status, BackfillStatus.COMPLETE)
        self.assertEqual(result.chunks_processed, 3)
        self.assertEqual(result.records_received, 3 * 24 * 60)
        self.assertEqual(
            [call[2] - call[1] for call in self.connector.range_calls],
            [timedelta(days=1)] * 3,
        )
        checkpoint = self.store.get_backfill_checkpoint(
            "Broker-Demo", "EURUSD", "M1", start, end
        )
        self.assertTrue(checkpoint.is_complete)
        self.assertEqual(checkpoint.next_from_utc, end)
        self.assertEqual(self.count_candles(), 3 * 24 * 60)

        calls_before = len(self.connector.range_calls)
        resumed = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
            chunk_days=1,
        )
        self.assertEqual(resumed.chunks_processed, 0)
        self.assertEqual(len(self.connector.range_calls), calls_before)

    def test_backfill_resumes_from_last_committed_checkpoint_after_failure(self):
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(days=3)
        self.connector.fail_range_call = 2

        with self.assertRaisesRegex(MT5MarketDataError, "backfill chunk"):
            self.adapter.backfill(
                start,
                end,
                timeframes=("M1",),
                chunk_days=1,
            )

        checkpoint = self.store.get_backfill_checkpoint(
            "Broker-Demo", "EURUSD", "M1", start, end
        )
        self.assertFalse(checkpoint.is_complete)
        self.assertEqual(checkpoint.next_from_utc, start + timedelta(days=1))
        self.assertEqual(self.count_candles(), 24 * 60)

        self.connector.fail_range_call = None
        self.connector.range_calls.clear()
        result = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
            chunk_days=1,
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.status, BackfillStatus.COMPLETE)
        self.assertEqual(result.chunks_processed, 2)
        self.assertEqual(self.connector.range_calls[0][1], start + timedelta(days=1))
        self.assertEqual(self.count_candles(), 3 * 24 * 60)

    def test_empty_holiday_like_chunk_is_unknown_without_a_calendar(self):
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        self.connector.range_response = lambda timeframe, chunk_start, chunk_end: rates_frame()

        result = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
            chunk_days=1,
        )

        checkpoint = self.store.get_backfill_checkpoint(
            "Broker-Demo", "EURUSD", "M1", start, end
        )
        self.assertFalse(result.completed)
        self.assertEqual(result.status, BackfillStatus.UNKNOWN)
        self.assertEqual(result.chunks_processed, 0)
        self.assertFalse(checkpoint.is_complete)
        self.assertEqual(checkpoint.next_from_utc, start)
        self.assertEqual(self.count_candles(), 0)

    def test_insufficient_history_returns_unknown_without_storing_partial_chunk(self):
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(minutes=3)
        self.connector.range_response = lambda timeframe, chunk_start, chunk_end: (
            rates_frame(rate_row(chunk_start))
        )

        result = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
        )

        checkpoint = self.store.get_backfill_checkpoint(
            "Broker-Demo", "EURUSD", "M1", start, end
        )
        self.assertEqual(result.status, BackfillStatus.UNKNOWN)
        self.assertFalse(result.completed)
        self.assertEqual(checkpoint.next_from_utc, start)
        self.assertEqual(self.count_candles(), 0)

    def test_chunk_with_unclassified_gap_returns_unknown_without_writing(self):
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(minutes=3)
        self.connector.range_response = lambda timeframe, chunk_start, chunk_end: (
            rates_frame(
                rate_row(chunk_start),
                rate_row(chunk_start + timedelta(minutes=2)),
            )
        )

        result = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
        )

        checkpoint = self.store.get_backfill_checkpoint(
            "Broker-Demo", "EURUSD", "M1", start, end
        )
        self.assertEqual(result.status, BackfillStatus.UNKNOWN)
        self.assertEqual(checkpoint.next_from_utc, start)
        self.assertEqual(self.count_candles(), 0)

    def test_contiguous_chunk_is_completed(self):
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(minutes=3)

        result = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
        )

        self.assertEqual(result.status, BackfillStatus.COMPLETE)
        self.assertTrue(result.completed)
        self.assertEqual(result.records_received, 3)
        self.assertEqual(self.count_candles(), 3)

    def test_backfill_excludes_inclusive_end_boundary_candle(self):
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(minutes=3)
        self.connector.range_response = lambda timeframe, start, end: rates_frame(
            rate_row(start),
            rate_row(start + timedelta(minutes=1)),
            rate_row(start + timedelta(minutes=2)),
            rate_row(end),
        )

        result = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
            chunk_days=1,
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.records_received, 3)
        candles = self.store.get_closed_candles(
            "Broker-Demo", "EURUSD", "M1"
        )
        self.assertEqual(len(candles), 3)
        self.assertEqual(candles[0].candle_open_time_utc, start)
        self.assertEqual(
            candles[-1].candle_open_time_utc,
            end - timedelta(minutes=1),
        )

    def test_checkpoint_failure_after_store_commit_replays_safely(self):
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(minutes=3)
        save_checkpoint = self.store.save_backfill_checkpoint
        calls = 0

        def fail_after_initial_checkpoint(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("mock checkpoint write failure")
            return save_checkpoint(*args, **kwargs)

        with patch.object(
            self.store,
            "save_backfill_checkpoint",
            side_effect=fail_after_initial_checkpoint,
        ):
            with self.assertRaisesRegex(RuntimeError, "checkpoint write failure"):
                self.adapter.backfill(
                    start,
                    end,
                    timeframes=("M1",),
                )

        checkpoint = self.store.get_backfill_checkpoint(
            "Broker-Demo", "EURUSD", "M1", start, end
        )
        self.assertEqual(checkpoint.next_from_utc, start)
        self.assertEqual(self.count_candles(), 3)

        replay = self.adapter.backfill(
            start,
            end,
            timeframes=("M1",),
        )
        self.assertEqual(replay.status, BackfillStatus.COMPLETE)
        self.assertEqual(replay.store_summary.unchanged, 3)
        self.assertEqual(self.count_candles(), 3)


class MT5ConnectorMethodTests(unittest.TestCase):
    def test_reads_broker_from_active_account_without_initializing_mt5(self):
        connector = MT5Connector("EURUSD")
        connector.connected = True
        with (
            patch(
                "eurusd_ai_monitor.engines.mt5_engine.mt5.account_info",
                return_value=SimpleNamespace(server="Actual-Demo-Server"),
            ),
            patch(
                "eurusd_ai_monitor.engines.mt5_engine.mt5.initialize"
            ) as initialize,
        ):
            self.assertEqual(connector.broker_server(), "Actual-Demo-Server")
        initialize.assert_not_called()

    def test_broker_server_requires_real_account_server_value(self):
        connector = MT5Connector("EURUSD")
        connector.connected = True
        with patch(
            "eurusd_ai_monitor.engines.mt5_engine.mt5.account_info",
            return_value=SimpleNamespace(server=""),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not provide"):
                connector.broker_server()

    def test_bars_range_uses_utc_copy_rates_range_on_existing_connection(self):
        connector = MT5Connector("EURUSD")
        connector.connected = True
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(minutes=2)
        rates = np.array(
            [
                (int(start.timestamp()), 1.0800, 1.0810, 1.0790, 1.0805, 12, 8, 0),
            ],
            dtype=[
                ("time", "i8"),
                ("open", "f8"),
                ("high", "f8"),
                ("low", "f8"),
                ("close", "f8"),
                ("tick_volume", "i8"),
                ("spread", "i8"),
                ("real_volume", "i8"),
            ],
        )
        with patch(
            "eurusd_ai_monitor.engines.mt5_engine.mt5.copy_rates_range",
            return_value=rates,
        ) as copy_rates:
            frame = connector.bars_range("M1", start, end)

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["time"], pd.Timestamp(start))
        args = copy_rates.call_args.args
        self.assertEqual(args[0], "EURUSD")
        self.assertEqual(args[2:], (start, end))

    def test_bars_range_none_response_is_a_fetch_error(self):
        connector = MT5Connector("EURUSD")
        connector.connected = True
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(minutes=2)
        with (
            patch(
                "eurusd_ai_monitor.engines.mt5_engine.mt5.copy_rates_range",
                return_value=None,
            ),
            patch(
                "eurusd_ai_monitor.engines.mt5_engine.mt5.last_error",
                return_value=(-1, "mock MT5 history error"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "No M1 bars"):
                connector.bars_range("M1", start, end)

    def test_bars_range_rejects_disconnected_or_invalid_requests(self):
        connector = MT5Connector("EURUSD")
        start = datetime(2026, 11, 2, tzinfo=timezone.utc)
        end = start + timedelta(minutes=2)
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            connector.bars_range("M1", start, end)

        connector.connected = True
        with self.assertRaisesRegex(ValueError, "Unsupported timeframe"):
            connector.bars_range("M15", start, end)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            connector.bars_range(
                "M1",
                datetime(2026, 11, 2),
                end,
            )


if __name__ == "__main__":
    unittest.main()

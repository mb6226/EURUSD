from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.engines.market_context_builder import MarketContextBuilder
from eurusd_ai_monitor.models.context_quality import ContextQuality
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.market_data_store import Candle


NOW = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
BROKER = "Fake-Broker"


def make_candle(tf: str, open_time: datetime) -> Candle:
    return Candle(
        broker_server=BROKER,
        symbol="EURUSD",
        timeframe=tf,
        candle_open_time_utc=open_time,
        open=Decimal("1.08000"),
        high=Decimal("1.08100"),
        low=Decimal("1.07900"),
        close=Decimal("1.08050"),
        tick_volume=10,
        spread=8,
        real_volume=0,
    )


class FakeConnector:
    symbol = "EURUSD"

    def __init__(self, tick=None, broker=BROKER):
        self._tick = tick or {
            "time": NOW.isoformat(),
            "bid": 1.0800,
            "ask": 1.08008,
            "last": 1.08004,
            "spread_pips": 0.8,
        }
        self._broker = broker
        self.tick_error = None

    def broker_server(self):
        return self._broker

    def tick(self):
        if self.tick_error:
            raise self.tick_error
        return self._tick


class FakeStore:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    def get_closed_candles(self, broker, symbol, timeframe, **kwargs):
        self.calls.append((broker, symbol, timeframe, kwargs))
        return self.frames.get(timeframe, [])


class FakeAdapter:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def sync_latest(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail
        return object()


def three_candles(tf: str, interval_minutes: int, last_close_time: datetime):
    interval = timedelta(minutes=interval_minutes)
    return [
        make_candle(tf, last_close_time - interval * 3),
        make_candle(tf, last_close_time - interval * 2),
        make_candle(tf, last_close_time - interval),
    ]


class MarketContextBuilderTests(unittest.TestCase):
    def build_parts(self, *, m1_close=NOW - timedelta(minutes=1), m5_close=NOW - timedelta(minutes=5)):
        connector = FakeConnector()
        store = FakeStore({
            "M1": three_candles("M1", 1, m1_close),
            "M5": three_candles("M5", 5, m5_close),
        })
        adapter = FakeAdapter()
        builder = MarketContextBuilder(
            connector,
            store,
            adapter,
            clock=lambda: NOW,
            minimum_candles=3,
        )
        return builder, connector, store, adapter

    def test_builds_valid_snapshot_from_closed_store_candles(self):
        builder, connector, store, adapter = self.build_parts()
        snapshot = builder.build(count=100)

        self.assertIsInstance(snapshot, MarketSnapshot)
        self.assertEqual(snapshot.symbol, "EURUSD")
        self.assertEqual(snapshot.broker_server, BROKER)
        self.assertEqual(snapshot.timestamp_utc, NOW)
        self.assertEqual(len(snapshot.m1_candles), 3)
        self.assertEqual(len(snapshot.m5_candles), 3)
        self.assertEqual(snapshot.m1_candles[-1].timeframe, "M1")
        self.assertEqual(snapshot.m5_candles[-1].timeframe, "M5")
        self.assertEqual(snapshot.spread_pips, Decimal("0.8"))
        self.assertTrue(snapshot.quality.is_valid)
        self.assertEqual(snapshot.quality.candle_counts, {"M1": 3, "M5": 3})
        self.assertEqual(adapter.calls[0]["timeframes"], ("M1", "M5"))
        self.assertEqual(adapter.calls[0]["count"], 100)
        self.assertEqual(len(store.calls), 2)

    def test_stale_timeframe_invalidates_snapshot(self):
        builder, *_ = self.build_parts(m1_close=NOW - timedelta(minutes=5))
        snapshot = builder.build()

        self.assertFalse(snapshot.quality.is_valid)
        self.assertTrue(any("M1 data is stale" in issue for issue in snapshot.quality.issues))

    def test_sync_error_is_reported_and_snapshot_is_invalid(self):
        builder, connector, store, adapter = self.build_parts()
        adapter.fail = RuntimeError("simulated sync outage")
        snapshot = builder.build()

        self.assertFalse(snapshot.quality.is_valid)
        self.assertTrue(any("Market data sync failed" in issue for issue in snapshot.quality.issues))
        # The builder still tries to read already stored candles for diagnostics.
        self.assertEqual(len(store.calls), 2)

    def test_tick_failure_is_warning_not_candle_quality_failure(self):
        builder, connector, *_ = self.build_parts()
        connector.tick_error = RuntimeError("tick unavailable")
        snapshot = builder.build()

        self.assertTrue(snapshot.quality.is_valid)
        self.assertIsNone(snapshot.tick)
        self.assertIsNone(snapshot.spread_pips)
        self.assertTrue(snapshot.quality.warnings)

    def test_insufficient_history_marks_missing_timeframe(self):
        builder, connector, store, adapter = self.build_parts()
        store.frames["M5"] = []
        snapshot = builder.build()

        self.assertFalse(snapshot.quality.is_valid)
        self.assertIn("M5", snapshot.quality.missing_timeframes)
        self.assertEqual(snapshot.m5_candles, ())

    def test_invalid_timeframe_and_count_rejected(self):
        builder, *_ = self.build_parts()
        with self.assertRaises(ValueError):
            builder.build(timeframes=("M1", "H1"))
        with self.assertRaises(ValueError):
            builder.build(count=0)

    def test_quality_model_rejects_valid_with_issues(self):
        with self.assertRaises(ValueError):
            ContextQuality(is_valid=True, issues=("bad data",))

    def test_snapshot_rejects_wrong_timeframe_candle_assignment(self):
        candle = make_candle("M5", NOW - timedelta(minutes=5))
        quality = ContextQuality(is_valid=True)
        with self.assertRaises(ValueError):
            MarketSnapshot(
                symbol="EURUSD",
                timestamp_utc=NOW,
                broker_server=BROKER,
                m1_candles=(candle,),
                m5_candles=(),
                tick=None,
                spread_pips=None,
                quality=quality,
            )


if __name__ == "__main__":
    unittest.main()

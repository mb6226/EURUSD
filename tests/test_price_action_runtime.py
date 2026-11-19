from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from eurusd_ai_monitor.engines.price_action_coordinator import PriceActionCoordinator
from eurusd_ai_monitor.engines.price_action_runtime import (
    PriceActionRuntime,
    PriceActionRuntimeStatus,
    RecoveryStatus,
)
from eurusd_ai_monitor.models.context_quality import ContextQuality
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.lifecycle_store import (
    LifecycleStore,
    LifecycleStoreStatus,
)
from eurusd_ai_monitor.storage.market_data_store import Candle, MarketDataStore
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


def history_with_candidate():
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
    return history + (candle(13, "1.10800", "1.10650"),)


def make_snapshot(candles, *, valid=True):
    return MarketSnapshot(
        symbol=SYMBOL,
        timestamp_utc=candles[-1].candle_open_time_utc + timedelta(minutes=5),
        broker_server=BROKER,
        m1_candles=(),
        m5_candles=tuple(candles),
        tick=None,
        spread_pips=None,
        quality=ContextQuality(
            is_valid=valid,
            issues=() if valid else ("synthetic invalid context",),
        ),
    )


class FakeRecoveryGate:
    def __init__(self, status=RecoveryStatus.NORMAL):
        self.status = status
        self.calls = []

    def get_status(self, broker_server, symbol):
        self.calls.append((broker_server, symbol))
        return self.status


class PriceActionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.market = MarketDataStore(Path(self.temp_dir.name) / "market.sqlite")
        self.store = LifecycleStore(self.market)
        self.config = load_strategy_config()
        self.gate = FakeRecoveryGate()
        self.runtime = PriceActionRuntime(
            coordinator=PriceActionCoordinator(),
            lifecycle_store=self.store,
            config=self.config,
            recovery_gate=self.gate,
        )
        self.candles = history_with_candidate()
        self.snapshot = make_snapshot(self.candles)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_creates_and_persists_first_candidate(self):
        result = self.runtime.process(self.snapshot)

        self.assertEqual(result.status, PriceActionRuntimeStatus.PROCESSED)
        self.assertEqual(result.lifecycle_state.value, "CANDIDATE")
        self.assertEqual(result.persistence_status, LifecycleStoreStatus.CREATED)
        self.assertEqual(result.record_version, 1)
        self.assertEqual(result.state_version, 0)
        self.assertEqual(result.trade_authority, "NONE")
        self.assertIsNotNone(self.store.load_active(BROKER, SYMBOL))
        stored = self.store.load_active_record(BROKER, SYMBOL)
        self.assertEqual(stored.record_version, 1)
        self.assertEqual(stored.revision_watermark, 0)

    def test_no_candidate_is_not_persisted(self):
        snapshot = make_snapshot(self.candles[:-1])
        result = self.runtime.process(snapshot)

        self.assertEqual(result.status, PriceActionRuntimeStatus.NO_LIFECYCLE)
        self.assertIsNone(result.lifecycle_id)
        self.assertIsNone(self.store.load_active(BROKER, SYMBOL))

    def test_invalid_context_stops_before_recovery_or_storage(self):
        snapshot = make_snapshot(self.candles, valid=False)
        result = self.runtime.process(snapshot)

        self.assertEqual(result.status, PriceActionRuntimeStatus.WAIT_INVALID_CONTEXT)
        self.assertEqual(self.gate.calls, [])
        self.assertIsNone(self.store.load_active(BROKER, SYMBOL))

    def test_non_normal_recovery_status_blocks_processing(self):
        self.gate.status = RecoveryStatus.RECONCILIATION
        result = self.runtime.process(self.snapshot)

        self.assertEqual(result.status, PriceActionRuntimeStatus.WAIT_RECOVERY)
        self.assertEqual(result.recovery_status, RecoveryStatus.RECONCILIATION)
        self.assertIsNone(self.store.load_active(BROKER, SYMBOL))

    def test_active_lifecycle_version_mismatch_is_blocked(self):
        created = self.runtime.process(self.snapshot)
        self.assertEqual(created.status, PriceActionRuntimeStatus.PROCESSED)

        changed_config = replace(
            self.config,
            take_profit_pips=Decimal("60"),
        )
        changed_runtime = PriceActionRuntime(
            coordinator=PriceActionCoordinator(),
            lifecycle_store=self.store,
            config=changed_config,
            recovery_gate=self.gate,
        )
        result = changed_runtime.process(self.snapshot)

        self.assertEqual(result.status, PriceActionRuntimeStatus.WAIT_VERSION_MISMATCH)
        self.assertEqual(result.record_version, 1)
        self.assertEqual(result.reason_codes, ("ACTIVE_LIFECYCLE_VERSION_MISMATCH",))

    def test_unreconciled_m5_revision_blocks_active_lifecycle(self):
        created = self.runtime.process(self.snapshot)
        self.assertEqual(created.status, PriceActionRuntimeStatus.PROCESSED)

        source = self.candles[-1]
        close_time = source.candle_open_time_utc + timedelta(minutes=5)
        self.market.upsert_candles(
            [source], as_of_utc=close_time, observed_at_utc=close_time
        )
        revised = replace(source, close=source.close + Decimal("0.00001"))
        self.market.upsert_candles(
            [revised], as_of_utc=close_time, observed_at_utc=close_time
        )

        result = self.runtime.process(self.snapshot)
        self.assertEqual(result.status, PriceActionRuntimeStatus.WAIT_RECOVERY)
        self.assertEqual(
            result.reason_codes, ("UNRECONCILED_M5_CANDLE_REVISION",)
        )
        self.assertEqual(result.record_version, 1)

    def test_runtime_uses_full_history_to_resume_existing_lifecycle(self):
        created = self.runtime.process(self.snapshot)
        self.assertEqual(created.status, PriceActionRuntimeStatus.PROCESSED)

        next_candle = candle(14, "1.10780", "1.10680")
        resumed_snapshot = make_snapshot(self.candles + (next_candle,))
        result = self.runtime.process(resumed_snapshot)

        self.assertEqual(result.status, PriceActionRuntimeStatus.PROCESSED)
        self.assertEqual(result.lifecycle_id, created.lifecycle_id)
        self.assertEqual(result.trade_authority, "NONE")
        stored = self.store.load_active_record(BROKER, SYMBOL)
        self.assertEqual(stored.lifecycle.last_processed_m5_utc, next_candle.candle_open_time_utc)
        self.assertEqual(stored.record_version, 2)


if __name__ == "__main__":
    unittest.main()

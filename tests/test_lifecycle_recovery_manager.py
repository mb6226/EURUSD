from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from eurusd_ai_monitor.engines.lifecycle_recovery_manager import LifecycleRecoveryManager
from eurusd_ai_monitor.engines.price_action_coordinator import PriceActionCoordinator
from eurusd_ai_monitor.engines.price_action_runtime import (
    PriceActionRuntime,
    RecoveryStatus,
)
from eurusd_ai_monitor.models.context_quality import ContextQuality
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.lifecycle_store import LifecycleStore
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


def snapshot(candles):
    return MarketSnapshot(
        symbol=SYMBOL,
        timestamp_utc=candles[-1].candle_open_time_utc + timedelta(minutes=5),
        broker_server=BROKER,
        m1_candles=(),
        m5_candles=tuple(candles),
        tick=None,
        spread_pips=None,
        quality=ContextQuality(is_valid=True),
    )


class NormalGate:
    def get_status(self, broker_server, symbol):
        return RecoveryStatus.NORMAL


class LifecycleRecoveryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.market = MarketDataStore(Path(self.temp_dir.name) / "market.sqlite")
        self.store = LifecycleStore(self.market)
        self.manager = LifecycleRecoveryManager(self.store, self.market)
        self.config = load_strategy_config()
        self.candles = history_with_candidate()
        self.as_of = self.candles[-1].candle_open_time_utc + timedelta(minutes=5)
        self.market.upsert_candles(
            self.candles, as_of_utc=self.as_of, observed_at_utc=self.as_of
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_active_lifecycle(self):
        runtime = PriceActionRuntime(
            coordinator=PriceActionCoordinator(),
            lifecycle_store=self.store,
            config=self.config,
            recovery_gate=NormalGate(),
        )
        result = runtime.process(snapshot(self.candles))
        self.assertEqual(result.status.value, "PROCESSED")
        return result

    def test_empty_stream_recovers_to_normal_and_persists_status(self):
        status = self.manager.recover_stream(BROKER, SYMBOL, self.config)
        self.assertEqual(status, RecoveryStatus.NORMAL)
        record = self.store.get_recovery_record(BROKER, SYMBOL)
        self.assertEqual(record["status"], "NORMAL")
        self.assertEqual(record["reason_code"], "RECOVERY_VALIDATED")
        self.assertEqual(self.manager.get_status(BROKER, SYMBOL), RecoveryStatus.NORMAL)

    def test_active_lifecycle_and_event_chain_recover_to_normal(self):
        self.create_active_lifecycle()
        status = self.manager.recover_stream(BROKER, SYMBOL, self.config)
        self.assertEqual(status, RecoveryStatus.NORMAL)
        self.assertEqual(
            self.store.get_recovery_record(BROKER, SYMBOL)["details"]["audited_lifecycles"],
            1,
        )

    def test_revision_change_requires_reconciliation_without_rewriting_state(self):
        self.create_active_lifecycle()
        before = self.store.load_active_record(BROKER, SYMBOL)
        source = self.candles[-1]
        revised = replace(source, close=source.close + Decimal("0.00001"))
        self.market.upsert_candles(
            [revised], as_of_utc=self.as_of, observed_at_utc=self.as_of
        )

        status = self.manager.recover_stream(BROKER, SYMBOL, self.config)
        after = self.store.load_active_record(BROKER, SYMBOL)
        self.assertEqual(status, RecoveryStatus.RECONCILIATION)
        self.assertEqual(after.record_version, before.record_version)
        self.assertEqual(after.lifecycle, before.lifecycle)
        self.assertEqual(
            self.store.get_recovery_record(BROKER, SYMBOL)["reason_code"],
            "M5_CANDLE_REVISION_REQUIRES_REPLAY",
        )

    def test_parameter_version_change_quarantines_active_lifecycle(self):
        from dataclasses import replace as dc_replace
        self.create_active_lifecycle()
        changed = dc_replace(
            self.config,
            take_profit_pips=Decimal("60"),
        )
        status = self.manager.recover_stream(BROKER, SYMBOL, changed)
        self.assertEqual(status, RecoveryStatus.QUARANTINED)
        self.assertEqual(
            self.store.get_recovery_record(BROKER, SYMBOL)["reason_code"],
            "ACTIVE_LIFECYCLE_VERSION_MISMATCH",
        )

    def test_missing_evidence_candle_quarantines_active_lifecycle(self):
        self.create_active_lifecycle()
        lifecycle = self.store.load_active(BROKER, SYMBOL)
        evidence_time = lifecycle.impulse.start_pivot.candle.candle_open_time_utc
        with self.market._connect() as connection:
            connection.execute(
                """
                DELETE FROM candles
                WHERE broker_server = ? AND symbol = ? AND timeframe = 'M5'
                  AND candle_open_time_utc = ?
                """,
                (
                    BROKER,
                    SYMBOL,
                    evidence_time.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                ),
            )
            connection.commit()
        status = self.manager.recover_stream(BROKER, SYMBOL, self.config)
        self.assertEqual(status, RecoveryStatus.QUARANTINED)
        self.assertEqual(
            self.store.get_recovery_record(BROKER, SYMBOL)["reason_code"],
            "ACTIVE_LIFECYCLE_EVIDENCE_MISMATCH",
        )

    def test_missing_startup_record_fails_closed(self):
        self.assertEqual(
            self.manager.get_status(BROKER, SYMBOL),
            RecoveryStatus.RECONCILIATION,
        )


if __name__ == "__main__":
    unittest.main()

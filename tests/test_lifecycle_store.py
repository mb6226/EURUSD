from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from eurusd_ai_monitor.engines.correction_detector import CorrectionDetector
from eurusd_ai_monitor.engines.impulse_detector import ImpulseDetector
from eurusd_ai_monitor.engines.technical_engine import TechnicalEngine
from eurusd_ai_monitor.models.correction_lifecycle import (
    LifecycleState,
    TransitionResult,
    TransitionType,
)
from eurusd_ai_monitor.models.price_action import (
    EvidenceRef,
    EvidenceRole,
    MarketContext,
    TrendDirection,
)
from eurusd_ai_monitor.storage.lifecycle_store import (
    LifecycleConcurrencyConflict,
    LifecycleIntegrityError,
    LifecycleRevisionConflict,
    LifecycleStore,
    LifecycleStoreStatus,
)
from eurusd_ai_monitor.storage.market_data_store import Candle, MarketDataStore
from eurusd_ai_monitor.strategy_config import load_strategy_config


BASE = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
BROKER = "Mock-Broker"
SYMBOL = "EURUSD"


def candle(index, high, low, *, timeframe="M5"):
    high = Decimal(str(high))
    low = Decimal(str(low))
    close = (high + low) / Decimal(2)
    return Candle(
        broker_server=BROKER,
        symbol=SYMBOL,
        timeframe=timeframe,
        candle_open_time_utc=BASE + timedelta(minutes=5 * index),
        open=close,
        high=high,
        low=low,
        close=close,
        tick_volume=10,
        spread=2,
        real_volume=0,
    )


def make_candidate():
    config = load_strategy_config()
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
    context = MarketContext(
        symbol=SYMBOL,
        source_id=BROKER,
        as_of_utc=history[-1].candle_open_time_utc + timedelta(minutes=5),
        m1_candles=(),
        m5_candles=history,
    )
    structure = TechnicalEngine(config).analyze_m5(context)
    impulse = ImpulseDetector().detect(structure, config.pip_size)
    first_correction = candle(13, "1.10800", "1.10650")
    all_candles = history + (first_correction,)
    lifecycle = CorrectionDetector().detect_candidate(
        impulse,
        TrendDirection.UP,
        all_candles,
        all_candles[-1].candle_open_time_utc + timedelta(minutes=5),
        Decimal("5"),
        Decimal("0.80"),
    )
    if lifecycle is None:
        raise AssertionError("fixture did not produce a correction candidate")
    transition = TransitionResult(
        transition_type=TransitionType.CREATED,
        previous_state=None,
        current_state=LifecycleState.CANDIDATE,
        lifecycle=lifecycle,
        occurred_at_utc=lifecycle.last_processed_m5_utc + timedelta(minutes=5),
        reason_codes=("CORRECTION_THRESHOLD_REACHED",),
        evidence_refs=(lifecycle.candidate_start_evidence, lifecycle.extreme_evidence),
    )
    return lifecycle, transition


class LifecycleStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market.sqlite"
        self.market = MarketDataStore(self.db_path)
        self.store = LifecycleStore(self.market)
        self.lifecycle, self.created = make_candidate()
        self.created_at = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_dir.cleanup()

    def save_created(self):
        return self.store.save_transition(
            self.created,
            expected_record_version=None,
            revision_watermark=0,
            created_at_utc=self.created_at,
        )

    def test_create_event_and_snapshot_are_atomic_and_recoverable(self):
        saved = self.save_created()
        self.assertEqual(saved.status, LifecycleStoreStatus.CREATED)
        self.assertEqual(saved.state_version, 0)
        self.assertEqual(saved.record_version, 1)
        self.assertEqual(saved.event_sequence, 1)
        self.assertEqual(self.store.load_by_id(self.lifecycle.lifecycle_id), self.lifecycle)
        self.assertEqual(self.store.load_active(BROKER, SYMBOL), self.lifecycle)
        events = self.store.get_events(self.lifecycle.lifecycle_id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].transition, self.created)
        self.assertEqual(self.store.get_last_processed(BROKER, SYMBOL), self.lifecycle.last_processed_m5_utc)

    def test_duplicate_event_is_idempotent_even_after_later_revision(self):
        first = self.save_created()
        m5 = candle(13, "1.10800", "1.10650")
        closed_at = m5.candle_open_time_utc + timedelta(minutes=5)
        self.market.upsert_candles([m5], as_of_utc=closed_at, observed_at_utc=closed_at)
        changed = replace(m5, close=Decimal("1.10700"))
        self.market.upsert_candles([changed], as_of_utc=closed_at, observed_at_utc=closed_at)
        self.assertGreater(self.store.get_revision_watermark(BROKER, SYMBOL), 0)

        duplicate = self.store.save_transition(
            self.created,
            expected_record_version=None,
            revision_watermark=0,
            created_at_utc=self.created_at,
        )
        self.assertEqual(duplicate.status, LifecycleStoreStatus.ALREADY_APPLIED)
        self.assertEqual(duplicate.event_id, first.event_id)
        self.assertEqual(len(self.store.get_events(self.lifecycle.lifecycle_id)), 1)

    def test_event_insert_failure_rolls_back_snapshot(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute(
                """
                CREATE TRIGGER fail_lifecycle_event_insert
                BEFORE INSERT ON pa_lifecycle_events
                BEGIN
                    SELECT RAISE(ABORT, 'injected event insert failure');
                END
                """
            )
            db.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            self.save_created()

        self.assertIsNone(self.store.load_by_id(self.lifecycle.lifecycle_id))
        self.assertEqual(self.store.get_events(self.lifecycle.lifecycle_id), [])

    def test_checkpoint_advances_record_version_without_new_event(self):
        self.save_created()
        next_candle = candle(14, "1.10750", "1.10500")
        evidence = EvidenceRef(
            candle=next_candle,
            role=EvidenceRole.CORRECTION,
            confirmed_at_utc=next_candle.candle_open_time_utc + timedelta(minutes=5),
            algorithm_version=self.lifecycle.algorithm_version,
            parameter_version=self.lifecycle.parameter_version,
        )
        depth = (
            self.lifecycle.impulse.end_price - next_candle.low
        ) / self.lifecycle.impulse.pip_size
        progressed = replace(
            self.lifecycle,
            extreme_evidence=evidence,
            depth_pips=depth,
            retracement_ratio=depth / self.lifecycle.impulse.size_pips,
            last_processed_m5_utc=next_candle.candle_open_time_utc,
            age_bars=self.lifecycle.age_bars + 1,
        )
        checkpoint = TransitionResult(
            transition_type=TransitionType.NO_TRANSITION,
            previous_state=LifecycleState.CANDIDATE,
            current_state=LifecycleState.CANDIDATE,
            lifecycle=progressed,
            occurred_at_utc=next_candle.candle_open_time_utc + timedelta(minutes=5),
            reason_codes=("NO_LIFECYCLE_TRANSITION",),
            evidence_refs=(),
        )
        saved = self.store.save_transition(
            checkpoint,
            expected_record_version=1,
            revision_watermark=0,
            created_at_utc=self.created_at + timedelta(minutes=5),
        )
        self.assertEqual(saved.status, LifecycleStoreStatus.CHECKPOINTED)
        self.assertEqual(saved.state_version, 0)
        self.assertEqual(saved.record_version, 2)
        self.assertEqual(len(self.store.get_events(self.lifecycle.lifecycle_id)), 1)

        with self.assertRaises(LifecycleConcurrencyConflict):
            self.store.save_transition(
                checkpoint,
                expected_record_version=1,
                revision_watermark=0,
                created_at_utc=self.created_at + timedelta(minutes=6),
            )

    def test_noop_checkpoint_does_not_write(self):
        self.save_created()
        no_op = TransitionResult(
            transition_type=TransitionType.NO_TRANSITION,
            previous_state=LifecycleState.CANDIDATE,
            current_state=LifecycleState.CANDIDATE,
            lifecycle=self.lifecycle,
            occurred_at_utc=self.lifecycle.last_processed_m5_utc + timedelta(minutes=5),
            reason_codes=("NO_NEW_CLOSED_M5_CANDLES",),
            evidence_refs=(),
        )
        result = self.store.save_transition(
            no_op,
            expected_record_version=1,
            revision_watermark=0,
            created_at_utc=self.created_at + timedelta(minutes=1),
        )
        self.assertIsNone(result)
        self.assertEqual(len(self.store.get_events(self.lifecycle.lifecycle_id)), 1)
        with closing(sqlite3.connect(self.db_path)) as db:
            record = db.execute(
                "SELECT record_version FROM pa_lifecycle_state WHERE lifecycle_id = ?",
                (self.lifecycle.lifecycle_id,),
            ).fetchone()
        self.assertEqual(record[0], 1)

    def test_stale_m5_revision_watermark_is_rejected(self):
        m5 = candle(13, "1.10800", "1.10650")
        closed_at = m5.candle_open_time_utc + timedelta(minutes=5)
        self.market.upsert_candles([m5], as_of_utc=closed_at, observed_at_utc=closed_at)
        changed = replace(m5, close=Decimal("1.10700"))
        self.market.upsert_candles([changed], as_of_utc=closed_at, observed_at_utc=closed_at)
        with self.assertRaises(LifecycleRevisionConflict):
            self.save_created()

    def test_terminal_lifecycle_is_not_loaded_as_active(self):
        self.save_created()
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "UPDATE pa_lifecycle_state SET state = 'EXPIRED' WHERE lifecycle_id = ?",
                (self.lifecycle.lifecycle_id,),
            )
            db.commit()
        self.assertIsNone(self.store.load_active(BROKER, SYMBOL))


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.models.correction_lifecycle import (
    CorrectionLifecycle,
    LifecycleState,
    LifecycleWarning,
    TransitionResult,
    TransitionType,
)
from eurusd_ai_monitor.models.impulse import Impulse
from eurusd_ai_monitor.models.price_action import (
    EvidenceRef,
    EvidenceRole,
    MovementDirection,
    TrendDirection,
)
from eurusd_ai_monitor.storage.market_data_store import Candle


BASE = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
BROKER = "TestBroker"
SYMBOL = "EURUSD"
ALGORITHM = "market_structure_v1"
PARAMETERS = "test-parameters"


def candle(index, high, low):
    return Candle(
        broker_server=BROKER,
        symbol=SYMBOL,
        timeframe="M5",
        candle_open_time_utc=BASE + timedelta(minutes=5 * index),
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(low),
        tick_volume=10,
        spread=2,
        real_volume=0,
    )


def evidence(index, high, low, role, confirmed_after_minutes=15):
    item = candle(index, high, low)
    return EvidenceRef(
        candle=item,
        role=role,
        confirmed_at_utc=item.candle_open_time_utc + timedelta(minutes=confirmed_after_minutes),
        algorithm_version=ALGORITHM,
        parameter_version=PARAMETERS,
    )


def make_impulse():
    start = evidence(0, "1.1010", "1.1000", EvidenceRole.TREND_PIVOT)
    end = evidence(4, "1.1100", "1.1080", EvidenceRole.TREND_PIVOT)
    return Impulse(
        direction=MovementDirection.UP,
        start_pivot=start,
        end_pivot=end,
        start_price=Decimal("1.1000"),
        end_price=Decimal("1.1100"),
        pip_size=Decimal("0.0001"),
        size_pips=Decimal("100"),
        started_at_utc=start.candle.candle_open_time_utc,
        ended_at_utc=end.candle.candle_open_time_utc,
        confirmed_at_utc=end.confirmed_at_utc,
        algorithm_version=ALGORITHM,
        parameter_version=PARAMETERS,
    )


def make_lifecycle(state=LifecycleState.CONFIRMED):
    impulse = make_impulse()
    candidate = evidence(5, "1.1090", "1.1070", EvidenceRole.CORRECTION, 5)
    extreme = evidence(12, "1.1080", "1.1070", EvidenceRole.CORRECTION, 5)
    pivots = tuple(
        evidence(index, high, low, EvidenceRole.TREND_PIVOT, 15)
        for index, high, low in (
            (6, "1.1090", "1.1080"),
            (8, "1.1085", "1.1075"),
            (10, "1.1080", "1.1070"),
        )
    )
    confirmed = pivots[-1].confirmed_at_utc if state in (
        LifecycleState.CONFIRMED,
        LifecycleState.DEEPENING,
        LifecycleState.RESOLVED,
    ) else None
    return CorrectionLifecycle(
        lifecycle_id="test-lifecycle-1",
        broker_server=BROKER,
        symbol=SYMBOL,
        state=state,
        trend_direction=TrendDirection.UP,
        impulse=impulse,
        candidate_start_evidence=candidate,
        extreme_evidence=extreme,
        depth_pips=Decimal("30"),
        retracement_ratio=Decimal("0.3"),
        correction_pivots=pivots if confirmed is not None else (),
        confirmed_at_utc=confirmed,
        last_processed_m5_utc=BASE + timedelta(minutes=60),
        age_bars=8,
        warnings=(),
        algorithm_version=ALGORITHM,
        parameter_version=PARAMETERS,
        state_version=2,
    )


class CorrectionLifecycleModelTests(unittest.TestCase):
    def test_candidate_and_confirmed_lifecycle_are_valid(self):
        candidate = make_lifecycle(LifecycleState.CANDIDATE)
        confirmed = make_lifecycle(LifecycleState.CONFIRMED)
        self.assertIsNone(candidate.confirmed_at_utc)
        self.assertEqual(len(confirmed.correction_pivots), 3)
        self.assertEqual(confirmed.candidate_start_candle_id, confirmed.candidate_start_evidence.candle_id)
        self.assertEqual(confirmed.correction_extreme_price, Decimal("1.1070"))

    def test_rejects_inconsistent_depth(self):
        lifecycle = make_lifecycle()
        with self.assertRaisesRegex(ValueError, "depth_pips"):
            CorrectionLifecycle(
                **{
                    **lifecycle.__dict__,
                    "depth_pips": Decimal("29"),
                }
            )

    def test_rejects_confirmed_state_without_three_pivots(self):
        lifecycle = make_lifecycle()
        with self.assertRaisesRegex(ValueError, "three pivots"):
            CorrectionLifecycle(
                **{
                    **lifecycle.__dict__,
                    "correction_pivots": lifecycle.correction_pivots[:2],
                }
            )

    def test_rejects_unprocessed_future_extreme(self):
        lifecycle = make_lifecycle()
        future = evidence(13, "1.1080", "1.1070", EvidenceRole.CORRECTION, 5)
        with self.assertRaisesRegex(ValueError, "cannot follow last processed"):
            CorrectionLifecycle(
                **{
                    **lifecycle.__dict__,
                    "extreme_evidence": future,
                }
            )

    def test_deep_correction_warning_is_data_not_automatic_invalidation(self):
        lifecycle = make_lifecycle()
        warned = CorrectionLifecycle(
            **{
                **lifecycle.__dict__,
                "warnings": (LifecycleWarning.DEEP_CORRECTION,),
            }
        )
        self.assertEqual(warned.state, LifecycleState.CONFIRMED)
        self.assertIn(LifecycleWarning.DEEP_CORRECTION, warned.warnings)

    def test_lifecycle_serialization_round_trip(self):
        lifecycle = make_lifecycle()
        restored = CorrectionLifecycle.from_dict(lifecycle.to_dict())
        self.assertEqual(restored, lifecycle)
        self.assertEqual(restored.impulse.impulse_id, lifecycle.impulse.impulse_id)


class TransitionResultModelTests(unittest.TestCase):
    def test_created_transition_requires_candidate_state(self):
        candidate = make_lifecycle(LifecycleState.CANDIDATE)
        result = TransitionResult(
            transition_type=TransitionType.CREATED,
            previous_state=None,
            current_state=LifecycleState.CANDIDATE,
            lifecycle=candidate,
            occurred_at_utc=candidate.impulse.confirmed_at_utc,
            reason_codes=("COUNTERTREND_THRESHOLD_REACHED",),
            evidence_refs=(candidate.candidate_start_evidence,),
        )
        self.assertEqual(result.current_state, LifecycleState.CANDIDATE)

    def test_no_transition_preserves_state(self):
        lifecycle = make_lifecycle()
        result = TransitionResult(
            transition_type=TransitionType.NO_TRANSITION,
            previous_state=LifecycleState.CONFIRMED,
            current_state=LifecycleState.CONFIRMED,
            lifecycle=lifecycle,
            occurred_at_utc=lifecycle.last_processed_m5_utc + timedelta(minutes=5),
            reason_codes=("NO_NEW_CONFIRMED_STRUCTURE",),
            evidence_refs=(),
        )
        self.assertEqual(result.lifecycle, lifecycle)

    def test_rejects_transition_type_state_mismatch(self):
        lifecycle = make_lifecycle(LifecycleState.CONFIRMED)
        with self.assertRaisesRegex(ValueError, "does not match"):
            TransitionResult(
                transition_type=TransitionType.RESOLVED,
                previous_state=LifecycleState.CANDIDATE,
                current_state=LifecycleState.CONFIRMED,
                lifecycle=lifecycle,
                occurred_at_utc=lifecycle.confirmed_at_utc,
                reason_codes=("TEST",),
                evidence_refs=(),
            )

    def test_transition_result_serialization_round_trip(self):
        lifecycle = make_lifecycle()
        result = TransitionResult(
            transition_type=TransitionType.CONFIRMED,
            previous_state=LifecycleState.CANDIDATE,
            current_state=LifecycleState.CONFIRMED,
            lifecycle=lifecycle,
            occurred_at_utc=lifecycle.confirmed_at_utc,
            reason_codes=("CORRECTION_STRUCTURE_CONFIRMED",),
            evidence_refs=lifecycle.correction_pivots,
        )
        self.assertEqual(TransitionResult.from_dict(result.to_dict()), result)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.models.price_action import (
    Correction,
    EntryEligibility,
    EvidenceRef,
    EvidenceRole,
    MarketContext,
    MovementDirection,
    OutcomeStatus,
    PatternStatus,
    Pullback,
    Rejection,
    TradeOutcome,
    TradeSetup,
    Trend,
    TrendDirection,
)
from eurusd_ai_monitor.storage.market_data_store import Candle


BASE = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
ALGORITHM_VERSION = "price_action_contract_v1"
PARAMETER_VERSION = "baseline-config-digest"


def make_candle(
    minute: int,
    *,
    timeframe: str = "M1",
    open_price: str = "1.10000",
    high: str = "1.10200",
    low: str = "1.09900",
    close: str = "1.10100",
) -> Candle:
    return Candle(
        broker_server="Demo-Server",
        symbol="EURUSD",
        timeframe=timeframe,
        candle_open_time_utc=BASE + timedelta(minutes=minute),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        tick_volume=10,
        spread=8,
        real_volume=0,
    )


def evidence(
    candle: Candle,
    role: EvidenceRole,
    *,
    confirmed_at: datetime | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        candle=candle,
        role=role,
        confirmed_at_utc=confirmed_at
        or candle.candle_open_time_utc
        + timedelta(minutes=1 if candle.timeframe == "M1" else 5),
        algorithm_version=ALGORITHM_VERSION,
        parameter_version=PARAMETER_VERSION,
    )


def make_trend() -> Trend:
    high_one = evidence(
        make_candle(
            0,
            timeframe="M5",
            high="1.10100",
            low="1.09800",
        ),
        EvidenceRole.TREND_PIVOT,
        confirmed_at=BASE + timedelta(minutes=25),
    )
    high_two = evidence(
        make_candle(
            10,
            timeframe="M5",
            high="1.10200",
            low="1.09900",
        ),
        EvidenceRole.TREND_PIVOT,
        confirmed_at=BASE + timedelta(minutes=25),
    )
    low_one = evidence(
        make_candle(
            5,
            timeframe="M5",
            open_price="1.09920",
            high="1.10000",
            low="1.09700",
            close="1.09950",
        ),
        EvidenceRole.TREND_PIVOT,
        confirmed_at=BASE + timedelta(minutes=25),
    )
    low_two = evidence(
        make_candle(
            15,
            timeframe="M5",
            high="1.10100",
            low="1.09800",
        ),
        EvidenceRole.TREND_PIVOT,
        confirmed_at=BASE + timedelta(minutes=25),
    )
    return Trend(
        direction=TrendDirection.UP,
        confirmed_at_utc=BASE + timedelta(minutes=25),
        swing_highs=(high_one, high_two),
        swing_lows=(low_one, low_two),
        protected_swing=low_two,
    )


def make_rejection() -> Rejection:
    candle = make_candle(
        30,
        open_price="1.10050",
        high="1.10120",
        low="1.09900",
        close="1.10100",
    )
    return Rejection(
        trend_direction=TrendDirection.UP,
        rejection_direction=TrendDirection.UP,
        candle=evidence(candle, EvidenceRole.REJECTION),
        level=Decimal("1.10000"),
    )


def make_correction() -> Correction:
    return Correction(
        trend_direction=TrendDirection.UP,
        movement_direction=MovementDirection.DOWN,
        started_at_utc=BASE + timedelta(minutes=25),
        ended_at_utc=BASE + timedelta(minutes=31),
        depth_pips=Decimal("5"),
        previous_impulse_size_pips=Decimal("20"),
        evidence=(),
    )


def make_pullback(entry_evidence: EvidenceRef | None = None) -> Pullback:
    return Pullback(
        direction=TrendDirection.UP,
        breakout=evidence(
            make_candle(32),
            EvidenceRole.PULLBACK,
        ),
        retest=evidence(
            make_candle(33),
            EvidenceRole.PULLBACK,
        ),
        trigger_level=Decimal("1.10120"),
        confirmed_at_utc=BASE + timedelta(minutes=34),
        next_bar_open=entry_evidence,
    )


def make_setup(
    *,
    pattern_status: PatternStatus = PatternStatus.CONFIRMED,
    eligibility: EntryEligibility = EntryEligibility.BLOCKED,
    entry_evidence: EvidenceRef | None = None,
    entry_price: Decimal | None = None,
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
    entry_gap_policy: str | None = None,
) -> TradeSetup:
    pullback = make_pullback(entry_evidence)
    return TradeSetup(
        setup_id="setup-1",
        strategy_version="experimental_baseline_v1",
        algorithm_version=ALGORITHM_VERSION,
        parameter_version=PARAMETER_VERSION,
        session_id="london:2026-11-17",
        pattern_status=pattern_status,
        entry_eligibility=eligibility,
        trend=make_trend(),
        correction=make_correction(),
        rejection=make_rejection(),
        pullback=pullback,
        detected_at_utc=BASE + timedelta(minutes=31),
        confirmed_at_utc=(
            pullback.confirmed_at_utc
            if pattern_status is PatternStatus.CONFIRMED
            else None
        ),
        entry_bar_evidence=entry_evidence,
        entry_at_utc=(
            entry_evidence.candle.candle_open_time_utc
            if entry_evidence is not None
            else None
        ),
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        entry_gap_policy=entry_gap_policy,
        confirmed_reasons=("M5 structure bullish",),
        rejected_reasons=(),
        entry_block_reasons=(
            ("entry gap policy is not configured",)
            if eligibility is EntryEligibility.BLOCKED
            else ()
        ),
    )


class PriceActionModelTests(unittest.TestCase):
    def test_market_context_keeps_latest_closed_candle_and_rejects_open_candle(self):
        m1 = (make_candle(0), make_candle(1))
        m5 = (make_candle(0, timeframe="M5"),)
        context = MarketContext(
            symbol="EURUSD",
            source_id="Demo-Server",
            as_of_utc=BASE + timedelta(minutes=5),
            m1_candles=m1,
            m5_candles=m5,
        )
        self.assertEqual(len(context.m1_candles), 2)
        self.assertEqual(context.m1_candles[-1], m1[-1])

        with self.assertRaisesRegex(ValueError, "not closed"):
            MarketContext(
                symbol="EURUSD",
                source_id="Demo-Server",
                as_of_utc=BASE + timedelta(seconds=30),
                m1_candles=(make_candle(0),),
                m5_candles=(),
            )

    def test_models_reject_float_decimal_values_and_naive_datetimes(self):
        with self.assertRaisesRegex(TypeError, "Decimal"):
            Correction(
                trend_direction=TrendDirection.UP,
                movement_direction=MovementDirection.DOWN,
                started_at_utc=BASE,
                ended_at_utc=BASE + timedelta(minutes=1),
                depth_pips=5.0,
                previous_impulse_size_pips=Decimal("20"),
                evidence=(),
            )

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            EvidenceRef(
                candle=make_candle(0),
                role=EvidenceRole.REJECTION,
                confirmed_at_utc=datetime(2026, 11, 17, 12, 1),
                algorithm_version=ALGORITHM_VERSION,
                parameter_version=PARAMETER_VERSION,
            )

    def test_correction_keeps_trend_and_counter_movement_independent(self):
        correction = make_correction()
        self.assertEqual(correction.trend_direction, TrendDirection.UP)
        self.assertEqual(correction.movement_direction, MovementDirection.DOWN)
        self.assertEqual(correction.correction_ratio, Decimal("0.25"))

        with self.assertRaisesRegex(ValueError, "must oppose"):
            Correction(
                trend_direction=TrendDirection.UP,
                movement_direction=MovementDirection.UP,
                started_at_utc=BASE,
                ended_at_utc=BASE + timedelta(minutes=1),
                depth_pips=Decimal("5"),
                previous_impulse_size_pips=Decimal("20"),
                evidence=(),
            )

    def test_rejection_with_zero_body_is_invalid(self):
        flat = make_candle(
            30,
            open_price="1.10000",
            high="1.10100",
            low="1.09900",
            close="1.10000",
        )
        with self.assertRaisesRegex(ValueError, "zero-body"):
            Rejection(
                trend_direction=TrendDirection.UP,
                rejection_direction=TrendDirection.UP,
                candle=evidence(flat, EvidenceRole.REJECTION),
                level=Decimal("1.10000"),
            )

    def test_pattern_confirmation_is_independent_from_entry_eligibility(self):
        setup = make_setup()
        self.assertEqual(setup.pattern_status, PatternStatus.CONFIRMED)
        self.assertEqual(setup.entry_eligibility, EntryEligibility.BLOCKED)
        self.assertIsNone(setup.entry_price)
        self.assertEqual(setup.rejection.wick_body_ratio, Decimal("3"))
        self.assertGreaterEqual(
            setup.rejection.close_location,
            Decimal("0.70"),
        )

    def test_blocked_setup_cannot_contain_an_entry(self):
        with self.assertRaisesRegex(ValueError, "cannot contain entry"):
            make_setup(
                entry_price=Decimal("1.10150"),
                stop_loss=Decimal("1.10100"),
                take_profit=Decimal("1.10650"),
                entry_gap_policy="test-only-gap-policy",
            )

    def test_eligible_entry_must_use_the_next_m1_open(self):
        entry_candle = make_candle(
            34,
            open_price="1.10150",
            high="1.10200",
            low="1.10100",
            close="1.10180",
        )
        entry_ref = evidence(entry_candle, EvidenceRole.ENTRY)
        setup = make_setup(
            eligibility=EntryEligibility.ELIGIBLE,
            entry_evidence=entry_ref,
            entry_price=Decimal("1.10150"),
            stop_loss=Decimal("1.10100"),
            take_profit=Decimal("1.10650"),
            entry_gap_policy="test-only-gap-policy",
        )
        self.assertEqual(setup.entry_price, entry_candle.open)

        with self.assertRaisesRegex(ValueError, "next candle open"):
            replace(setup, entry_at_utc=BASE + timedelta(minutes=35))

    def test_setup_serialization_round_trip_preserves_decimal_precision(self):
        setup = make_setup()
        payload = json.loads(json.dumps(setup.to_dict()))
        restored = TradeSetup.from_dict(payload)

        self.assertEqual(restored, setup)
        self.assertEqual(
            restored.rejection.candle.candle.open.as_tuple(),
            setup.rejection.candle.candle.open.as_tuple(),
        )
        self.assertEqual(restored.trend.direction, TrendDirection.UP)
        self.assertEqual(restored.entry_eligibility, EntryEligibility.BLOCKED)

    def test_trade_outcome_is_independent_from_pattern_status(self):
        outcome = TradeOutcome(
            setup_id="setup-1",
            status=OutcomeStatus.OPEN,
            opened_at_utc=BASE + timedelta(minutes=34),
            entry_price=Decimal("1.10150"),
        )
        self.assertEqual(outcome.status, OutcomeStatus.OPEN)
        with self.assertRaisesRegex(ValueError, "requires closed_at_utc"):
            TradeOutcome(
                setup_id="setup-1",
                status=OutcomeStatus.TP_HIT,
                opened_at_utc=BASE + timedelta(minutes=34),
                entry_price=Decimal("1.10150"),
            )

    def test_eligible_entry_requires_a_configured_gap_policy(self):
        entry_candle = make_candle(
            34,
            open_price="1.10150",
            high="1.10200",
            low="1.10100",
            close="1.10180",
        )
        entry_ref = evidence(entry_candle, EvidenceRole.ENTRY)
        with self.assertRaisesRegex(ValueError, "explicit gap policy"):
            make_setup(
                eligibility=EntryEligibility.ELIGIBLE,
                entry_evidence=entry_ref,
                entry_price=Decimal("1.10150"),
                stop_loss=Decimal("1.10100"),
                take_profit=Decimal("1.10650"),
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.engines.technical_engine import PivotKind, TechnicalStructure
from eurusd_ai_monitor.models.correction_lifecycle import (
    CorrectionLifecycle,
    LifecycleState,
    LifecycleWarning,
    TransitionResult,
    TransitionType,
)
from eurusd_ai_monitor.models.price_action import EvidenceRef, EvidenceRole, TrendDirection
from eurusd_ai_monitor.storage.market_data_store import Candle, TIMEFRAME_SECONDS


_M5 = timedelta(seconds=TIMEFRAME_SECONDS["M5"])
_TERMINAL_STATES = {
    LifecycleState.RESOLVED,
    LifecycleState.INVALIDATED,
    LifecycleState.EXPIRED,
}


class LifecycleStateMachine:
    """Pure, deterministic correction-lifecycle transition evaluator.

    The caller supplies the already-computed TechnicalStructure and the
    chronologically ordered closed M5 candles. This class performs no I/O,
    clock reads, pivot detection, trend classification, or trade decisions.
    """

    def advance(
        self,
        lifecycle: CorrectionLifecycle,
        structure: TechnicalStructure,
        m5_candles: tuple[Candle, ...],
        expiry_bars: int = 30,
        max_correction_ratio: Decimal = Decimal("0.80"),
    ) -> TransitionResult:
        if not isinstance(lifecycle, CorrectionLifecycle):
            raise TypeError("lifecycle must be a CorrectionLifecycle")
        if not isinstance(structure, TechnicalStructure):
            raise TypeError("structure must be a TechnicalStructure")
        if not isinstance(m5_candles, tuple) or any(
            not isinstance(candle, Candle) for candle in m5_candles
        ):
            raise TypeError("m5_candles must be a tuple of Candle values")
        if type(expiry_bars) is not int or expiry_bars <= 0:
            raise ValueError("expiry_bars must be a positive integer")
        if (
            not isinstance(max_correction_ratio, Decimal)
            or not max_correction_ratio.is_finite()
            or max_correction_ratio <= 0
            or max_correction_ratio > 1
        ):
            raise ValueError("max_correction_ratio must be a Decimal in (0, 1]")

        ordered = tuple(sorted(m5_candles, key=lambda c: c.candle_open_time_utc))
        if ordered != m5_candles:
            raise ValueError("M5 candles must be chronologically ordered")
        opens = tuple(c.candle_open_time_utc for c in ordered)
        if len(opens) != len(set(opens)):
            raise ValueError("M5 candle timestamps must be unique")
        for candle in ordered:
            if candle.timeframe != "M5":
                raise ValueError("lifecycle advancement requires M5 candles")
            if (
                candle.broker_server != lifecycle.broker_server
                or candle.symbol != lifecycle.symbol
            ):
                raise ValueError("all candles must match lifecycle identity")
            if candle.candle_open_time_utc + _M5 > structure.evaluated_at_utc:
                raise ValueError("lifecycle advancement cannot use an open candle")
        if structure.evaluated_at_utc < (
            lifecycle.last_processed_m5_utc + _M5
        ):
            raise ValueError("structure evaluation cannot precede the last processed close")

        if lifecycle.state in _TERMINAL_STATES:
            return self._result(
                TransitionType.NO_TRANSITION,
                lifecycle.state,
                lifecycle,
                lifecycle.last_processed_m5_utc + _M5,
                ("TERMINAL_STATE_IMMUTABLE",),
                (),
            )

        new_candles = tuple(
            candle
            for candle in ordered
            if candle.candle_open_time_utc > lifecycle.last_processed_m5_utc
        )
        if not new_candles:
            return self._result(
                TransitionType.NO_TRANSITION,
                lifecycle.state,
                lifecycle,
                lifecycle.last_processed_m5_utc + _M5,
                ("NO_NEW_CLOSED_M5_CANDLES",),
                (),
            )

        latest = new_candles[-1]
        age_bars = lifecycle.age_bars + len(new_candles)
        latest_close = latest.candle_open_time_utc + _M5
        base = replace(
            lifecycle,
            last_processed_m5_utc=latest.candle_open_time_utc,
            age_bars=age_bars,
        )

        # Priority 1: a confirmed break of the M5 protected swing.
        protected_break = structure.protected_swing_break
        if (
            protected_break is not None
            and protected_break.confirmed_at_utc > lifecycle.last_processed_m5_utc + _M5
            and protected_break.confirmed_at_utc <= structure.evaluated_at_utc
            and protected_break.broken_direction is lifecycle.trend_direction
        ):
            ref = self._candle_evidence(
                protected_break.break_candle, lifecycle, EvidenceRole.CORRECTION
            )
            updated = replace(base, state=LifecycleState.INVALIDATED, state_version=lifecycle.state_version + 1)
            return self._result(
                TransitionType.INVALIDATED, lifecycle.state, updated,
                protected_break.confirmed_at_utc, ("PROTECTED_SWING_BROKEN",), (ref,)
            )

        # Priority 2: before correction confirmation, a close through the
        # impulse terminal extreme means the trend resumed without the pattern.
        if lifecycle.state is LifecycleState.CANDIDATE:
            for candle in new_candles:
                resumed = (
                    candle.close > lifecycle.impulse.end_price
                    if lifecycle.trend_direction is TrendDirection.UP
                    else candle.close < lifecycle.impulse.end_price
                )
                if resumed:
                    ref = self._candle_evidence(candle, lifecycle, EvidenceRole.CORRECTION)
                    updated = replace(base, state=LifecycleState.INVALIDATED, state_version=lifecycle.state_version + 1)
                    return self._result(
                        TransitionType.INVALIDATED, lifecycle.state, updated,
                        candle.candle_open_time_utc + _M5,
                        ("IMPULSE_TERMINAL_EXTREME_BROKEN_BEFORE_CONFIRMATION",), (ref,)
                    )

        # Collect newly confirmed correction pivots without reprocessing old ones.
        known_ids = {ref.candle_id for ref in lifecycle.correction_pivots}
        candidate_open = lifecycle.candidate_start_evidence.candle.candle_open_time_utc
        pivot_counts: dict[str, int] = {}
        for pivot in structure.pivots:
            if pivot.evidence.candle.candle_open_time_utc >= candidate_open:
                pivot_counts[pivot.evidence.candle_id] = (
                    pivot_counts.get(pivot.evidence.candle_id, 0) + 1
                )
        fresh_pivots = tuple(
            pivot
            for pivot in structure.pivots
            if lifecycle.state is LifecycleState.CANDIDATE
            and pivot.evidence.candle.candle_open_time_utc >= candidate_open
            and pivot.evidence.confirmed_at_utc <= structure.evaluated_at_utc
            and pivot.evidence.candle_id not in known_ids
            and pivot_counts[pivot.evidence.candle_id] == 1
        )
        fresh_pivots = tuple(
            sorted(
                fresh_pivots,
                key=lambda p: (
                    p.evidence.candle.candle_open_time_utc,
                    p.evidence.confirmed_at_utc,
                    p.kind.value,
                ),
            )
        )
        correction_pivots = lifecycle.correction_pivots + tuple(
            pivot.evidence for pivot in fresh_pivots
        )
        # De-duplicate by candle identity and keep deterministic formation order.
        unique: dict[str, EvidenceRef] = {}
        for ref in correction_pivots:
            unique.setdefault(ref.candle_id, ref)
        correction_pivots = tuple(
            sorted(unique.values(), key=lambda ref: ref.candle.candle_open_time_utc)
        )

        # Priority 3: a confirmed correction resolves only after the M5 close
        # crosses the middle pivot (LH for UP, HL for DOWN).
        if lifecycle.state in (LifecycleState.CONFIRMED, LifecycleState.DEEPENING):
            if len(correction_pivots) >= 3:
                middle = correction_pivots[-2].candle
                for candle in new_candles:
                    resolved = (
                        candle.close > middle.high
                        if lifecycle.trend_direction is TrendDirection.UP
                        else candle.close < middle.low
                    )
                    if resolved:
                        updated = replace(
                            base,
                            state=LifecycleState.RESOLVED,
                            correction_pivots=correction_pivots,
                            state_version=lifecycle.state_version + 1,
                        )
                        ref = self._candle_evidence(candle, lifecycle, EvidenceRole.CORRECTION)
                        return self._result(
                            TransitionType.RESOLVED, lifecycle.state, updated,
                            candle.candle_open_time_utc + _M5,
                            ("CORRECTION_RESUMPTION_LEVEL_CLOSED_THROUGH",), (ref,)
                        )

        # Priority 4: complete the correction pivot sequence.
        if lifecycle.state is LifecycleState.CANDIDATE and len(correction_pivots) >= 3:
            last_three = correction_pivots[-3:]
            pivot_kinds = {
                pivot.evidence.candle_id: pivot.kind
                for pivot in structure.pivots
            }
            kinds = tuple(
                pivot_kinds.get(ref.candle_id)
                for ref in last_three
            )
            if lifecycle.trend_direction is TrendDirection.UP:
                valid_sequence = (
                    None not in kinds
                    and kinds == (PivotKind.LOW, PivotKind.HIGH, PivotKind.LOW)
                    and last_three[1].candle.high < lifecycle.impulse.end_price
                    and last_three[2].candle.low < last_three[0].candle.low
                )
            else:
                valid_sequence = (
                    None not in kinds
                    and kinds == (PivotKind.HIGH, PivotKind.LOW, PivotKind.HIGH)
                    and last_three[1].candle.low > lifecycle.impulse.end_price
                    and last_three[2].candle.high > last_three[0].candle.high
                )
            if valid_sequence:
                confirmed_at = last_three[-1].confirmed_at_utc
                updated = replace(
                    base,
                    state=LifecycleState.CONFIRMED,
                    correction_pivots=last_three,
                    confirmed_at_utc=confirmed_at,
                    state_version=lifecycle.state_version + 1,
                )
                return self._result(
                    TransitionType.CONFIRMED, lifecycle.state, updated,
                    confirmed_at, ("CORRECTION_PIVOT_SEQUENCE_CONFIRMED",), last_three
                )

        # Update the deepest observed correction extreme. A new extreme after
        # confirmation moves the lifecycle to DEEPENING.
        extreme_candle = lifecycle.extreme_evidence.candle
        for candle in new_candles:
            if lifecycle.trend_direction is TrendDirection.UP:
                if candle.low < extreme_candle.low:
                    extreme_candle = candle
            elif candle.high > extreme_candle.high:
                extreme_candle = candle
        extreme_changed = extreme_candle.candle_open_time_utc != lifecycle.extreme_evidence.candle.candle_open_time_utc
        if extreme_changed:
            extreme_ref = self._candle_evidence(extreme_candle, lifecycle, EvidenceRole.CORRECTION)
            depth = (
                lifecycle.impulse.end_price - extreme_candle.low
                if lifecycle.trend_direction is TrendDirection.UP
                else extreme_candle.high - lifecycle.impulse.end_price
            ) / lifecycle.impulse.pip_size
            ratio = depth / lifecycle.impulse.size_pips
            warnings = lifecycle.warnings
            if ratio > max_correction_ratio and LifecycleWarning.DEEP_CORRECTION not in warnings:
                warnings = warnings + (LifecycleWarning.DEEP_CORRECTION,)
            next_state = (
                LifecycleState.DEEPENING
                if lifecycle.state in (LifecycleState.CONFIRMED, LifecycleState.DEEPENING)
                else LifecycleState.CANDIDATE
            )
            updated = replace(
                base,
                state=next_state,
                extreme_evidence=extreme_ref,
                depth_pips=depth,
                retracement_ratio=ratio,
                correction_pivots=correction_pivots,
                warnings=warnings,
                state_version=(
                    lifecycle.state_version + 1
                    if next_state is LifecycleState.DEEPENING
                    and lifecycle.state is not LifecycleState.DEEPENING
                    else lifecycle.state_version
                ),
            )
            if next_state is LifecycleState.DEEPENING and lifecycle.state is not LifecycleState.DEEPENING:
                return self._result(
                    TransitionType.DEEPENED, lifecycle.state, updated,
                    latest_close, ("NEW_CORRECTION_EXTREME_AFTER_CONFIRMATION",), (extreme_ref,)
                )
            base = updated

        # Retain pivots discovered while the sequence is still incomplete.
        if correction_pivots != lifecycle.correction_pivots:
            base = replace(base, correction_pivots=correction_pivots)

        # Priority 6: expiry counts actual supplied closed bars, not wall time.
        if age_bars >= expiry_bars:
            updated = replace(
                base,
                state=LifecycleState.EXPIRED,
                state_version=lifecycle.state_version + 1,
            )
            return self._result(
                TransitionType.EXPIRED, lifecycle.state, updated,
                latest_close, ("LIFECYCLE_MAX_AGE_REACHED",), ()
            )

        return self._result(
            TransitionType.NO_TRANSITION, lifecycle.state, base,
            latest_close, ("NO_LIFECYCLE_TRANSITION",), ()
        )

    @staticmethod
    def _candle_evidence(
        candle: Candle,
        lifecycle: CorrectionLifecycle,
        role: EvidenceRole,
    ) -> EvidenceRef:
        return EvidenceRef(
            candle=candle,
            role=role,
            confirmed_at_utc=candle.candle_open_time_utc + _M5,
            algorithm_version=lifecycle.algorithm_version,
            parameter_version=lifecycle.parameter_version,
        )

    @staticmethod
    def _result(
        transition_type: TransitionType,
        previous_state: LifecycleState,
        lifecycle: CorrectionLifecycle,
        occurred_at: datetime,
        reason_codes: tuple[str, ...],
        evidence_refs: tuple[EvidenceRef, ...],
    ) -> TransitionResult:
        return TransitionResult(
            transition_type=transition_type,
            previous_state=previous_state,
            current_state=lifecycle.state,
            lifecycle=lifecycle,
            occurred_at_utc=occurred_at.astimezone(timezone.utc),
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
        )

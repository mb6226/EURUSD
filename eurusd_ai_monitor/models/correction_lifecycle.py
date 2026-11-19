from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from eurusd_ai_monitor.models.impulse import (
    Impulse,
    _datetime_to_string,
    _evidence_from_dict,
    _evidence_to_dict,
    _parse_datetime,
    _parse_decimal,
)
from eurusd_ai_monitor.models.price_action import (
    EvidenceRef,
    EvidenceRole,
    MovementDirection,
    TrendDirection,
)
from eurusd_ai_monitor.storage.market_data_store import TIMEFRAME_SECONDS


_M5_SECONDS = TIMEFRAME_SECONDS["M5"]


class LifecycleState(str, Enum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    DEEPENING = "DEEPENING"
    RESOLVED = "RESOLVED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class LifecycleWarning(str, Enum):
    DEEP_CORRECTION = "DEEP_CORRECTION"


class TransitionType(str, Enum):
    NO_TRANSITION = "NO_TRANSITION"
    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    DEEPENED = "DEEPENED"
    RESOLVED = "RESOLVED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{field_name} must be finite and greater than zero")
    return value


def _nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class CorrectionLifecycle:
    """Immutable snapshot of one correction's lifecycle.

    A lifecycle starts at CANDIDATE. NO_CORRECTION is represented by the
    absence of an active lifecycle, not by a persisted lifecycle instance.
    """

    lifecycle_id: str
    broker_server: str
    symbol: str
    state: LifecycleState
    trend_direction: TrendDirection
    impulse: Impulse
    candidate_start_evidence: EvidenceRef
    extreme_evidence: EvidenceRef
    depth_pips: Decimal
    retracement_ratio: Decimal
    correction_pivots: tuple[EvidenceRef, ...]
    confirmed_at_utc: datetime | None
    last_processed_m5_utc: datetime
    age_bars: int
    warnings: tuple[LifecycleWarning, ...]
    algorithm_version: str
    parameter_version: str
    state_version: int = 0

    def __post_init__(self) -> None:
        for name in ("lifecycle_id", "broker_server", "symbol", "algorithm_version", "parameter_version"):
            _nonempty(getattr(self, name), name)
        if not isinstance(self.state, LifecycleState):
            raise TypeError("state must be a LifecycleState")
        if not isinstance(self.trend_direction, TrendDirection):
            raise TypeError("trend_direction must be a TrendDirection")
        if self.trend_direction not in (TrendDirection.UP, TrendDirection.DOWN):
            raise ValueError("lifecycle requires a directional trend")
        if not isinstance(self.impulse, Impulse):
            raise TypeError("impulse must be an Impulse")
        if not isinstance(self.candidate_start_evidence, EvidenceRef):
            raise TypeError("candidate_start_evidence must be an EvidenceRef")
        if not isinstance(self.extreme_evidence, EvidenceRef):
            raise TypeError("extreme_evidence must be an EvidenceRef")

        expected_impulse_direction = (
            MovementDirection.UP
            if self.trend_direction is TrendDirection.UP
            else MovementDirection.DOWN
        )
        if self.impulse.direction is not expected_impulse_direction:
            raise ValueError("impulse direction must agree with the trend")
        impulse_candle = self.impulse.start_pivot.candle
        if impulse_candle.broker_server != self.broker_server or impulse_candle.symbol != self.symbol:
            raise ValueError("impulse identity must match lifecycle broker and symbol")

        for name, ref in (
            ("candidate_start_evidence", self.candidate_start_evidence),
            ("extreme_evidence", self.extreme_evidence),
        ):
            candle = ref.candle
            if candle.timeframe != "M5":
                raise ValueError(f"{name} must use M5")
            if candle.broker_server != self.broker_server or candle.symbol != self.symbol:
                raise ValueError(f"{name} identity must match lifecycle")
            if ref.role is not EvidenceRole.CORRECTION:
                raise ValueError(f"{name} must have the CORRECTION evidence role")
            if ref.algorithm_version != self.algorithm_version or ref.parameter_version != self.parameter_version:
                raise ValueError(f"{name} evidence versions must match lifecycle")

        if not isinstance(self.correction_pivots, tuple):
            raise TypeError("correction_pivots must be a tuple")
        if any(not isinstance(ref, EvidenceRef) for ref in self.correction_pivots):
            raise TypeError("correction_pivots must contain EvidenceRef values")
        pivot_times = []
        for ref in self.correction_pivots:
            candle = ref.candle
            if candle.timeframe != "M5":
                raise ValueError("correction pivots must use M5")
            if candle.broker_server != self.broker_server or candle.symbol != self.symbol:
                raise ValueError("correction pivot identity must match lifecycle")
            if ref.role is not EvidenceRole.TREND_PIVOT:
                raise ValueError("correction pivots must retain TREND_PIVOT evidence role")
            if ref.algorithm_version != self.algorithm_version or ref.parameter_version != self.parameter_version:
                raise ValueError("correction pivot evidence versions must match lifecycle")
            if ref.candle.candle_open_time_utc < self.candidate_start_evidence.candle.candle_open_time_utc:
                raise ValueError("correction pivots cannot precede candidate creation")
            pivot_times.append(candle.candle_open_time_utc)
        if pivot_times != sorted(set(pivot_times)):
            raise ValueError("correction_pivots must be chronologically ordered")

        depth = _positive_decimal(self.depth_pips, "depth_pips")
        ratio = _positive_decimal(self.retracement_ratio, "retracement_ratio")
        expected_depth = (
            self.impulse.end_price - self.extreme_evidence.candle.low
            if self.trend_direction is TrendDirection.UP
            else self.extreme_evidence.candle.high - self.impulse.end_price
        ) / self.impulse.pip_size
        if expected_depth <= 0 or depth != expected_depth:
            raise ValueError("depth_pips must match the impulse-to-correction extreme distance")
        expected_ratio = depth / self.impulse.size_pips
        if ratio != expected_ratio:
            raise ValueError("retracement_ratio must equal depth_pips / impulse size_pips")

        candidate_at = _utc(
            self.candidate_start_evidence.confirmed_at_utc,
            "candidate_start_evidence.confirmed_at_utc",
        )
        last_processed = _utc(self.last_processed_m5_utc, "last_processed_m5_utc")
        latest_processed_close = last_processed + timedelta(seconds=_M5_SECONDS)
        if int(last_processed.timestamp()) % _M5_SECONDS:
            raise ValueError("last_processed_m5_utc must align to an M5 candle open")
        candidate_close = (
            self.candidate_start_evidence.candle.candle_open_time_utc
            + timedelta(seconds=_M5_SECONDS)
        )
        if candidate_at != candidate_close:
            raise ValueError("candidate start is confirmed at its M5 candle close")
        extreme_close = (
            self.extreme_evidence.candle.candle_open_time_utc
            + timedelta(seconds=_M5_SECONDS)
        )
        if self.extreme_evidence.confirmed_at_utc != extreme_close:
            raise ValueError("correction extreme is confirmed at its M5 candle close")
        if self.extreme_evidence.candle.candle_open_time_utc < self.candidate_start_evidence.candle.candle_open_time_utc:
            raise ValueError("correction extreme cannot precede candidate creation")
        if self.candidate_start_evidence.candle.candle_open_time_utc <= self.impulse.ended_at_utc:
            raise ValueError("candidate start must follow the impulse terminal pivot")
        if self.impulse.confirmed_at_utc > latest_processed_close:
            raise ValueError("impulse cannot be confirmed after last processed candle")
        if self.candidate_start_evidence.candle.candle_open_time_utc > last_processed:
            raise ValueError("candidate start cannot follow last processed M5 candle")
        if candidate_at > latest_processed_close:
            raise ValueError("candidate start evidence cannot be confirmed after last processed candle")
        if self.extreme_evidence.candle.candle_open_time_utc > last_processed:
            raise ValueError("correction extreme cannot follow last processed M5 candle")
        if self.extreme_evidence.confirmed_at_utc > latest_processed_close:
            raise ValueError("correction extreme cannot be confirmed after last processed candle")
        if any(ref.confirmed_at_utc > latest_processed_close for ref in self.correction_pivots):
            raise ValueError("correction pivot cannot be confirmed after last processed candle")

        if type(self.age_bars) is not int or self.age_bars <= 0:
            raise ValueError("age_bars must be a positive integer")
        if type(self.state_version) is not int or self.state_version < 0:
            raise ValueError("state_version must be a non-negative integer")
        if not isinstance(self.warnings, tuple) or any(
            not isinstance(item, LifecycleWarning) for item in self.warnings
        ):
            raise TypeError("warnings must be a tuple of LifecycleWarning values")
        if len(set(self.warnings)) != len(self.warnings):
            raise ValueError("warnings must not contain duplicates")

        confirmed = (
            _utc(self.confirmed_at_utc, "confirmed_at_utc")
            if self.confirmed_at_utc is not None
            else None
        )
        if self.state in (
            LifecycleState.CONFIRMED,
            LifecycleState.DEEPENING,
            LifecycleState.RESOLVED,
        ):
            if confirmed is None or len(self.correction_pivots) < 3:
                raise ValueError("confirmed lifecycle states require three pivots and confirmed_at_utc")
            if confirmed != self.correction_pivots[-1].confirmed_at_utc:
                raise ValueError("confirmed_at_utc must match the latest correction pivot confirmation")
        elif confirmed is not None:
            if len(self.correction_pivots) < 3:
                raise ValueError("confirmed_at_utc requires at least three correction pivots")
            if confirmed != self.correction_pivots[-1].confirmed_at_utc:
                raise ValueError("confirmed_at_utc must match the latest correction pivot confirmation")
        if confirmed is not None and confirmed > latest_processed_close:
            raise ValueError("lifecycle cannot be confirmed after last processed candle")
        if self.state is LifecycleState.CANDIDATE and confirmed is not None:
            raise ValueError("CANDIDATE cannot have confirmed_at_utc")

        object.__setattr__(self, "last_processed_m5_utc", last_processed)
        object.__setattr__(self, "confirmed_at_utc", confirmed)

        if self.impulse.algorithm_version != self.algorithm_version:
            raise ValueError("lifecycle algorithm_version must match impulse")
        if self.impulse.parameter_version != self.parameter_version:
            raise ValueError("lifecycle parameter_version must match impulse")

    @property
    def candidate_started_at_utc(self) -> datetime:
        return self.candidate_start_evidence.confirmed_at_utc

    @property
    def candidate_start_candle_id(self) -> str:
        return self.candidate_start_evidence.candle_id

    @property
    def correction_extreme_price(self) -> Decimal:
        candle = self.extreme_evidence.candle
        return candle.low if self.trend_direction is TrendDirection.UP else candle.high

    def to_dict(self) -> dict[str, Any]:
        return {
            "lifecycle_id": self.lifecycle_id,
            "broker_server": self.broker_server,
            "symbol": self.symbol,
            "state": self.state.value,
            "trend_direction": self.trend_direction.value,
            "impulse": self.impulse.to_dict(),
            "candidate_start_evidence": _evidence_to_dict(self.candidate_start_evidence),
            "extreme_evidence": _evidence_to_dict(self.extreme_evidence),
            "depth_pips": format(self.depth_pips, "f"),
            "retracement_ratio": format(self.retracement_ratio, "f"),
            "correction_pivots": [_evidence_to_dict(ref) for ref in self.correction_pivots],
            "confirmed_at_utc": (
                _datetime_to_string(self.confirmed_at_utc)
                if self.confirmed_at_utc is not None
                else None
            ),
            "last_processed_m5_utc": _datetime_to_string(self.last_processed_m5_utc),
            "age_bars": self.age_bars,
            "warnings": [warning.value for warning in self.warnings],
            "algorithm_version": self.algorithm_version,
            "parameter_version": self.parameter_version,
            "state_version": self.state_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CorrectionLifecycle:
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        confirmed = payload["confirmed_at_utc"]
        return cls(
            lifecycle_id=payload["lifecycle_id"],
            broker_server=payload["broker_server"],
            symbol=payload["symbol"],
            state=LifecycleState(payload["state"]),
            trend_direction=TrendDirection(payload["trend_direction"]),
            impulse=Impulse.from_dict(payload["impulse"]),
            candidate_start_evidence=_evidence_from_dict(payload["candidate_start_evidence"]),
            extreme_evidence=_evidence_from_dict(payload["extreme_evidence"]),
            depth_pips=_parse_decimal(payload["depth_pips"], "depth_pips"),
            retracement_ratio=_parse_decimal(payload["retracement_ratio"], "retracement_ratio"),
            correction_pivots=tuple(
                _evidence_from_dict(item) for item in payload["correction_pivots"]
            ),
            confirmed_at_utc=(
                _parse_datetime(confirmed, "confirmed_at_utc")
                if confirmed is not None
                else None
            ),
            last_processed_m5_utc=_parse_datetime(
                payload["last_processed_m5_utc"],
                "last_processed_m5_utc",
            ),
            age_bars=payload["age_bars"],
            warnings=tuple(LifecycleWarning(item) for item in payload["warnings"]),
            algorithm_version=payload["algorithm_version"],
            parameter_version=payload["parameter_version"],
            state_version=payload["state_version"],
        )


@dataclass(frozen=True)
class TransitionResult:
    transition_type: TransitionType
    previous_state: LifecycleState | None
    current_state: LifecycleState | None
    lifecycle: CorrectionLifecycle | None
    occurred_at_utc: datetime
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.transition_type, TransitionType):
            raise TypeError("transition_type must be a TransitionType")
        if self.previous_state is not None and not isinstance(self.previous_state, LifecycleState):
            raise TypeError("previous_state must be a LifecycleState or None")
        if self.current_state is not None and not isinstance(self.current_state, LifecycleState):
            raise TypeError("current_state must be a LifecycleState or None")
        if self.lifecycle is not None and not isinstance(self.lifecycle, CorrectionLifecycle):
            raise TypeError("lifecycle must be a CorrectionLifecycle or None")
        occurred = _utc(self.occurred_at_utc, "occurred_at_utc")
        object.__setattr__(self, "occurred_at_utc", occurred)

        if not isinstance(self.reason_codes, tuple) or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty tuple")
        if any(not isinstance(code, str) or not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must contain non-empty strings")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, EvidenceRef) for ref in self.evidence_refs
        ):
            raise TypeError("evidence_refs must be a tuple of EvidenceRef values")

        if self.lifecycle is None:
            if self.current_state is not None:
                raise ValueError("current_state requires a lifecycle")
        elif self.current_state is not self.lifecycle.state:
            raise ValueError("current_state must match lifecycle.state")

        if self.transition_type is TransitionType.NO_TRANSITION:
            if self.previous_state is not self.current_state:
                raise ValueError("NO_TRANSITION must preserve the state")
        else:
            if self.current_state is None or self.current_state is self.previous_state:
                raise ValueError("a state transition must change to a non-empty state")
            expected_state = {
                TransitionType.CREATED: LifecycleState.CANDIDATE,
                TransitionType.CONFIRMED: LifecycleState.CONFIRMED,
                TransitionType.DEEPENED: LifecycleState.DEEPENING,
                TransitionType.RESOLVED: LifecycleState.RESOLVED,
                TransitionType.INVALIDATED: LifecycleState.INVALIDATED,
                TransitionType.EXPIRED: LifecycleState.EXPIRED,
            }[self.transition_type]
            if self.current_state is not expected_state:
                raise ValueError("transition_type does not match current_state")
            allowed_previous = {
                TransitionType.CREATED: (None,),
                TransitionType.CONFIRMED: (LifecycleState.CANDIDATE,),
                TransitionType.DEEPENED: (LifecycleState.CONFIRMED, LifecycleState.DEEPENING),
                TransitionType.RESOLVED: (LifecycleState.CONFIRMED, LifecycleState.DEEPENING),
                TransitionType.INVALIDATED: (
                    LifecycleState.CANDIDATE,
                    LifecycleState.CONFIRMED,
                    LifecycleState.DEEPENING,
                ),
                TransitionType.EXPIRED: (
                    LifecycleState.CANDIDATE,
                    LifecycleState.CONFIRMED,
                    LifecycleState.DEEPENING,
                ),
            }[self.transition_type]
            if self.previous_state not in allowed_previous:
                raise ValueError("previous_state is not valid for this transition_type")

        if self.lifecycle is None and self.evidence_refs:
            raise ValueError("evidence_refs require a lifecycle")
        if self.lifecycle is not None:
            for ref in self.evidence_refs:
                candle = ref.candle
                if candle.broker_server != self.lifecycle.broker_server or candle.symbol != self.lifecycle.symbol:
                    raise ValueError("transition evidence identity must match lifecycle")
                if ref.confirmed_at_utc > occurred:
                    raise ValueError("transition cannot use evidence confirmed in the future")
            latest_close = self.lifecycle.last_processed_m5_utc + timedelta(seconds=_M5_SECONDS)
            if occurred > latest_close:
                raise ValueError("transition cannot occur after the last processed M5 close")
            if occurred < self.lifecycle.candidate_started_at_utc:
                raise ValueError("transition cannot precede candidate creation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_type": self.transition_type.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "current_state": self.current_state.value if self.current_state else None,
            "lifecycle": self.lifecycle.to_dict() if self.lifecycle is not None else None,
            "occurred_at_utc": _datetime_to_string(self.occurred_at_utc),
            "reason_codes": list(self.reason_codes),
            "evidence_refs": [_evidence_to_dict(ref) for ref in self.evidence_refs],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TransitionResult:
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        lifecycle_payload = payload["lifecycle"]
        previous = payload["previous_state"]
        current = payload["current_state"]
        return cls(
            transition_type=TransitionType(payload["transition_type"]),
            previous_state=LifecycleState(previous) if previous is not None else None,
            current_state=LifecycleState(current) if current is not None else None,
            lifecycle=(
                CorrectionLifecycle.from_dict(lifecycle_payload)
                if lifecycle_payload is not None
                else None
            ),
            occurred_at_utc=_parse_datetime(payload["occurred_at_utc"], "occurred_at_utc"),
            reason_codes=tuple(payload["reason_codes"]),
            evidence_refs=tuple(_evidence_from_dict(item) for item in payload["evidence_refs"]),
        )

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from eurusd_ai_monitor.storage.market_data_store import (
    Candle,
    TIMEFRAME_SECONDS,
)


class TrendDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


class MovementDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class EvidenceRole(str, Enum):
    TREND_PIVOT = "TREND_PIVOT"
    CORRECTION = "CORRECTION"
    REJECTION = "REJECTION"
    PULLBACK = "PULLBACK"
    ENTRY = "ENTRY"


class PatternStatus(str, Enum):
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class EntryEligibility(str, Enum):
    BLOCKED = "BLOCKED"
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"


class OutcomeStatus(str, Enum):
    OPEN = "OPEN"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    TIME_EXIT = "TIME_EXIT"
    AMBIGUOUS = "AMBIGUOUS"


def _utc_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _positive_decimal(value: Decimal, field_name: str) -> Decimal:
    result = _decimal(value, field_name)
    if result <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return result


def _nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_refs(
    refs: tuple[EvidenceRef, ...],
    timeframe: str,
    field_name: str,
) -> None:
    if not isinstance(refs, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if any(not isinstance(ref, EvidenceRef) for ref in refs):
        raise TypeError(f"{field_name} must contain EvidenceRef values")
    if any(ref.candle.timeframe != timeframe for ref in refs):
        raise ValueError(f"{field_name} evidence must use {timeframe}")


@dataclass(frozen=True)
class MarketContext:
    symbol: str
    source_id: str
    as_of_utc: datetime
    m1_candles: tuple[Candle, ...]
    m5_candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        _nonempty(self.symbol, "symbol")
        _nonempty(self.source_id, "source_id")
        as_of = _utc_datetime(self.as_of_utc, "as_of_utc")
        object.__setattr__(self, "as_of_utc", as_of)

        for field_name, candles, timeframe in (
            ("m1_candles", self.m1_candles, "M1"),
            ("m5_candles", self.m5_candles, "M5"),
        ):
            if not isinstance(candles, tuple):
                raise TypeError(f"{field_name} must be a tuple")
            if any(not isinstance(candle, Candle) for candle in candles):
                raise TypeError(f"{field_name} must contain Candle values")
            open_times = []
            for candle in candles:
                if candle.symbol != self.symbol:
                    raise ValueError(f"{field_name} contains another symbol")
                if candle.broker_server != self.source_id:
                    raise ValueError(f"{field_name} contains another source")
                if candle.timeframe != timeframe:
                    raise ValueError(f"{field_name} contains another timeframe")
                close_time = candle.candle_open_time_utc + timedelta(
                    seconds=TIMEFRAME_SECONDS[timeframe]
                )
                if close_time > as_of:
                    raise ValueError(
                        f"{field_name} contains a candle not closed at as_of_utc"
                    )
                open_times.append(candle.candle_open_time_utc)
            if open_times != sorted(set(open_times)):
                raise ValueError(
                    f"{field_name} must be sorted with no duplicate candles"
                )


@dataclass(frozen=True)
class EvidenceRef:
    candle: Candle
    role: EvidenceRole
    confirmed_at_utc: datetime
    algorithm_version: str
    parameter_version: str
    supporting_candle_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.candle, Candle):
            raise TypeError("candle must be a Candle")
        if not isinstance(self.role, EvidenceRole):
            raise TypeError("role must be an EvidenceRole")
        confirmed_at = _utc_datetime(
            self.confirmed_at_utc,
            "confirmed_at_utc",
        )
        candle_closed_at = self.candle.candle_open_time_utc + timedelta(
            seconds=TIMEFRAME_SECONDS[self.candle.timeframe]
        )
        if confirmed_at < candle_closed_at:
            raise ValueError("evidence cannot be confirmed before its candle closes")
        object.__setattr__(self, "confirmed_at_utc", confirmed_at)
        _nonempty(self.algorithm_version, "algorithm_version")
        _nonempty(self.parameter_version, "parameter_version")
        if not isinstance(self.supporting_candle_ids, tuple):
            raise TypeError("supporting_candle_ids must be a tuple")
        if any(not isinstance(item, str) or not item for item in self.supporting_candle_ids):
            raise ValueError("supporting_candle_ids must contain non-empty strings")

    @property
    def candle_id(self) -> str:
        candle = self.candle
        timestamp = candle.candle_open_time_utc.isoformat().replace("+00:00", "Z")
        return (
            f"{candle.broker_server}|{candle.symbol}|"
            f"{candle.timeframe}|{timestamp}"
        )


@dataclass(frozen=True)
class Trend:
    direction: TrendDirection
    confirmed_at_utc: datetime
    swing_highs: tuple[EvidenceRef, ...]
    swing_lows: tuple[EvidenceRef, ...]
    protected_swing: EvidenceRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.direction, TrendDirection):
            raise TypeError("direction must be a TrendDirection")
        confirmed_at = _utc_datetime(
            self.confirmed_at_utc,
            "confirmed_at_utc",
        )
        object.__setattr__(self, "confirmed_at_utc", confirmed_at)
        _validate_refs(self.swing_highs, "M5", "swing_highs")
        _validate_refs(self.swing_lows, "M5", "swing_lows")
        refs = self.swing_highs + self.swing_lows
        if any(ref.confirmed_at_utc > confirmed_at for ref in refs):
            raise ValueError("trend cannot use evidence confirmed in the future")

        for name, sequence in (
            ("swing_highs", self.swing_highs),
            ("swing_lows", self.swing_lows),
        ):
            times = [ref.candle.candle_open_time_utc for ref in sequence]
            if times != sorted(set(times)):
                raise ValueError(f"{name} must be chronologically ordered")

        if self.direction in (TrendDirection.UP, TrendDirection.DOWN):
            if len(self.swing_highs) < 2 or len(self.swing_lows) < 2:
                raise ValueError("directional trend requires two swing highs and lows")
            previous_high, latest_high = (
                ref.candle.high for ref in self.swing_highs[-2:]
            )
            previous_low, latest_low = (
                ref.candle.low for ref in self.swing_lows[-2:]
            )
            if self.direction is TrendDirection.UP:
                if latest_high <= previous_high or latest_low <= previous_low:
                    raise ValueError("UP trend requires higher highs and higher lows")
                if self.protected_swing != self.swing_lows[-1]:
                    raise ValueError("UP trend protected swing must be its latest low")
            else:
                if latest_high >= previous_high or latest_low >= previous_low:
                    raise ValueError("DOWN trend requires lower highs and lower lows")
                if self.protected_swing != self.swing_highs[-1]:
                    raise ValueError("DOWN trend protected swing must be its latest high")


@dataclass(frozen=True)
class Correction:
    trend_direction: TrendDirection
    movement_direction: MovementDirection
    started_at_utc: datetime
    ended_at_utc: datetime
    depth_pips: Decimal
    previous_impulse_size_pips: Decimal
    evidence: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if self.trend_direction not in (TrendDirection.UP, TrendDirection.DOWN):
            raise ValueError("correction requires a directional trend")
        if not isinstance(self.movement_direction, MovementDirection):
            raise TypeError("movement_direction must be a MovementDirection")
        expected = (
            MovementDirection.DOWN
            if self.trend_direction is TrendDirection.UP
            else MovementDirection.UP
        )
        if self.movement_direction is not expected:
            raise ValueError("correction movement must oppose the trend")

        started = _utc_datetime(self.started_at_utc, "started_at_utc")
        ended = _utc_datetime(self.ended_at_utc, "ended_at_utc")
        if started > ended:
            raise ValueError("started_at_utc must not follow ended_at_utc")
        object.__setattr__(self, "started_at_utc", started)
        object.__setattr__(self, "ended_at_utc", ended)
        _positive_decimal(self.depth_pips, "depth_pips")
        _positive_decimal(
            self.previous_impulse_size_pips,
            "previous_impulse_size_pips",
        )
        if not isinstance(self.evidence, tuple):
            raise TypeError("evidence must be a tuple")
        if any(
            not isinstance(ref, EvidenceRef) or ref.candle.timeframe != "M5"
            for ref in self.evidence
        ):
            raise ValueError("correction evidence must contain M5 EvidenceRef values")

    @property
    def correction_ratio(self) -> Decimal:
        return self.depth_pips / self.previous_impulse_size_pips


@dataclass(frozen=True)
class Rejection:
    trend_direction: TrendDirection
    rejection_direction: TrendDirection
    candle: EvidenceRef
    level: Decimal

    def __post_init__(self) -> None:
        if self.trend_direction not in (TrendDirection.UP, TrendDirection.DOWN):
            raise ValueError("rejection requires a directional trend")
        if self.rejection_direction is not self.trend_direction:
            raise ValueError("rejection direction must agree with the trend")
        if not isinstance(self.candle, EvidenceRef):
            raise TypeError("candle must be an EvidenceRef")
        if self.candle.candle.timeframe != "M1":
            raise ValueError("rejection evidence must use M1")
        _positive_decimal(self.level, "level")
        if self.body <= 0:
            raise ValueError("zero-body candles are not valid rejections")

    @property
    def body(self) -> Decimal:
        candle = self.candle.candle
        return abs(candle.close - candle.open)

    @property
    def upper_wick(self) -> Decimal:
        candle = self.candle.candle
        return candle.high - max(candle.open, candle.close)

    @property
    def lower_wick(self) -> Decimal:
        candle = self.candle.candle
        return min(candle.open, candle.close) - candle.low

    @property
    def candle_range(self) -> Decimal:
        candle = self.candle.candle
        return candle.high - candle.low

    @property
    def close_location(self) -> Decimal:
        candle = self.candle.candle
        return (candle.close - candle.low) / self.candle_range

    @property
    def wick_body_ratio(self) -> Decimal:
        wick = (
            self.lower_wick
            if self.rejection_direction is TrendDirection.UP
            else self.upper_wick
        )
        return wick / self.body


@dataclass(frozen=True)
class Pullback:
    direction: TrendDirection
    breakout: EvidenceRef
    retest: EvidenceRef
    trigger_level: Decimal
    confirmed_at_utc: datetime
    next_bar_open: EvidenceRef | None = None

    def __post_init__(self) -> None:
        if self.direction not in (TrendDirection.UP, TrendDirection.DOWN):
            raise ValueError("pullback requires a directional trend")
        for name, ref in (("breakout", self.breakout), ("retest", self.retest)):
            if not isinstance(ref, EvidenceRef):
                raise TypeError(f"{name} must be an EvidenceRef")
            if ref.candle.timeframe != "M1":
                raise ValueError(f"{name} evidence must use M1")
        if (
            self.breakout.candle.candle_open_time_utc
            >= self.retest.candle.candle_open_time_utc
        ):
            raise ValueError("retest must occur after breakout")
        _positive_decimal(self.trigger_level, "trigger_level")

        confirmed_at = _utc_datetime(
            self.confirmed_at_utc,
            "confirmed_at_utc",
        )
        retest_close = self.retest.candle.candle_open_time_utc + timedelta(
            seconds=TIMEFRAME_SECONDS["M1"]
        )
        if confirmed_at != retest_close:
            raise ValueError("pullback is confirmed when its retest candle closes")
        object.__setattr__(self, "confirmed_at_utc", confirmed_at)

        if self.next_bar_open is not None:
            if not isinstance(self.next_bar_open, EvidenceRef):
                raise TypeError("next_bar_open must be an EvidenceRef or None")
            if self.next_bar_open.candle.timeframe != "M1":
                raise ValueError("next_bar_open evidence must use M1")
            if self.next_bar_open.candle.candle_open_time_utc != confirmed_at:
                raise ValueError("entry evidence must be the next M1 candle")


@dataclass(frozen=True)
class TradeSetup:
    setup_id: str
    strategy_version: str
    algorithm_version: str
    parameter_version: str
    session_id: str
    pattern_status: PatternStatus
    entry_eligibility: EntryEligibility
    trend: Trend
    correction: Correction
    rejection: Rejection
    pullback: Pullback | None
    detected_at_utc: datetime
    confirmed_at_utc: datetime | None
    entry_bar_evidence: EvidenceRef | None
    entry_at_utc: datetime | None
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    entry_gap_policy: str | None
    confirmed_reasons: tuple[str, ...] = ()
    rejected_reasons: tuple[str, ...] = ()
    entry_block_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "setup_id",
            "strategy_version",
            "algorithm_version",
            "parameter_version",
            "session_id",
        ):
            _nonempty(getattr(self, field_name), field_name)
        if not isinstance(self.pattern_status, PatternStatus):
            raise TypeError("pattern_status must be a PatternStatus")
        if not isinstance(self.entry_eligibility, EntryEligibility):
            raise TypeError("entry_eligibility must be an EntryEligibility")
        if not isinstance(self.trend, Trend):
            raise TypeError("trend must be a Trend")
        if not isinstance(self.correction, Correction):
            raise TypeError("correction must be a Correction")
        if not isinstance(self.rejection, Rejection):
            raise TypeError("rejection must be a Rejection")
        if self.pullback is not None and not isinstance(self.pullback, Pullback):
            raise TypeError("pullback must be a Pullback or None")
        if self.entry_bar_evidence is not None:
            if not isinstance(self.entry_bar_evidence, EvidenceRef):
                raise TypeError("entry_bar_evidence must be an EvidenceRef or None")
            if self.entry_bar_evidence.candle.timeframe != "M1":
                raise ValueError("entry_bar_evidence must use M1")
        if self.correction.trend_direction is not self.trend.direction:
            raise ValueError("correction and trend directions must match")
        if self.rejection.trend_direction is not self.trend.direction:
            raise ValueError("rejection and trend directions must match")
        if self.pullback is not None and self.pullback.direction is not self.trend.direction:
            raise ValueError("pullback and trend directions must match")

        detected_at = _utc_datetime(
            self.detected_at_utc,
            "detected_at_utc",
        )
        object.__setattr__(self, "detected_at_utc", detected_at)
        confirmed_at = (
            _utc_datetime(self.confirmed_at_utc, "confirmed_at_utc")
            if self.confirmed_at_utc is not None
            else None
        )
        object.__setattr__(self, "confirmed_at_utc", confirmed_at)
        if confirmed_at is not None and confirmed_at < detected_at:
            raise ValueError("confirmed_at_utc must not precede detected_at_utc")
        if self.pattern_status is PatternStatus.CONFIRMED:
            if self.pullback is None or confirmed_at is None:
                raise ValueError("confirmed pattern requires a confirmed pullback")
            if confirmed_at != self.pullback.confirmed_at_utc:
                raise ValueError("setup confirmation must match pullback confirmation")
        if self.entry_gap_policy is not None:
            _nonempty(self.entry_gap_policy, "entry_gap_policy")

        entry_values = (
            self.entry_at_utc,
            self.entry_price,
            self.stop_loss,
            self.take_profit,
        )
        if self.entry_eligibility is EntryEligibility.ELIGIBLE:
            if self.pattern_status is not PatternStatus.CONFIRMED:
                raise ValueError("eligible entry requires a confirmed pattern")
            if self.entry_gap_policy is None:
                raise ValueError("eligible entry requires an explicit gap policy")
            if any(value is None for value in entry_values):
                raise ValueError("eligible entry requires price, time, SL and TP")
            if not isinstance(self.entry_bar_evidence, EvidenceRef):
                raise ValueError("eligible entry requires next-bar evidence")
            if self.pullback is None:
                raise ValueError("eligible entry requires a pullback")
            entry_at = _utc_datetime(self.entry_at_utc, "entry_at_utc")
            object.__setattr__(self, "entry_at_utc", entry_at)
            _positive_decimal(self.entry_price, "entry_price")
            _positive_decimal(self.stop_loss, "stop_loss")
            _positive_decimal(self.take_profit, "take_profit")
            if self.entry_bar_evidence.candle.timeframe != "M1":
                raise ValueError("entry evidence must use M1")
            if self.entry_bar_evidence.candle.candle_open_time_utc != entry_at:
                raise ValueError("entry time must be the next candle open")
            if self.entry_bar_evidence.candle.open != self.entry_price:
                raise ValueError("entry price must equal the next candle open")
            if self.pullback.confirmed_at_utc != entry_at:
                raise ValueError("entry must follow pullback confirmation")
            if self.trend.direction is TrendDirection.UP:
                valid_prices = self.stop_loss < self.entry_price < self.take_profit
            else:
                valid_prices = self.take_profit < self.entry_price < self.stop_loss
            if not valid_prices:
                raise ValueError("entry, stop loss and take profit are inconsistent")
        else:
            if any(value is not None for value in entry_values):
                raise ValueError(
                    "blocked or rejected entry cannot contain entry prices or time"
                )

        for name, reasons in (
            ("confirmed_reasons", self.confirmed_reasons),
            ("rejected_reasons", self.rejected_reasons),
            ("entry_block_reasons", self.entry_block_reasons),
        ):
            if not isinstance(reasons, tuple):
                raise TypeError(f"{name} must be a tuple")
            if any(not isinstance(reason, str) or not reason.strip() for reason in reasons):
                raise ValueError(f"{name} must contain non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return _encode(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TradeSetup:
        return _trade_setup_from_dict(payload)


@dataclass(frozen=True)
class TradeOutcome:
    setup_id: str
    status: OutcomeStatus
    opened_at_utc: datetime
    entry_price: Decimal
    closed_at_utc: datetime | None = None
    exit_price: Decimal | None = None

    def __post_init__(self) -> None:
        _nonempty(self.setup_id, "setup_id")
        if not isinstance(self.status, OutcomeStatus):
            raise TypeError("status must be an OutcomeStatus")
        opened = _utc_datetime(self.opened_at_utc, "opened_at_utc")
        object.__setattr__(self, "opened_at_utc", opened)
        _positive_decimal(self.entry_price, "entry_price")
        if self.status is OutcomeStatus.OPEN:
            if self.closed_at_utc is not None or self.exit_price is not None:
                raise ValueError("OPEN outcome cannot have close data")
            return
        if self.closed_at_utc is None:
            raise ValueError("closed outcome requires closed_at_utc")
        closed = _utc_datetime(self.closed_at_utc, "closed_at_utc")
        if closed < opened:
            raise ValueError("closed_at_utc must not precede opened_at_utc")
        object.__setattr__(self, "closed_at_utc", closed)
        if self.exit_price is not None:
            _positive_decimal(self.exit_price, "exit_price")
        if self.status is not OutcomeStatus.AMBIGUOUS and self.exit_price is None:
            raise ValueError("resolved outcome requires exit_price")

    def to_dict(self) -> dict[str, Any]:
        return _encode(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TradeOutcome:
        closed_at = payload["closed_at_utc"]
        exit_price = payload["exit_price"]
        return cls(
            setup_id=payload["setup_id"],
            status=OutcomeStatus(payload["status"]),
            opened_at_utc=_parse_datetime(
                payload["opened_at_utc"],
                "opened_at_utc",
            ),
            entry_price=_parse_decimal(payload["entry_price"], "entry_price"),
            closed_at_utc=(
                _parse_datetime(closed_at, "closed_at_utc")
                if closed_at is not None
                else None
            ),
            exit_price=(
                _parse_decimal(exit_price, "exit_price")
                if exit_price is not None
                else None
            ),
        )


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _encode(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be an ISO datetime string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utc_datetime(parsed, field_name)


def _parse_decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a decimal string")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _candle_from_dict(payload: Mapping[str, Any]) -> Candle:
    return Candle(
        broker_server=payload["broker_server"],
        symbol=payload["symbol"],
        timeframe=payload["timeframe"],
        candle_open_time_utc=_parse_datetime(
            payload["candle_open_time_utc"],
            "candle_open_time_utc",
        ),
        open=_parse_decimal(payload["open"], "open"),
        high=_parse_decimal(payload["high"], "high"),
        low=_parse_decimal(payload["low"], "low"),
        close=_parse_decimal(payload["close"], "close"),
        tick_volume=payload["tick_volume"],
        spread=payload["spread"],
        real_volume=payload["real_volume"],
    )


def _evidence_from_dict(payload: Mapping[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        candle=_candle_from_dict(payload["candle"]),
        role=EvidenceRole(payload["role"]),
        confirmed_at_utc=_parse_datetime(
            payload["confirmed_at_utc"],
            "confirmed_at_utc",
        ),
        algorithm_version=payload["algorithm_version"],
        parameter_version=payload["parameter_version"],
        supporting_candle_ids=tuple(payload["supporting_candle_ids"]),
    )


def _trend_from_dict(payload: Mapping[str, Any]) -> Trend:
    protected = payload["protected_swing"]
    return Trend(
        direction=TrendDirection(payload["direction"]),
        confirmed_at_utc=_parse_datetime(
            payload["confirmed_at_utc"],
            "confirmed_at_utc",
        ),
        swing_highs=tuple(
            _evidence_from_dict(item) for item in payload["swing_highs"]
        ),
        swing_lows=tuple(
            _evidence_from_dict(item) for item in payload["swing_lows"]
        ),
        protected_swing=(
            _evidence_from_dict(protected) if protected is not None else None
        ),
    )


def _correction_from_dict(payload: Mapping[str, Any]) -> Correction:
    return Correction(
        trend_direction=TrendDirection(payload["trend_direction"]),
        movement_direction=MovementDirection(payload["movement_direction"]),
        started_at_utc=_parse_datetime(
            payload["started_at_utc"],
            "started_at_utc",
        ),
        ended_at_utc=_parse_datetime(
            payload["ended_at_utc"],
            "ended_at_utc",
        ),
        depth_pips=_parse_decimal(payload["depth_pips"], "depth_pips"),
        previous_impulse_size_pips=_parse_decimal(
            payload["previous_impulse_size_pips"],
            "previous_impulse_size_pips",
        ),
        evidence=tuple(
            _evidence_from_dict(item) for item in payload["evidence"]
        ),
    )


def _rejection_from_dict(payload: Mapping[str, Any]) -> Rejection:
    return Rejection(
        trend_direction=TrendDirection(payload["trend_direction"]),
        rejection_direction=TrendDirection(payload["rejection_direction"]),
        candle=_evidence_from_dict(payload["candle"]),
        level=_parse_decimal(payload["level"], "level"),
    )


def _pullback_from_dict(payload: Mapping[str, Any]) -> Pullback:
    next_bar = payload["next_bar_open"]
    return Pullback(
        direction=TrendDirection(payload["direction"]),
        breakout=_evidence_from_dict(payload["breakout"]),
        retest=_evidence_from_dict(payload["retest"]),
        trigger_level=_parse_decimal(payload["trigger_level"], "trigger_level"),
        confirmed_at_utc=_parse_datetime(
            payload["confirmed_at_utc"],
            "confirmed_at_utc",
        ),
        next_bar_open=(
            _evidence_from_dict(next_bar) if next_bar is not None else None
        ),
    )


def _trade_setup_from_dict(payload: Mapping[str, Any]) -> TradeSetup:
    pullback = payload["pullback"]
    entry_evidence = payload["entry_bar_evidence"]

    def optional_decimal(name: str) -> Decimal | None:
        value = payload[name]
        return _parse_decimal(value, name) if value is not None else None

    return TradeSetup(
        setup_id=payload["setup_id"],
        strategy_version=payload["strategy_version"],
        algorithm_version=payload["algorithm_version"],
        parameter_version=payload["parameter_version"],
        session_id=payload["session_id"],
        pattern_status=PatternStatus(payload["pattern_status"]),
        entry_eligibility=EntryEligibility(payload["entry_eligibility"]),
        trend=_trend_from_dict(payload["trend"]),
        correction=_correction_from_dict(payload["correction"]),
        rejection=_rejection_from_dict(payload["rejection"]),
        pullback=_pullback_from_dict(pullback) if pullback is not None else None,
        detected_at_utc=_parse_datetime(
            payload["detected_at_utc"],
            "detected_at_utc",
        ),
        confirmed_at_utc=(
            _parse_datetime(payload["confirmed_at_utc"], "confirmed_at_utc")
            if payload["confirmed_at_utc"] is not None
            else None
        ),
        entry_bar_evidence=(
            _evidence_from_dict(entry_evidence)
            if entry_evidence is not None
            else None
        ),
        entry_at_utc=(
            _parse_datetime(payload["entry_at_utc"], "entry_at_utc")
            if payload["entry_at_utc"] is not None
            else None
        ),
        entry_price=optional_decimal("entry_price"),
        stop_loss=optional_decimal("stop_loss"),
        take_profit=optional_decimal("take_profit"),
        entry_gap_policy=payload["entry_gap_policy"],
        confirmed_reasons=tuple(payload["confirmed_reasons"]),
        rejected_reasons=tuple(payload["rejected_reasons"]),
        entry_block_reasons=tuple(payload["entry_block_reasons"]),
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json

from eurusd_ai_monitor.models.price_action import (
    EvidenceRef,
    EvidenceRole,
    MarketContext,
    Trend,
    TrendDirection,
)
from eurusd_ai_monitor.storage.market_data_store import Candle, TIMEFRAME_SECONDS
from eurusd_ai_monitor.strategy_config import StrategyConfig


MARKET_STRUCTURE_ALGORITHM_VERSION = "m5-market-structure-v2"
_M5_DURATION = timedelta(seconds=TIMEFRAME_SECONDS["M5"])


class PivotKind(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True)
class Pivot:
    kind: PivotKind
    evidence: EvidenceRef

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PivotKind):
            raise TypeError("kind must be a PivotKind")
        if not isinstance(self.evidence, EvidenceRef):
            raise TypeError("evidence must be an EvidenceRef")
        if self.evidence.candle.timeframe != "M5":
            raise ValueError("pivot evidence must use M5")
        if self.evidence.role is not EvidenceRole.TREND_PIVOT:
            raise ValueError("pivot evidence must have the TREND_PIVOT role")

    @property
    def price(self) -> Decimal:
        return (
            self.evidence.candle.high
            if self.kind is PivotKind.HIGH
            else self.evidence.candle.low
        )


@dataclass(frozen=True)
class ProtectedSwingBreak:
    broken_direction: TrendDirection
    protected_swing: EvidenceRef
    structure_time_utc: datetime
    break_candle: Candle
    confirmed_at_utc: datetime

    def __post_init__(self) -> None:
        if self.broken_direction not in (TrendDirection.UP, TrendDirection.DOWN):
            raise ValueError("broken_direction must be UP or DOWN")
        if not isinstance(self.protected_swing, EvidenceRef):
            raise TypeError("protected_swing must be an EvidenceRef")
        if not isinstance(self.break_candle, Candle):
            raise TypeError("break_candle must be a Candle")
        if self.protected_swing.candle.timeframe != "M5":
            raise ValueError("protected_swing must use M5")
        if self.break_candle.timeframe != "M5":
            raise ValueError("break_candle must use M5")
        if (
            self.confirmed_at_utc.tzinfo is None
            or self.confirmed_at_utc.utcoffset() is None
        ):
            raise ValueError("confirmed_at_utc must be timezone-aware")
        if (
            self.structure_time_utc.tzinfo is None
            or self.structure_time_utc.utcoffset() is None
        ):
            raise ValueError("structure_time_utc must be timezone-aware")
        structure_time = self.structure_time_utc.astimezone(timezone.utc)
        confirmed_at = self.confirmed_at_utc.astimezone(timezone.utc)
        expected_close = self.break_candle.candle_open_time_utc + _M5_DURATION
        if confirmed_at != expected_close:
            raise ValueError("break is confirmed only when its candle closes")
        if confirmed_at <= structure_time:
            raise ValueError("break must close after structure confirmation")
        if self.break_candle.candle_open_time_utc < structure_time:
            raise ValueError("break candle must open after structure confirmation")
        if confirmed_at <= self.protected_swing.confirmed_at_utc:
            raise ValueError("break must follow confirmation of the protected swing")
        if self.break_candle.candle_open_time_utc < self.protected_swing.confirmed_at_utc:
            raise ValueError("break candle must open after swing confirmation")
        if self.broken_direction is TrendDirection.UP:
            crossed = self.break_candle.close < self.protected_swing.candle.low
        else:
            crossed = self.break_candle.close > self.protected_swing.candle.high
        if not crossed:
            raise ValueError("break candle must close beyond the protected swing")
        object.__setattr__(self, "structure_time_utc", structure_time)
        object.__setattr__(self, "confirmed_at_utc", confirmed_at)


@dataclass(frozen=True)
class TechnicalStructure:
    trend: Trend
    pivots: tuple[Pivot, ...]
    protected_swing_break: ProtectedSwingBreak | None
    structure_time_utc: datetime | None
    evaluated_at_utc: datetime
    algorithm_version: str
    parameter_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.trend, Trend):
            raise TypeError("trend must be a Trend")
        if not isinstance(self.pivots, tuple) or any(
            not isinstance(pivot, Pivot) for pivot in self.pivots
        ):
            raise TypeError("pivots must be a tuple of Pivot values")
        if self.protected_swing_break is not None and not isinstance(
            self.protected_swing_break, ProtectedSwingBreak
        ):
            raise TypeError("protected_swing_break must be a ProtectedSwingBreak")
        for field_name in ("algorithm_version", "parameter_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if (
            self.evaluated_at_utc.tzinfo is None
            or self.evaluated_at_utc.utcoffset() is None
        ):
            raise ValueError("evaluated_at_utc must be timezone-aware")
        evaluated_at = self.evaluated_at_utc.astimezone(timezone.utc)
        structure_time = self.structure_time_utc
        if structure_time is not None:
            if structure_time.tzinfo is None or structure_time.utcoffset() is None:
                raise ValueError("structure_time_utc must be timezone-aware or None")
            structure_time = structure_time.astimezone(timezone.utc)
            if structure_time > evaluated_at:
                raise ValueError("structure cannot be confirmed after evaluation time")
        if self.trend.confirmed_at_utc > evaluated_at:
            raise ValueError("trend cannot be confirmed after evaluation time")
        if any(pivot.evidence.confirmed_at_utc > evaluated_at for pivot in self.pivots):
            raise ValueError("pivots cannot be confirmed after evaluation time")
        if (
            self.protected_swing_break is not None
            and self.protected_swing_break.confirmed_at_utc > evaluated_at
        ):
            raise ValueError("swing break cannot be confirmed after evaluation time")
        if self.protected_swing_break is not None and (
            structure_time != self.protected_swing_break.structure_time_utc
        ):
            raise ValueError("swing break must reference this structure's confirmation")
        if self.trend.direction in (TrendDirection.UP, TrendDirection.DOWN):
            if structure_time != self.trend.confirmed_at_utc:
                raise ValueError("directional trend time must match structure time")
        object.__setattr__(self, "structure_time_utc", structure_time)
        object.__setattr__(self, "evaluated_at_utc", evaluated_at)


class TechnicalEngine:
    """Determines closed-candle M5 swing structure without producing signals."""

    def __init__(self, config: StrategyConfig) -> None:
        if not isinstance(config, StrategyConfig):
            raise TypeError("config must be a StrategyConfig")
        self._config = config
        self._parameter_version = _strategy_parameter_version(config)

    def analyze_m5(self, context: MarketContext) -> TechnicalStructure:
        if not isinstance(context, MarketContext):
            raise TypeError("context must be a MarketContext")
        _validate_m5_context(context)

        return self._analyze_validated_context(context)

    def analyze_m5_at(
        self,
        context: MarketContext,
        as_of_utc: datetime,
    ) -> TechnicalStructure:
        """Rebuild a point-in-time snapshot while ignoring later candles."""
        if not isinstance(context, MarketContext):
            raise TypeError("context must be a MarketContext")
        if not isinstance(as_of_utc, datetime):
            raise TypeError("as_of_utc must be a datetime")
        if as_of_utc.tzinfo is None or as_of_utc.utcoffset() is None:
            raise ValueError("as_of_utc must be timezone-aware")
        as_of = as_of_utc.astimezone(timezone.utc)
        if as_of > context.as_of_utc:
            raise ValueError("as_of_utc cannot exceed the context's as_of_utc")

        historical_context = MarketContext(
            symbol=context.symbol,
            source_id=context.source_id,
            as_of_utc=as_of,
            m1_candles=tuple(
                candle
                for candle in context.m1_candles
                if candle.candle_open_time_utc
                + timedelta(seconds=TIMEFRAME_SECONDS["M1"])
                <= as_of
            ),
            m5_candles=tuple(
                candle
                for candle in context.m5_candles
                if candle.candle_open_time_utc + _M5_DURATION <= as_of
            ),
        )
        return self.analyze_m5(historical_context)

    def _analyze_validated_context(
        self,
        context: MarketContext,
    ) -> TechnicalStructure:
        pivots = self._find_confirmed_pivots(context)
        highs = tuple(p.evidence for p in pivots if p.kind is PivotKind.HIGH)
        lows = tuple(p.evidence for p in pivots if p.kind is PivotKind.LOW)
        latest_highs = highs[-2:]
        latest_lows = lows[-2:]
        structural_refs = latest_highs + latest_lows
        structure_time = (
            max(ref.confirmed_at_utc for ref in structural_refs)
            if len(latest_highs) == 2 and len(latest_lows) == 2
            else None
        )

        direction = _classify_structure(latest_highs, latest_lows)
        if direction not in (TrendDirection.UP, TrendDirection.DOWN):
            trend = Trend(
                direction=direction,
                confirmed_at_utc=structure_time or context.as_of_utc,
                swing_highs=latest_highs,
                swing_lows=latest_lows,
            )
            return self._result(context, pivots, trend, None, structure_time)

        if structure_time is None:
            raise RuntimeError("directional structure is missing its confirmation time")
        protected = latest_lows[-1] if direction is TrendDirection.UP else latest_highs[-1]
        swing_break = self._find_protected_swing_break(
            context,
            direction,
            protected,
            structure_time,
        )
        if swing_break is not None:
            trend = Trend(
                direction=TrendDirection.RANGE,
                confirmed_at_utc=swing_break.confirmed_at_utc,
                swing_highs=latest_highs,
                swing_lows=latest_lows,
            )
        else:
            trend = Trend(
                direction=direction,
                confirmed_at_utc=structure_time,
                swing_highs=latest_highs,
                swing_lows=latest_lows,
                protected_swing=protected,
            )
        return self._result(context, pivots, trend, swing_break, structure_time)

    def _find_confirmed_pivots(self, context: MarketContext) -> tuple[Pivot, ...]:
        """Use strict extrema; equality with any neighbor disqualifies a pivot."""
        candles = context.m5_candles
        left = self._config.pivot_left_bars
        right = self._config.pivot_right_bars
        pivots: list[Pivot] = []

        for index in range(left, len(candles) - right):
            candidate = candles[index]
            left_candles = candles[index - left : index]
            right_candles = candles[index + 1 : index + right + 1]
            if len(left_candles) != left or len(right_candles) != right:
                continue
            confirmed_at = right_candles[-1].candle_open_time_utc + _M5_DURATION
            if confirmed_at > context.as_of_utc:
                continue

            support_ids = tuple(_candle_id(candle) for candle in right_candles)
            evidence = EvidenceRef(
                candle=candidate,
                role=EvidenceRole.TREND_PIVOT,
                confirmed_at_utc=confirmed_at,
                algorithm_version=MARKET_STRUCTURE_ALGORITHM_VERSION,
                parameter_version=self._parameter_version,
                supporting_candle_ids=support_ids,
            )
            if all(candidate.high > candle.high for candle in left_candles + right_candles):
                pivots.append(Pivot(PivotKind.HIGH, evidence))
            if all(candidate.low < candle.low for candle in left_candles + right_candles):
                pivots.append(Pivot(PivotKind.LOW, evidence))

        return tuple(
            sorted(
                pivots,
                key=lambda pivot: (
                    pivot.evidence.confirmed_at_utc,
                    pivot.evidence.candle.candle_open_time_utc,
                    pivot.kind.value,
                ),
            )
        )

    def _find_protected_swing_break(
        self,
        context: MarketContext,
        direction: TrendDirection,
        protected: EvidenceRef,
        structure_time: datetime,
    ) -> ProtectedSwingBreak | None:
        for candle in context.m5_candles:
            close_time = candle.candle_open_time_utc + _M5_DURATION
            if (
                candle.candle_open_time_utc < structure_time
                or close_time <= structure_time
            ):
                continue
            crossed = (
                candle.close < protected.candle.low
                if direction is TrendDirection.UP
                else candle.close > protected.candle.high
            )
            if crossed:
                return ProtectedSwingBreak(
                    broken_direction=direction,
                    protected_swing=protected,
                    structure_time_utc=structure_time,
                    break_candle=candle,
                    confirmed_at_utc=close_time,
                )
        return None

    def _result(
        self,
        context: MarketContext,
        pivots: tuple[Pivot, ...],
        trend: Trend,
        swing_break: ProtectedSwingBreak | None,
        structure_time: datetime | None,
    ) -> TechnicalStructure:
        return TechnicalStructure(
            trend=trend,
            pivots=pivots,
            protected_swing_break=swing_break,
            structure_time_utc=structure_time,
            evaluated_at_utc=context.as_of_utc,
            algorithm_version=MARKET_STRUCTURE_ALGORITHM_VERSION,
            parameter_version=self._parameter_version,
        )


def _classify_structure(
    swing_highs: tuple[EvidenceRef, ...],
    swing_lows: tuple[EvidenceRef, ...],
) -> TrendDirection:
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return TrendDirection.UNKNOWN
    if not _has_alternating_swing_order(swing_highs, swing_lows):
        return TrendDirection.RANGE

    previous_high, latest_high = swing_highs[-2:]
    previous_low, latest_low = swing_lows[-2:]
    higher_high = latest_high.candle.high > previous_high.candle.high
    higher_low = latest_low.candle.low > previous_low.candle.low
    lower_high = latest_high.candle.high < previous_high.candle.high
    lower_low = latest_low.candle.low < previous_low.candle.low

    if higher_high and higher_low:
        return TrendDirection.UP
    if lower_high and lower_low:
        return TrendDirection.DOWN
    return TrendDirection.RANGE


def _has_alternating_swing_order(
    swing_highs: tuple[EvidenceRef, ...],
    swing_lows: tuple[EvidenceRef, ...],
) -> bool:
    """Require the latest four swings to alternate by pivot time, with no ties."""
    events = [
        (ref.candle.candle_open_time_utc, "HIGH")
        for ref in swing_highs[-2:]
    ] + [
        (ref.candle.candle_open_time_utc, "LOW")
        for ref in swing_lows[-2:]
    ]
    events.sort(key=lambda event: event[0])
    if len(events) != 4 or len({timestamp for timestamp, _ in events}) != 4:
        return False
    return all(events[index - 1][1] != events[index][1] for index in range(1, 4))


def _validate_m5_context(context: MarketContext) -> None:
    candles = context.m5_candles
    if tuple(sorted(candles, key=lambda candle: candle.candle_open_time_utc)) != candles:
        raise ValueError("M5 candles must be in chronological order")
    open_times = tuple(candle.candle_open_time_utc for candle in candles)
    if len(open_times) != len(set(open_times)):
        raise ValueError("M5 candle timestamps must be unique")
    for candle in candles:
        if candle.timeframe != "M5":
            raise ValueError("technical structure requires M5 candles")
        if candle.candle_open_time_utc + _M5_DURATION > context.as_of_utc:
            raise ValueError("technical structure cannot use an open candle")


def _candle_id(candle: Candle) -> str:
    timestamp = candle.candle_open_time_utc.isoformat().replace("+00:00", "Z")
    return f"{candle.broker_server}|{candle.symbol}|{candle.timeframe}|{timestamp}"


def _strategy_parameter_version(config: StrategyConfig) -> str:
    payload = config.to_dict()
    payload.pop("algorithm_version")
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return f"{config.strategy_version}:{digest}"

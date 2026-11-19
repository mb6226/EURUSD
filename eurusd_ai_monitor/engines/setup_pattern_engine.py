from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from eurusd_ai_monitor.models.correction_lifecycle import CorrectionLifecycle, LifecycleState
from eurusd_ai_monitor.models.price_action import (
    EvidenceRef, EvidenceRole, Rejection, Pullback, TrendDirection,
)
from eurusd_ai_monitor.storage.market_data_store import Candle, TIMEFRAME_SECONDS
from eurusd_ai_monitor.strategy_config import StrategyConfig


class SetupStage(str, Enum):
    WAIT_CORRECTION_CONFIRMATION = "WAIT_CORRECTION_CONFIRMATION"
    WAIT_REJECTION = "WAIT_REJECTION"
    WAIT_BREAKOUT = "WAIT_BREAKOUT"
    WAIT_PULLBACK_RETEST = "WAIT_PULLBACK_RETEST"
    PATTERN_CONFIRMED = "PATTERN_CONFIRMED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class SetupAssessment:
    stage: SetupStage
    trend_direction: TrendDirection | None
    rejection: Rejection | None
    pullback: Pullback | None
    trigger_level: Decimal | None
    evaluated_at_utc: datetime
    reason_codes: tuple[str, ...]
    decision_authority: str = "ASSESSMENT_ONLY"
    trade_authority: str = "NONE"
    entry_eligibility: str = "BLOCKED"

    def __post_init__(self) -> None:
        if self.trade_authority != "NONE":
            raise ValueError("setup assessment cannot grant trade authority")
        if self.decision_authority != "ASSESSMENT_ONLY":
            raise ValueError("setup assessment is not a decision authority")
        if self.entry_eligibility != "BLOCKED":
            raise ValueError("Phase 7 does not enable entries")
        if self.stage is SetupStage.PATTERN_CONFIRMED and self.pullback is None:
            raise ValueError("confirmed pattern requires a pullback")
        if not self.reason_codes or any(not item for item in self.reason_codes):
            raise ValueError("reason_codes must be non-empty")

    def to_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "trend_direction": self.trend_direction.value if self.trend_direction else None,
            "rejection": ({
                "candle_id": self.rejection.candle.candle_id,
                "level": str(self.rejection.level),
                "wick_body_ratio": str(self.rejection.wick_body_ratio),
                "close_location": str(self.rejection.close_location),
            } if self.rejection else None),
            "pullback": ({
                "breakout_candle_id": self.pullback.breakout.candle_id,
                "retest_candle_id": self.pullback.retest.candle_id,
                "trigger_level": str(self.pullback.trigger_level),
                "confirmed_at_utc": self.pullback.confirmed_at_utc.isoformat(),
            } if self.pullback else None),
            "trigger_level": str(self.trigger_level) if self.trigger_level is not None else None,
            "evaluated_at_utc": self.evaluated_at_utc.isoformat(),
            "reason_codes": list(self.reason_codes),
            "decision_authority": self.decision_authority,
            "trade_authority": self.trade_authority,
            "entry_eligibility": self.entry_eligibility,
        }


class SetupPatternEngine:
    """Closed-candle M1 rejection and breakout/retest assessment.

    M5 lifecycle remains the sole trend/correction authority. M1 candles only
    refine the already-confirmed correction and can never reverse its trend.
    """

    def __init__(self, config: StrategyConfig) -> None:
        if not isinstance(config, StrategyConfig):
            raise TypeError("config must be a StrategyConfig")
        self._config = config

    def assess(
        self,
        lifecycle: CorrectionLifecycle | None,
        m1_candles: tuple[Candle, ...],
        evaluated_at_utc: datetime,
    ) -> SetupAssessment:
        evaluated = self._utc(evaluated_at_utc)
        if not isinstance(m1_candles, tuple) or any(not isinstance(c, Candle) for c in m1_candles):
            raise TypeError("m1_candles must be a tuple of Candle values")
        ordered = tuple(sorted(m1_candles, key=lambda c: c.candle_open_time_utc))
        if ordered != m1_candles:
            raise ValueError("M1 candles must be chronologically ordered")
        if len({c.candle_open_time_utc for c in ordered}) != len(ordered):
            raise ValueError("M1 candle timestamps must be unique")
        if any(c.timeframe != "M1" for c in ordered):
            raise ValueError("setup detection requires M1 candles")
        if any(c.candle_open_time_utc + timedelta(seconds=60) > evaluated for c in ordered):
            raise ValueError("M1 candles must be closed at evaluated_at_utc")

        if lifecycle is None:
            return self._result(SetupStage.BLOCKED, None, None, None, None, evaluated,
                                ("NO_ACTIVE_CORRECTION_LIFECYCLE",))
        direction = lifecycle.trend_direction
        if lifecycle.state not in (LifecycleState.CONFIRMED, LifecycleState.DEEPENING):
            return self._result(SetupStage.WAIT_CORRECTION_CONFIRMATION, direction, None, None,
                                None, evaluated, ("CORRECTION_NOT_CONFIRMED",))
        if lifecycle.confirmed_at_utc is None:
            return self._result(SetupStage.BLOCKED, direction, None, None, None, evaluated,
                                ("CORRECTION_CONFIRMATION_TIME_MISSING",))
        if not ordered:
            return self._result(SetupStage.WAIT_REJECTION, direction, None, None, None,
                                evaluated, ("M1_EVIDENCE_UNAVAILABLE",))

        level = (
            lifecycle.extreme_evidence.candle.low
            if direction is TrendDirection.UP
            else lifecycle.extreme_evidence.candle.high
        )
        eligible = tuple(
            c for c in ordered
            if c.candle_open_time_utc >= lifecycle.confirmed_at_utc
            and c.broker_server == lifecycle.broker_server
            and c.symbol == lifecycle.symbol
        )
        rejection = self.find_rejection(
            eligible, direction, level, lifecycle.impulse.algorithm_version,
            lifecycle.impulse.parameter_version,
        )
        if rejection is None:
            return self._result(SetupStage.WAIT_REJECTION, direction, None, None, level,
                                evaluated, ("NO_VALID_M1_REJECTION",))

        after_rejection = tuple(
            c for c in eligible
            if c.candle_open_time_utc > rejection.candle.candle.candle_open_time_utc
        )
        pullback = self.find_pullback(
            after_rejection, direction, rejection, self._config.pullback_tolerance_pips
            * self._config.pip_size, lifecycle.impulse.algorithm_version,
            lifecycle.impulse.parameter_version,
        )
        if pullback is None:
            breakout_seen = self._has_breakout(after_rejection, direction, rejection)
            stage = SetupStage.WAIT_PULLBACK_RETEST if breakout_seen else SetupStage.WAIT_BREAKOUT
            reason = "BREAKOUT_CONFIRMED_WAITING_FOR_RETEST" if breakout_seen else "REJECTION_CONFIRMED_WAITING_FOR_BREAKOUT"
            return self._result(stage, direction, rejection, None,
                                self._trigger(direction, rejection), evaluated, (reason,))
        return self._result(SetupStage.PATTERN_CONFIRMED, direction, rejection, pullback,
                            pullback.trigger_level, evaluated,
                            ("TREND_CORRECTION_REJECTION_PULLBACK_CONFIRMED",))

    def find_rejection(
        self, candles: tuple[Candle, ...], direction: TrendDirection, level: Decimal,
        algorithm_version: str, parameter_version: str,
    ) -> Rejection | None:
        for candle in candles:
            body = abs(candle.close - candle.open)
            candle_range = candle.high - candle.low
            if body <= 0 or candle_range <= 0:
                continue
            if direction is TrendDirection.UP:
                wick = min(candle.open, candle.close) - candle.low
                close_location = (candle.close - candle.low) / candle_range
                touched = candle.low <= level
                valid_close = candle.close > level and candle.close > candle.open
                valid_location = close_location >= self._config.bullish_close_location_min
            elif direction is TrendDirection.DOWN:
                wick = candle.high - max(candle.open, candle.close)
                close_location = (candle.close - candle.low) / candle_range
                touched = candle.high >= level
                valid_close = candle.close < level and candle.close < candle.open
                valid_location = close_location <= self._config.bearish_close_location_max
            else:
                return None
            if touched and valid_close and valid_location and wick / body >= self._config.min_wick_body_ratio:
                ref = self._evidence(candle, EvidenceRole.REJECTION, algorithm_version, parameter_version)
                return Rejection(direction, direction, ref, level)
        return None

    def find_pullback(
        self, candles: tuple[Candle, ...], direction: TrendDirection, rejection: Rejection,
        tolerance: Decimal, algorithm_version: str, parameter_version: str,
    ) -> Pullback | None:
        trigger = self._trigger(direction, rejection)
        breakout = None
        for candle in candles:
            if direction is TrendDirection.UP and candle.close > trigger:
                breakout = candle
                break
            if direction is TrendDirection.DOWN and candle.close < trigger:
                breakout = candle
                break
        if breakout is None:
            return None
        for candle in candles:
            if candle.candle_open_time_utc <= breakout.candle_open_time_utc:
                continue
            if direction is TrendDirection.UP:
                # A bullish retest must actually reach the trigger, but may not
                # penetrate it by more than the configured tolerance.
                touched = trigger - tolerance <= candle.low <= trigger
                held = candle.close > trigger
            else:
                # Bearish mirror: reach the trigger from below without
                # overshooting above it by more than the configured tolerance.
                touched = trigger <= candle.high <= trigger + tolerance
                held = candle.close < trigger
            if touched and held:
                breakout_ref = self._evidence(breakout, EvidenceRole.PULLBACK, algorithm_version, parameter_version)
                retest_ref = self._evidence(candle, EvidenceRole.PULLBACK, algorithm_version, parameter_version)
                confirmed = candle.candle_open_time_utc + timedelta(seconds=TIMEFRAME_SECONDS["M1"])
                return Pullback(direction, breakout_ref, retest_ref, trigger, confirmed)
        return None

    @staticmethod
    def _has_breakout(candles: tuple[Candle, ...], direction: TrendDirection, rejection: Rejection) -> bool:
        trigger = SetupPatternEngine._trigger(direction, rejection)
        return any(
            c.close > trigger if direction is TrendDirection.UP else c.close < trigger
            for c in candles
        )

    @staticmethod
    def _trigger(direction: TrendDirection, rejection: Rejection) -> Decimal:
        return rejection.candle.candle.high if direction is TrendDirection.UP else rejection.candle.candle.low

    @staticmethod
    def _evidence(candle: Candle, role: EvidenceRole, algorithm: str, parameters: str) -> EvidenceRef:
        return EvidenceRef(
            candle=candle, role=role,
            confirmed_at_utc=candle.candle_open_time_utc + timedelta(seconds=TIMEFRAME_SECONDS["M1"]),
            algorithm_version=algorithm, parameter_version=parameters,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at_utc must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _result(stage, direction, rejection, pullback, trigger, evaluated, reasons):
        return SetupAssessment(stage, direction, rejection, pullback, trigger, evaluated, reasons)

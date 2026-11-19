from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from eurusd_ai_monitor.engines.correction_detector import CorrectionDetector
from eurusd_ai_monitor.engines.impulse_detector import ImpulseDetector
from eurusd_ai_monitor.engines.lifecycle_state_machine import LifecycleStateMachine
from eurusd_ai_monitor.engines.technical_engine import TechnicalStructure
from eurusd_ai_monitor.models.correction_lifecycle import (
    CorrectionLifecycle,
    LifecycleState,
    TransitionResult,
    TransitionType,
)
from eurusd_ai_monitor.models.price_action import TrendDirection
from eurusd_ai_monitor.storage.market_data_store import Candle


@dataclass(frozen=True)
class PriceActionCoordinatorOutput:
    """Lifecycle result with an explicit non-trading authority boundary."""

    transition: TransitionResult
    trade_authority: str = "NONE"

    def __post_init__(self) -> None:
        if not isinstance(self.transition, TransitionResult):
            raise TypeError("transition must be a TransitionResult")
        if self.trade_authority != "NONE":
            raise ValueError("PriceActionCoordinator cannot grant trade authority")


class PriceActionCoordinator:
    """Orchestrate existing PA components without duplicating analysis."""

    def __init__(
        self,
        impulse_detector: ImpulseDetector | None = None,
        correction_detector: CorrectionDetector | None = None,
        state_machine: LifecycleStateMachine | None = None,
    ) -> None:
        self._impulse_detector = impulse_detector or ImpulseDetector()
        self._correction_detector = correction_detector or CorrectionDetector()
        self._state_machine = state_machine or LifecycleStateMachine()

    def process(
        self,
        structure: TechnicalStructure,
        m5_candles: tuple[Candle, ...],
        active_lifecycle: CorrectionLifecycle | None,
        pip_size: Decimal,
        min_correction_pips: Decimal,
        max_correction_ratio: Decimal,
        expiry_bars: int = 30,
    ) -> PriceActionCoordinatorOutput:
        if not isinstance(structure, TechnicalStructure):
            raise TypeError("structure must be a TechnicalStructure")
        if not isinstance(m5_candles, tuple) or any(
            not isinstance(candle, Candle) for candle in m5_candles
        ):
            raise TypeError("m5_candles must be a tuple of Candle values")
        if active_lifecycle is not None and not isinstance(
            active_lifecycle, CorrectionLifecycle
        ):
            raise TypeError("active_lifecycle must be a CorrectionLifecycle or None")
        if not isinstance(pip_size, Decimal) or not pip_size.is_finite() or pip_size <= 0:
            raise ValueError("pip_size must be a positive finite Decimal")
        if (
            not isinstance(min_correction_pips, Decimal)
            or not min_correction_pips.is_finite()
            or min_correction_pips <= 0
        ):
            raise ValueError("min_correction_pips must be a positive finite Decimal")
        if (
            not isinstance(max_correction_ratio, Decimal)
            or not max_correction_ratio.is_finite()
            or max_correction_ratio <= 0
            or max_correction_ratio > 1
        ):
            raise ValueError("max_correction_ratio must be a Decimal in (0, 1]")
        if type(expiry_bars) is not int or expiry_bars <= 0:
            raise ValueError("expiry_bars must be a positive integer")

        if active_lifecycle is not None:
            transition = self._state_machine.advance(
                active_lifecycle,
                structure,
                m5_candles,
                expiry_bars=expiry_bars,
                max_correction_ratio=max_correction_ratio,
            )
            return PriceActionCoordinatorOutput(transition=transition)

        if structure.trend.direction not in (TrendDirection.UP, TrendDirection.DOWN):
            return self._no_candidate(structure, "NO_DIRECTIONAL_M5_TREND")

        impulse = self._impulse_detector.detect(structure, pip_size)
        if impulse is None:
            return self._no_candidate(structure, "NO_VALID_CONFIRMED_IMPULSE")

        candidate = self._correction_detector.detect_candidate(
            impulse=impulse,
            trend_direction=structure.trend.direction,
            m5_candles=m5_candles,
            evaluated_at_utc=structure.evaluated_at_utc,
            min_correction_pips=min_correction_pips,
            max_correction_ratio=max_correction_ratio,
        )
        if candidate is None:
            return self._no_candidate(structure, "NO_CORRECTION_CANDIDATE")

        transition = TransitionResult(
            transition_type=TransitionType.CREATED,
            previous_state=None,
            current_state=LifecycleState.CANDIDATE,
            lifecycle=candidate,
            occurred_at_utc=(
                candidate.last_processed_m5_utc
                + __import__("datetime").timedelta(seconds=300)
            ),
            reason_codes=("CORRECTION_THRESHOLD_REACHED",),
            evidence_refs=(
                candidate.candidate_start_evidence,
                candidate.extreme_evidence,
            ),
        )
        return PriceActionCoordinatorOutput(transition=transition)

    @staticmethod
    def _no_candidate(
        structure: TechnicalStructure,
        reason: str,
    ) -> PriceActionCoordinatorOutput:
        return PriceActionCoordinatorOutput(
            transition=TransitionResult(
                transition_type=TransitionType.NO_TRANSITION,
                previous_state=None,
                current_state=None,
                lifecycle=None,
                occurred_at_utc=structure.evaluated_at_utc,
                reason_codes=(reason,),
                evidence_refs=(),
            )
        )

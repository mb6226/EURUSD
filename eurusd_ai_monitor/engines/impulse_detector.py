from __future__ import annotations

from decimal import Decimal

from eurusd_ai_monitor.engines.technical_engine import (
    Pivot,
    PivotKind,
    TechnicalStructure,
)
from eurusd_ai_monitor.models.impulse import Impulse
from eurusd_ai_monitor.models.price_action import MovementDirection, TrendDirection


class ImpulseDetector:
    """Select the latest completed directional M5 leg from confirmed pivots.

    Pivot detection remains exclusively owned by TechnicalEngine. This class
    only normalizes consecutive same-kind pivots and constructs the last
    completed trend-aligned LOW->HIGH (UP) or HIGH->LOW (DOWN) impulse.
    """

    def detect(
        self,
        structure: TechnicalStructure,
        pip_size: Decimal,
    ) -> Impulse | None:
        if not isinstance(structure, TechnicalStructure):
            raise TypeError("structure must be a TechnicalStructure")
        if not isinstance(pip_size, Decimal):
            raise TypeError("pip_size must be a Decimal")
        if not pip_size.is_finite() or pip_size <= 0:
            raise ValueError("pip_size must be finite and greater than zero")

        direction = structure.trend.direction
        if direction not in (TrendDirection.UP, TrendDirection.DOWN):
            return None

        confirmed = tuple(
            pivot
            for pivot in structure.pivots
            if pivot.evidence.confirmed_at_utc <= structure.evaluated_at_utc
        )
        normalized = self._normalize(confirmed)
        expected = (
            (PivotKind.LOW, PivotKind.HIGH, MovementDirection.UP)
            if direction is TrendDirection.UP
            else (PivotKind.HIGH, PivotKind.LOW, MovementDirection.DOWN)
        )
        start_kind, end_kind, movement = expected

        selected: tuple[Pivot, Pivot] | None = None
        for start, end in zip(normalized, normalized[1:]):
            if start.kind is start_kind and end.kind is end_kind:
                selected = (start, end)

        if selected is None:
            return None

        start, end = selected
        start_price = start.price
        end_price = end.price
        size_pips = abs(end_price - start_price) / pip_size
        if size_pips <= 0:
            return None

        return Impulse(
            direction=movement,
            start_pivot=start.evidence,
            end_pivot=end.evidence,
            start_price=start_price,
            end_price=end_price,
            pip_size=pip_size,
            size_pips=size_pips,
            started_at_utc=start.evidence.candle.candle_open_time_utc,
            ended_at_utc=end.evidence.candle.candle_open_time_utc,
            confirmed_at_utc=end.evidence.confirmed_at_utc,
            algorithm_version=structure.algorithm_version,
            parameter_version=structure.parameter_version,
        )

    @staticmethod
    def _normalize(pivots: tuple[Pivot, ...]) -> tuple[Pivot, ...]:
        ordered = sorted(
            pivots,
            key=lambda pivot: (
                pivot.evidence.candle.candle_open_time_utc,
                pivot.evidence.confirmed_at_utc,
            ),
        )
        result: list[Pivot] = []
        for pivot in ordered:
            if not result or result[-1].kind is not pivot.kind:
                result.append(pivot)
                continue

            previous = result[-1]
            more_extreme = (
                pivot.price > previous.price
                if pivot.kind is PivotKind.HIGH
                else pivot.price < previous.price
            )
            # Equal extremes keep the older pivot deterministically.
            if more_extreme:
                result[-1] = pivot
        return tuple(result)

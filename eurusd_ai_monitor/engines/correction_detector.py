from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib

from eurusd_ai_monitor.models.correction_lifecycle import (
    CorrectionLifecycle,
    LifecycleState,
    LifecycleWarning,
)
from eurusd_ai_monitor.models.impulse import Impulse
from eurusd_ai_monitor.models.price_action import (
    EvidenceRef,
    EvidenceRole,
    MovementDirection,
    TrendDirection,
)
from eurusd_ai_monitor.storage.market_data_store import Candle, TIMEFRAME_SECONDS


_M5 = timedelta(seconds=TIMEFRAME_SECONDS["M5"])


class CorrectionDetector:
    """Find the first closed M5 candle reaching the configured correction depth.

    This detector only creates a CANDIDATE snapshot. Pivot-sequence
    confirmation, resolution, invalidation and expiry belong to the later
    lifecycle state-machine phase.
    """

    def detect_candidate(
        self,
        impulse: Impulse,
        trend_direction: TrendDirection,
        m5_candles: tuple[Candle, ...],
        evaluated_at_utc: datetime,
        min_correction_pips: Decimal,
        max_correction_ratio: Decimal,
    ) -> CorrectionLifecycle | None:
        if not isinstance(impulse, Impulse):
            raise TypeError("impulse must be an Impulse")
        if trend_direction not in (TrendDirection.UP, TrendDirection.DOWN):
            raise ValueError("trend_direction must be UP or DOWN")
        expected_direction = (
            MovementDirection.UP
            if trend_direction is TrendDirection.UP
            else MovementDirection.DOWN
        )
        if impulse.direction is not expected_direction:
            raise ValueError("impulse direction must match trend direction")
        if not isinstance(m5_candles, tuple) or any(
            not isinstance(candle, Candle) for candle in m5_candles
        ):
            raise TypeError("m5_candles must be a tuple of Candle values")
        if not isinstance(evaluated_at_utc, datetime):
            raise TypeError("evaluated_at_utc must be a datetime")
        if evaluated_at_utc.tzinfo is None or evaluated_at_utc.utcoffset() is None:
            raise ValueError("evaluated_at_utc must be timezone-aware")
        evaluated_at = evaluated_at_utc.astimezone(timezone.utc)

        for name, value in (
            ("min_correction_pips", min_correction_pips),
            ("max_correction_ratio", max_correction_ratio),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and greater than zero")

        ordered = tuple(sorted(m5_candles, key=lambda c: c.candle_open_time_utc))
        if ordered != m5_candles:
            raise ValueError("M5 candles must be chronologically ordered")
        opens = tuple(c.candle_open_time_utc for c in ordered)
        if len(opens) != len(set(opens)):
            raise ValueError("M5 candle timestamps must be unique")

        source = impulse.start_pivot.candle
        for candle in ordered:
            if candle.timeframe != "M5":
                raise ValueError("correction detection requires M5 candles")
            if candle.broker_server != source.broker_server or candle.symbol != source.symbol:
                raise ValueError("all candles must match the impulse broker and symbol")
            if candle.candle_open_time_utc + _M5 > evaluated_at:
                raise ValueError("correction detection cannot use an open candle")

        eligible = tuple(
            candle
            for candle in ordered
            if candle.candle_open_time_utc >= impulse.confirmed_at_utc
        )
        threshold = min_correction_pips * impulse.pip_size

        candidate_index: int | None = None
        for index, candle in enumerate(eligible):
            adverse_distance = (
                impulse.end_price - candle.low
                if trend_direction is TrendDirection.UP
                else candle.high - impulse.end_price
            )
            if adverse_distance >= threshold:
                candidate_index = index
                break

        if candidate_index is None:
            return None

        correction_candles = eligible[candidate_index:]
        candidate_candle = correction_candles[0]
        extreme_candle = (
            min(correction_candles, key=lambda candle: (candle.low, candle.candle_open_time_utc))
            if trend_direction is TrendDirection.UP
            else max(correction_candles, key=lambda candle: (candle.high, -candle.candle_open_time_utc.timestamp()))
        )

        def evidence(candle: Candle) -> EvidenceRef:
            return EvidenceRef(
                candle=candle,
                role=EvidenceRole.CORRECTION,
                confirmed_at_utc=candle.candle_open_time_utc + _M5,
                algorithm_version=impulse.algorithm_version,
                parameter_version=impulse.parameter_version,
            )

        depth = (
            impulse.end_price - extreme_candle.low
            if trend_direction is TrendDirection.UP
            else extreme_candle.high - impulse.end_price
        ) / impulse.pip_size
        if depth <= 0:
            return None
        ratio = depth / impulse.size_pips
        age_bars = len(correction_candles)
        warnings = (
            (LifecycleWarning.DEEP_CORRECTION,)
            if ratio > max_correction_ratio
            else ()
        )

        identity = (
            f"{impulse.impulse_id}|{evidence(candidate_candle).candle_id}"
        ).encode("utf-8")
        lifecycle_id = hashlib.sha256(identity).hexdigest()

        return CorrectionLifecycle(
            lifecycle_id=lifecycle_id,
            broker_server=source.broker_server,
            symbol=source.symbol,
            state=LifecycleState.CANDIDATE,
            trend_direction=trend_direction,
            impulse=impulse,
            candidate_start_evidence=evidence(candidate_candle),
            extreme_evidence=evidence(extreme_candle),
            depth_pips=depth,
            retracement_ratio=ratio,
            correction_pivots=(),
            confirmed_at_utc=None,
            last_processed_m5_utc=ordered[-1].candle_open_time_utc,
            age_bars=age_bars,
            warnings=warnings,
            algorithm_version=impulse.algorithm_version,
            parameter_version=impulse.parameter_version,
        )

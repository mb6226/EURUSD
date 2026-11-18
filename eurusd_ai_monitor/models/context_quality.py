from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping


def _require_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ContextQuality:
    """Quality/freshness report for a market snapshot."""

    is_valid: bool
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    last_candle_time: datetime | None = None
    data_age_seconds: float | None = None
    missing_timeframes: tuple[str, ...] = ()
    candle_counts: Mapping[str, int] | None = None
    timeframe_last_candle_times: Mapping[str, datetime | None] | None = None

    def __post_init__(self) -> None:
        if self.last_candle_time is not None:
            object.__setattr__(
                self,
                "last_candle_time",
                _require_utc(self.last_candle_time, "last_candle_time"),
            )
        if self.data_age_seconds is not None and self.data_age_seconds < 0:
            raise ValueError("data_age_seconds must be non-negative")
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "missing_timeframes", tuple(self.missing_timeframes))
        counts = dict(self.candle_counts or {})
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
            raise ValueError("candle_counts values must be non-negative integers")
        object.__setattr__(self, "candle_counts", counts)
        last_times = dict(self.timeframe_last_candle_times or {})
        for tf, value in last_times.items():
            if value is not None:
                last_times[tf] = _require_utc(value, f"timeframe_last_candle_times[{tf}]")
        object.__setattr__(self, "timeframe_last_candle_times", last_times)
        if self.is_valid and self.issues:
            raise ValueError("valid quality report cannot contain issues")

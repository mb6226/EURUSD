from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


class MacroImpact(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class MacroEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    TENTATIVE = "TENTATIVE"
    CANCELLED = "CANCELLED"
    RELEASED = "RELEASED"
    UNKNOWN = "UNKNOWN"


def _aware_utc(value: datetime | None, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{name} must be normalized to UTC")


def _decimal(value: Decimal | None, name: str) -> None:
    if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
        raise ValueError(f"{name} must be a finite Decimal or None")


@dataclass(frozen=True)
class MacroEvent:
    event_id: str
    source_id: str
    source_name: str
    source_url: str
    source_event_id: str
    title: str
    description: str
    currency_codes: tuple[str, ...]
    category: str
    impact: MacroImpact
    impact_reason: str
    scheduled_date: date
    scheduled_at_utc: datetime | None
    source_timezone: str
    status: MacroEventStatus
    reference_period: str | None = None
    actual: Decimal | None = None
    forecast: Decimal | None = None
    previous: Decimal | None = None
    result_unit: str | None = None
    source_updated_at_utc: datetime | None = None
    retrieved_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "event_id", "source_id", "source_name", "source_url",
            "source_event_id", "title", "source_timezone", "category",
            "impact_reason",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("source_url must be an absolute HTTP(S) URL")
        if not isinstance(self.scheduled_date, date) or isinstance(self.scheduled_date, datetime):
            raise TypeError("scheduled_date must be a date")
        if not isinstance(self.currency_codes, tuple) or not self.currency_codes:
            raise ValueError("currency_codes must be a non-empty tuple")
        if any(code not in {"EUR", "USD", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"} for code in self.currency_codes):
            raise ValueError("currency_codes contains an unsupported ISO currency code")
        if not isinstance(self.impact, MacroImpact):
            raise TypeError("impact must be MacroImpact")
        if not isinstance(self.status, MacroEventStatus):
            raise TypeError("status must be MacroEventStatus")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        if self.scheduled_at_utc is not None:
            _aware_utc(self.scheduled_at_utc, "scheduled_at_utc")
        _aware_utc(self.source_updated_at_utc, "source_updated_at_utc")
        _aware_utc(self.retrieved_at_utc, "retrieved_at_utc")
        for name in ("actual", "forecast", "previous"):
            _decimal(getattr(self, name), name)
        if self.result_unit is not None and not isinstance(self.result_unit, str):
            raise TypeError("result_unit must be a string or None")

    def to_dict(self, include_retrieved_at: bool = True) -> dict[str, Any]:
        def stamp(value: datetime | None) -> str | None:
            return value.isoformat().replace("+00:00", "Z") if value is not None else None

        result = {
            "event_id": self.event_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_event_id": self.source_event_id,
            "title": self.title,
            "description": self.description,
            "currency_codes": list(self.currency_codes),
            "category": self.category,
            "impact": self.impact.value,
            "impact_reason": self.impact_reason,
            "scheduled_date": self.scheduled_date.isoformat(),
            "scheduled_at_utc": stamp(self.scheduled_at_utc),
            "source_timezone": self.source_timezone,
            "status": self.status.value,
            "reference_period": self.reference_period,
            "actual": str(self.actual) if self.actual is not None else None,
            "forecast": str(self.forecast) if self.forecast is not None else None,
            "previous": str(self.previous) if self.previous is not None else None,
            "result_unit": self.result_unit,
            "source_updated_at_utc": stamp(self.source_updated_at_utc),
        }
        if include_retrieved_at:
            result["retrieved_at_utc"] = stamp(self.retrieved_at_utc)
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MacroEvent":
        def parse_stamp(value: str | None) -> datetime | None:
            if value is None:
                return None
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

        return cls(
            event_id=payload["event_id"],
            source_id=payload["source_id"],
            source_name=payload["source_name"],
            source_url=payload["source_url"],
            source_event_id=payload["source_event_id"],
            title=payload["title"],
            description=payload.get("description", ""),
            currency_codes=tuple(payload["currency_codes"]),
            category=payload["category"],
            impact=MacroImpact(payload["impact"]),
            impact_reason=payload["impact_reason"],
            scheduled_date=date.fromisoformat(payload["scheduled_date"]),
            scheduled_at_utc=parse_stamp(payload.get("scheduled_at_utc")),
            source_timezone=payload["source_timezone"],
            status=MacroEventStatus(payload["status"]),
            reference_period=payload.get("reference_period"),
            actual=Decimal(payload["actual"]) if payload.get("actual") is not None else None,
            forecast=Decimal(payload["forecast"]) if payload.get("forecast") is not None else None,
            previous=Decimal(payload["previous"]) if payload.get("previous") is not None else None,
            result_unit=payload.get("result_unit"),
            source_updated_at_utc=parse_stamp(payload.get("source_updated_at_utc")),
            retrieved_at_utc=parse_stamp(payload.get("retrieved_at_utc")),
        )

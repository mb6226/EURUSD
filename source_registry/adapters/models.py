from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _utc_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _datetime_to_json(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decimal_to_json(value: Decimal) -> str:
    return format(value, "f")


def _validate_decimal(value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError("Economic values must be Decimal")
    if not value.is_finite():
        raise ValueError("Economic values must be finite")


def _validate_utc_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field_name} must be normalized to UTC")


@dataclass(frozen=True)
class DecimalRange:
    low: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        _validate_decimal(self.low)
        _validate_decimal(self.high)
        if self.low > self.high:
            raise ValueError("DecimalRange.low must not exceed DecimalRange.high")

    def to_dict(self) -> dict[str, str]:
        return {
            "low": _decimal_to_json(self.low),
            "high": _decimal_to_json(self.high),
        }


@dataclass(frozen=True)
class FetchRequest:
    source_id: str
    product_id: str
    since: datetime | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.source_id, "source_id")
        _require_identifier(self.product_id, "product_id")
        if self.since is not None:
            object.__setattr__(
                self,
                "since",
                _utc_datetime(self.since, "since"),
            )


@dataclass(frozen=True)
class Observation:
    source_id: str
    product_id: str
    value: Decimal | DecimalRange
    unit: str
    effective_at_utc: datetime
    published_at_utc: datetime | None
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "effective_at_utc",
            _utc_datetime(self.effective_at_utc, "effective_at_utc"),
        )
        if self.published_at_utc is not None:
            object.__setattr__(
                self,
                "published_at_utc",
                _utc_datetime(self.published_at_utc, "published_at_utc"),
            )
        self.validate()

    def validate(self) -> None:
        _require_identifier(self.source_id, "source_id")
        _require_identifier(self.product_id, "product_id")
        _require_identifier(self.unit, "unit")
        if isinstance(self.value, DecimalRange):
            self.value.validate()
        else:
            _validate_decimal(self.value)
        _validate_utc_datetime(self.effective_at_utc, "effective_at_utc")
        if self.published_at_utc is not None:
            _validate_utc_datetime(self.published_at_utc, "published_at_utc")
        if self.source_record_id is not None:
            _require_identifier(self.source_record_id, "source_record_id")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "source_id": self.source_id,
            "product_id": self.product_id,
            "value": (
                self.value.to_dict()
                if isinstance(self.value, DecimalRange)
                else _decimal_to_json(self.value)
            ),
            "unit": self.unit,
            "effective_at_utc": _datetime_to_json(self.effective_at_utc),
            "published_at_utc": (
                _datetime_to_json(self.published_at_utc)
                if self.published_at_utc is not None
                else None
            ),
            "source_record_id": self.source_record_id,
        }


@dataclass(frozen=True)
class FetchResult:
    source_id: str
    product_id: str
    observations: tuple[Observation, ...]
    source_url: str
    record_count: int
    retrieved_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        if self.retrieved_at_utc is not None:
            object.__setattr__(
                self,
                "retrieved_at_utc",
                _utc_datetime(self.retrieved_at_utc, "retrieved_at_utc"),
            )
        self.validate()

    def validate(self, require_retrieved_at: bool = False) -> None:
        _require_identifier(self.source_id, "source_id")
        _require_identifier(self.product_id, "product_id")
        if not isinstance(self.observations, tuple):
            raise TypeError("observations must be a tuple")
        if any(not isinstance(item, Observation) for item in self.observations):
            raise TypeError("observations must contain only Observation values")
        if self.retrieved_at_utc is None:
            if require_retrieved_at:
                raise ValueError(
                    "retrieved_at_utc must be set by the execution layer before serialization"
                )
        else:
            _validate_utc_datetime(self.retrieved_at_utc, "retrieved_at_utc")
        if not isinstance(self.source_url, str) or not self.source_url.strip():
            raise ValueError("source_url must be a non-empty URL")
        parsed_url = urlsplit(self.source_url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError("source_url must be an absolute HTTP or HTTPS URL")
        if isinstance(self.record_count, bool) or not isinstance(
            self.record_count, int
        ):
            raise TypeError("record_count must be an integer")
        if self.record_count != len(self.observations):
            raise ValueError("record_count must match the number of observations")

        seen_records: set[tuple[object, ...]] = set()
        for observation in self.observations:
            observation.validate()
            if (
                observation.source_id != self.source_id
                or observation.product_id != self.product_id
            ):
                raise ValueError(
                    "Each observation must match the result source_id and product_id"
                )
            identity = (
                ("source_record_id", observation.source_record_id)
                if observation.source_record_id is not None
                else (
                    "natural_key",
                    observation.effective_at_utc,
                    observation.published_at_utc,
                    observation.value,
                    observation.unit,
                )
            )
            if identity in seen_records:
                raise ValueError("FetchResult contains a duplicate observation")
            seen_records.add(identity)

    def with_retrieved_at(self, retrieved_at_utc: datetime) -> FetchResult:
        """Return a result stamped by the execution layer after fetching."""
        return replace(
            self,
            retrieved_at_utc=_utc_datetime(
                retrieved_at_utc,
                "retrieved_at_utc",
            ),
        )

    def to_dict(self) -> dict[str, object]:
        self.validate(require_retrieved_at=True)
        if self.retrieved_at_utc is None:
            raise ValueError("retrieved_at_utc is required for serialization")
        return {
            "source_id": self.source_id,
            "product_id": self.product_id,
            "observations": [
                observation.to_dict() for observation in self.observations
            ],
            "retrieved_at_utc": _datetime_to_json(self.retrieved_at_utc),
            "source_url": self.source_url,
            "record_count": self.record_count,
        }

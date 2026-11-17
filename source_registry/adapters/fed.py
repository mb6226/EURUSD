from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import FetchAdapter
from .exceptions import FetchParseError, FetchValidationError
from .models import DecimalRange, FetchRequest, FetchResult, Observation

FED_SOURCE_ID = "FED_FOMC_POLICY"
FED_TARGET_RANGE_PRODUCT_ID = "FED_TARGET_RANGE"
FED_OPEN_MARKET_URL = (
    "https://www.federalreserve.gov/monetarypolicy/openmarket.htm"
)

RawRecord = Mapping[str, Any]
RecordsProvider = Callable[[FetchRequest], Iterable[RawRecord]]


class FedAdapter(FetchAdapter):
    """Normalize extracted Fed target-range rows without performing I/O."""

    def __init__(self, records_provider: RecordsProvider) -> None:
        if not callable(records_provider):
            raise TypeError("records_provider must be callable")
        self._records_provider = records_provider

    def fetch(self, request: FetchRequest) -> FetchResult:
        if request.source_id != FED_SOURCE_ID:
            raise FetchValidationError(
                f"FedAdapter does not support source {request.source_id!r}"
            )
        if request.product_id != FED_TARGET_RANGE_PRODUCT_ID:
            raise FetchValidationError(
                f"FedAdapter does not support product {request.product_id!r}"
            )

        records = self._parse(self._records_provider(request))
        if not records and request.since is None:
            raise FetchValidationError(
                "Fed full-history response contains no target-range records"
            )

        normalized = [self._normalize(record) for record in records]
        ranges_by_effective_at: dict[datetime, DecimalRange] = {}
        for observation in normalized:
            if not isinstance(observation.value, DecimalRange):
                raise FetchValidationError(
                    "Fed target-range observation must contain DecimalRange"
                )
            previous = ranges_by_effective_at.get(
                observation.effective_at_utc
            )
            if previous is not None:
                if previous != observation.value:
                    raise FetchValidationError(
                        "Conflicting Fed target ranges for effective date "
                        f"{observation.effective_at_utc.date().isoformat()}"
                    )
                raise FetchValidationError(
                    "Duplicate Fed target-range record for effective date "
                    f"{observation.effective_at_utc.date().isoformat()}"
                )
            ranges_by_effective_at[observation.effective_at_utc] = (
                observation.value
            )

        observations = tuple(
            sorted(
                normalized,
                key=lambda observation: observation.effective_at_utc,
            )
        )
        return FetchResult(
            source_id=FED_SOURCE_ID,
            product_id=FED_TARGET_RANGE_PRODUCT_ID,
            observations=observations,
            source_url=FED_OPEN_MARKET_URL,
            record_count=len(observations),
        )

    @staticmethod
    def _parse(raw_records: Iterable[RawRecord]) -> list[RawRecord]:
        if isinstance(raw_records, (str, bytes, Mapping)):
            raise FetchParseError("Fed records must be an iterable of record objects")
        try:
            iterator = iter(raw_records)
        except TypeError as exc:
            raise FetchParseError(
                "Fed records must be an iterable of record objects"
            ) from exc

        records: list[RawRecord] = []
        required_fields = {"effective_date", "lower_bound", "upper_bound"}
        for index, record in enumerate(iterator):
            if not isinstance(record, Mapping):
                raise FetchParseError(f"Fed record {index} must be an object")
            missing = required_fields.difference(record)
            if missing:
                raise FetchParseError(
                    f"Fed record {index} is missing fields: "
                    + ", ".join(sorted(missing))
                )
            records.append(record)
        return records

    @staticmethod
    def _decimal(value: object, field_name: str) -> Decimal:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, str):
            try:
                result = Decimal(value)
            except InvalidOperation as exc:
                raise FetchValidationError(
                    f"Fed field {field_name} is not a valid decimal string"
                ) from exc
        else:
            raise FetchValidationError(
                f"Fed field {field_name} must be a Decimal or decimal string"
            )

        if not result.is_finite():
            raise FetchValidationError(
                f"Fed field {field_name} must be a finite decimal"
            )
        return result

    @staticmethod
    def _effective_at(value: object) -> datetime:
        if isinstance(value, datetime):
            raise FetchValidationError(
                "Fed effective_date must be a calendar date, not a datetime"
            )
        if isinstance(value, date):
            effective_date = value
        elif isinstance(value, str):
            try:
                effective_date = date.fromisoformat(value)
            except ValueError as exc:
                raise FetchValidationError(
                    "Fed effective_date must use YYYY-MM-DD format"
                ) from exc
        else:
            raise FetchValidationError(
                "Fed effective_date must be a date or YYYY-MM-DD string"
            )
        return datetime.combine(
            effective_date,
            time.min,
            tzinfo=timezone.utc,
        )

    @staticmethod
    def _published_at(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise FetchValidationError(
                    "Fed published_at_utc must be timezone-aware"
                )
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            try:
                published_at = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise FetchValidationError(
                    "Fed published_at_utc must be an ISO 8601 timestamp"
                ) from exc
            if published_at.tzinfo is None or published_at.utcoffset() is None:
                raise FetchValidationError(
                    "Fed published_at_utc must be timezone-aware"
                )
            return published_at.astimezone(timezone.utc)
        raise FetchValidationError(
            "Fed published_at_utc must be an ISO timestamp or null"
        )

    @classmethod
    def _normalize(cls, record: RawRecord) -> Observation:
        try:
            value = DecimalRange(
                low=cls._decimal(record["lower_bound"], "lower_bound"),
                high=cls._decimal(record["upper_bound"], "upper_bound"),
            )
            effective_at = cls._effective_at(record["effective_date"])
            published_at = cls._published_at(
                record.get("published_at_utc")
            )
            source_record_id = record.get("source_record_id")
            if source_record_id is not None and not isinstance(
                source_record_id, str
            ):
                raise FetchValidationError(
                    "Fed source_record_id must be a string or null"
                )
            return Observation(
                source_id=FED_SOURCE_ID,
                product_id=FED_TARGET_RANGE_PRODUCT_ID,
                value=value,
                unit="percent_per_annum",
                effective_at_utc=effective_at,
                published_at_utc=published_at,
                source_record_id=source_record_id,
            )
        except KeyError as exc:
            raise FetchParseError(
                f"Fed record is missing field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            if isinstance(exc, FetchValidationError):
                raise
            raise FetchValidationError(
                f"Invalid Fed target range record: {exc}"
            ) from exc

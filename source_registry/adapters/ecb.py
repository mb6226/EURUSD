from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import FetchAdapter
from .exceptions import FetchParseError, FetchValidationError
from .models import FetchRequest, FetchResult, Observation

ECB_SOURCE_ID = "ECB_POLICY_RATES"
ECB_POLICY_RATES_URL = (
    "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
    "key_ecb_interest_rates/html/index.en.html"
)
ECB_PRODUCT_UNITS = {
    "ECB_DEPOSIT_FACILITY_RATE": "deposit_facility_rate",
    "ECB_MAIN_REFINANCING_RATE": "main_refinancing_rate",
    "ECB_MARGINAL_LENDING_RATE": "marginal_lending_rate",
}

RawRecord = Mapping[str, Any]
RecordsProvider = Callable[[FetchRequest], Iterable[RawRecord]]


class ECBPolicyRateAdapter(FetchAdapter):
    """Normalize one ECB policy-rate series from extracted official records.

    Transport and HTML/table extraction are deliberately injected. This class
    validates and normalizes records; it does not fetch or scrape the website.
    One instance is bound to exactly one registered ECB product.
    """

    def __init__(self, product_id: str, records_provider: RecordsProvider) -> None:
        if product_id not in ECB_PRODUCT_UNITS:
            raise FetchValidationError(
                f"Unsupported ECB policy-rate product: {product_id!r}"
            )
        if not callable(records_provider):
            raise TypeError("records_provider must be callable")
        self.product_id = product_id
        self._records_provider = records_provider

    def fetch(self, request: FetchRequest) -> FetchResult:
        if request.source_id != ECB_SOURCE_ID:
            raise FetchValidationError(
                f"ECB adapter does not support source {request.source_id!r}"
            )
        if request.product_id != self.product_id:
            raise FetchValidationError(
                f"ECB adapter for {self.product_id!r} does not support "
                f"product {request.product_id!r}"
            )

        raw_records = self._parse(self._records_provider(request))
        if not raw_records and request.since is None:
            raise FetchValidationError(
                "ECB full-history response contains no policy-rate records"
            )

        normalized = [self._normalize(record) for record in raw_records]
        by_effective: dict[datetime, Observation] = {}
        for observation in normalized:
            previous = by_effective.get(observation.effective_at_utc)
            if previous is not None:
                if previous.value != observation.value:
                    raise FetchValidationError(
                        "Conflicting ECB policy rates for effective date "
                        f"{observation.effective_at_utc.date().isoformat()}"
                    )
                raise FetchValidationError(
                    "Duplicate ECB policy-rate record for effective date "
                    f"{observation.effective_at_utc.date().isoformat()}"
                )
            by_effective[observation.effective_at_utc] = observation

        observations = tuple(
            sorted(normalized, key=lambda item: item.effective_at_utc)
        )
        return FetchResult(
            source_id=ECB_SOURCE_ID,
            product_id=self.product_id,
            observations=observations,
            source_url=ECB_POLICY_RATES_URL,
            record_count=len(observations),
        )

    @staticmethod
    def _parse(records: Iterable[RawRecord]) -> list[RawRecord]:
        if isinstance(records, (str, bytes, Mapping)):
            raise FetchParseError(
                "ECB records must be an iterable of record objects"
            )
        try:
            iterator = iter(records)
        except TypeError as exc:
            raise FetchParseError(
                "ECB records must be an iterable of record objects"
            ) from exc

        parsed: list[RawRecord] = []
        required = {"effective_date", "rate"}
        for index, record in enumerate(iterator):
            if not isinstance(record, Mapping):
                raise FetchParseError(f"ECB record {index} must be an object")
            missing = required.difference(record)
            if missing:
                raise FetchParseError(
                    f"ECB record {index} is missing fields: "
                    + ", ".join(sorted(missing))
                )
            parsed.append(record)
        return parsed

    @staticmethod
    def _decimal(value: object) -> Decimal:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, str):
            try:
                result = Decimal(value.strip())
            except InvalidOperation as exc:
                raise FetchValidationError(
                    "ECB rate must be a valid decimal string"
                ) from exc
        else:
            raise FetchValidationError(
                "ECB rate must be a Decimal or decimal string"
            )
        if not result.is_finite():
            raise FetchValidationError("ECB rate must be finite")
        return result

    @staticmethod
    def _effective_at(value: object) -> datetime:
        if isinstance(value, datetime):
            raise FetchValidationError(
                "ECB effective_date must be a calendar date, not a datetime"
            )
        if isinstance(value, date):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise FetchValidationError(
                    "ECB effective_date must use YYYY-MM-DD format"
                ) from exc
        else:
            raise FetchValidationError(
                "ECB effective_date must be a date or YYYY-MM-DD string"
            )
        return datetime.combine(parsed, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _published_at(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise FetchValidationError(
                    "ECB published_at_utc must be an ISO 8601 timestamp"
                ) from exc
        else:
            raise FetchValidationError(
                "ECB published_at_utc must be an ISO timestamp or null"
            )
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise FetchValidationError(
                "ECB published_at_utc must be timezone-aware"
            )
        return parsed.astimezone(timezone.utc)

    def _normalize(self, record: RawRecord) -> Observation:
        try:
            source_record_id = record.get("source_record_id")
            if source_record_id is not None and not isinstance(
                source_record_id, str
            ):
                raise FetchValidationError(
                    "ECB source_record_id must be a string or null"
                )
            return Observation(
                source_id=ECB_SOURCE_ID,
                product_id=self.product_id,
                value=self._decimal(record["rate"]),
                unit="percent_per_annum",
                effective_at_utc=self._effective_at(record["effective_date"]),
                published_at_utc=self._published_at(
                    record.get("published_at_utc")
                ),
                source_record_id=source_record_id,
            )
        except KeyError as exc:
            raise FetchParseError(
                f"ECB record is missing field: {exc.args[0]}"
            ) from exc

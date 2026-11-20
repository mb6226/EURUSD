from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from .base import FetchAdapter
from .exceptions import FetchParseError, FetchValidationError
from .models import FetchRequest, FetchResult, Observation

US_BLS_SOURCE_ID = "US_BLS_MACRO"
EUROSTAT_SOURCE_ID = "EUROSTAT_MACRO"

MACRO_SERIES_UNITS = {
    (US_BLS_SOURCE_ID, "US_CPI_ALL_ITEMS_INDEX"): "index_1982_84_100",
    (US_BLS_SOURCE_ID, "US_UNEMPLOYMENT_RATE"): "percent_of_labor_force",
    (EUROSTAT_SOURCE_ID, "EA_HICP_ALL_ITEMS_INDEX"): "index_2015_100",
    (EUROSTAT_SOURCE_ID, "EA_UNEMPLOYMENT_RATE"): "percent_of_labor_force",
}
MACRO_SERIES_URLS = {
    US_BLS_SOURCE_ID: "https://api.bls.gov/publicAPI/v1/timeseries/data/",
    EUROSTAT_SOURCE_ID: "https://ec.europa.eu/eurostat/data/database",
}

RawRecord = Mapping[str, Any]
RecordsProvider = Callable[[FetchRequest], Iterable[RawRecord]]
_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class OfficialMacroSeriesAdapter(FetchAdapter):
    """Normalize extracted official monthly macro series; transport is injected.

    Each instance is bound to one registered source/product. Records must carry
    the actual publication timestamp; retrieval time is stamped downstream by
    SourceObservationIngestion. A stable record id is generated from product
    and reference month when the provider does not supply one, allowing later
    revisions of the same month to append as new point-in-time versions.
    """

    def __init__(
        self,
        *,
        source_id: str,
        product_id: str,
        records_provider: RecordsProvider,
    ) -> None:
        identity = (source_id, product_id)
        if identity not in MACRO_SERIES_UNITS:
            raise FetchValidationError(f"Unsupported official macro series: {identity!r}")
        if not callable(records_provider):
            raise TypeError("records_provider must be callable")
        self.source_id = source_id
        self.product_id = product_id
        self.unit = MACRO_SERIES_UNITS[identity]
        self._provider = records_provider

    def fetch(self, request: FetchRequest) -> FetchResult:
        if (request.source_id, request.product_id) != (self.source_id, self.product_id):
            raise FetchValidationError("Macro adapter source/product does not match request")
        raw_records = self._parse(self._provider(request))
        normalized = [self._normalize(record) for record in raw_records]
        by_period: dict[datetime, Observation] = {}
        for observation in normalized:
            previous = by_period.get(observation.effective_at_utc)
            if previous is not None:
                raise FetchValidationError(
                    "Duplicate macro record for reference month "
                    f"{observation.effective_at_utc.strftime('%Y-%m')}"
                )
            by_period[observation.effective_at_utc] = observation

        if request.since is not None:
            normalized = [
                item for item in normalized if item.effective_at_utc >= request.since
            ]
        if not normalized and request.since is None:
            raise FetchValidationError("Official macro full-history response is empty")

        observations = tuple(sorted(normalized, key=lambda item: item.effective_at_utc))
        return FetchResult(
            source_id=self.source_id,
            product_id=self.product_id,
            observations=observations,
            source_url=MACRO_SERIES_URLS[self.source_id],
            record_count=len(observations),
        )

    @staticmethod
    def _parse(records: Iterable[RawRecord]) -> list[RawRecord]:
        if isinstance(records, (str, bytes, Mapping)):
            raise FetchParseError("Macro records must be an iterable of record objects")
        try:
            iterator = iter(records)
        except TypeError as exc:
            raise FetchParseError("Macro records must be iterable") from exc
        parsed = []
        for index, record in enumerate(iterator):
            if not isinstance(record, Mapping):
                raise FetchParseError(f"Macro record {index} must be an object")
            missing = {"reference_period", "value", "published_at_utc"}.difference(record)
            if missing:
                raise FetchParseError(
                    f"Macro record {index} is missing fields: {', '.join(sorted(missing))}"
                )
            parsed.append(record)
        return parsed

    @staticmethod
    def _decimal(value: object) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
            raise FetchValidationError("Macro value must be a decimal string, Decimal, or integer")
        try:
            parsed = value if isinstance(value, Decimal) else Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise FetchValidationError("Macro value is not a valid decimal") from exc
        if not parsed.is_finite():
            raise FetchValidationError("Macro value must be finite")
        return parsed

    @staticmethod
    def _period(value: object) -> datetime:
        if not isinstance(value, str) or not _PERIOD.fullmatch(value):
            raise FetchValidationError("reference_period must use YYYY-MM format")
        try:
            parsed = datetime.strptime(value, "%Y-%m")
        except ValueError as exc:
            raise FetchValidationError("reference_period is invalid") from exc
        return parsed.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    @staticmethod
    def _published(value: object) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise FetchValidationError("published_at_utc must be ISO-8601") from exc
        else:
            raise FetchValidationError("published_at_utc must be a timezone-aware timestamp")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise FetchValidationError("published_at_utc must be timezone-aware")
        return parsed.astimezone(timezone.utc)

    def _normalize(self, record: RawRecord) -> Observation:
        period = self._period(record["reference_period"])
        published = self._published(record["published_at_utc"])
        if published < period:
            raise FetchValidationError("published_at_utc cannot precede the reference month")
        provider_record_id = record.get("source_record_id")
        if provider_record_id is not None and (
            not isinstance(provider_record_id, str) or not provider_record_id.strip()
        ):
            raise FetchValidationError("source_record_id must be a non-empty string")
        # The canonical observation identity must remain stable across revisions.
        source_record_id = f"{self.product_id}:{period.strftime('%Y-%m')}"
        return Observation(
            source_id=self.source_id,
            product_id=self.product_id,
            value=self._decimal(record["value"]),
            unit=self.unit,
            effective_at_utc=period,
            published_at_utc=published,
            source_record_id=source_record_id,
        )

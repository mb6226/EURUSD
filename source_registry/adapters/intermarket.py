from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import FetchAdapter
from .exceptions import FetchParseError, FetchValidationError
from .models import FetchRequest, FetchResult, Observation

# Logical products are deliberately separated from provider-specific series IDs.
# A provider/parser must be injected; this module performs no network I/O.
INTERMARKET_PRODUCTS = {
    ("FRED_INTERMARKET", "US_10Y_TREASURY_YIELD"): "percent_per_annum",
    ("FRED_INTERMARKET", "USD_BROAD_TRADE_WEIGHTED_INDEX"): "index_points",
    ("FRED_INTERMARKET", "SP500_INDEX"): "index_points",
    ("ECB_INTERMARKET", "DE_10Y_GOVERNMENT_YIELD"): "percent_per_annum",
    ("LBMA_INTERMARKET", "GOLD_USD_TROY_OUNCE"): "usd_per_troy_ounce",
    ("BROKER_SPOT_REFERENCE", "EURUSD_SPOT_REFERENCE"): "usd_per_eur",
}
INTERMARKET_SOURCE_URLS = {
    "FRED_INTERMARKET": "https://fred.stlouisfed.org/",
    "ECB_INTERMARKET": "https://data.ecb.europa.eu/",
    "LBMA_INTERMARKET": "https://www.lbma.org.uk/prices-and-data/precious-metal-prices",
    "BROKER_SPOT_REFERENCE": "https://www.metatrader5.com/",
}
RawRecord = Mapping[str, Any]
RecordsProvider = Callable[[FetchRequest], Iterable[RawRecord]]


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise FetchValidationError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FetchValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FetchValidationError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise FetchValidationError("intermarket value must be a decimal scalar")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FetchValidationError("intermarket value must be a valid decimal") from exc
    if not result.is_finite():
        raise FetchValidationError("intermarket value must be finite")
    return result


class IntermarketSeriesAdapter(FetchAdapter):
    """Normalize manually extracted market observations into the shared contract.

    Required fields: observed_at_utc, published_at_utc, value. Publication time
    must be the actual time the observation became available, not retrieval time.
    Retrieval is stamped later by SourceObservationIngestion.
    """

    def __init__(
        self, *, source_id: str, product_id: str,
        records_provider: RecordsProvider,
    ) -> None:
        identity = (source_id, product_id)
        if identity not in INTERMARKET_PRODUCTS:
            raise FetchValidationError(f"Unsupported intermarket series: {identity!r}")
        if not callable(records_provider):
            raise TypeError("records_provider must be callable")
        self.source_id = source_id
        self.product_id = product_id
        self.unit = INTERMARKET_PRODUCTS[identity]
        self._provider = records_provider

    def fetch(self, request: FetchRequest) -> FetchResult:
        if (request.source_id, request.product_id) != (self.source_id, self.product_id):
            raise FetchValidationError("Intermarket adapter identity does not match request")
        records = self._provider(request)
        if isinstance(records, (str, bytes, Mapping)):
            raise FetchParseError("Intermarket records must be an iterable of objects")
        try:
            iterator = iter(records)
        except TypeError as exc:
            raise FetchParseError("Intermarket records must be iterable") from exc

        normalized: dict[datetime, Observation] = {}
        for index, record in enumerate(iterator):
            if not isinstance(record, Mapping):
                raise FetchParseError(f"Intermarket record {index} must be an object")
            observed = _timestamp(record.get("observed_at_utc"), "observed_at_utc")
            published = _timestamp(record.get("published_at_utc"), "published_at_utc")
            if published < observed:
                raise FetchValidationError("published_at_utc cannot precede observed_at_utc")
            value = _decimal(record.get("value"))
            record_id = f"{self.product_id}|{observed.isoformat().replace('+00:00', 'Z')}"
            observation = Observation(
                source_id=self.source_id,
                product_id=self.product_id,
                value=value,
                unit=self.unit,
                effective_at_utc=observed,
                published_at_utc=published,
                source_record_id=record_id,
            )
            if observed in normalized:
                raise FetchValidationError(
                    f"Duplicate intermarket observation timestamp: {observed.isoformat()}"
                )
            normalized[observed] = observation

        if request.since is not None:
            normalized = {
                at: item for at, item in normalized.items() if at >= request.since
            }
        if not normalized and request.since is None:
            raise FetchValidationError("Intermarket full-history response is empty")

        observations = tuple(normalized[key] for key in sorted(normalized))
        return FetchResult(
            source_id=self.source_id,
            product_id=self.product_id,
            observations=observations,
            source_url=INTERMARKET_SOURCE_URLS[self.source_id],
            record_count=len(observations),
        )

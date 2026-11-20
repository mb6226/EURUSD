from __future__ import annotations

"""FRED/ALFRED vintage acquisition. Date-grain only; never invent intraday release times."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Callable
from urllib.parse import urlencode

from source_registry.adapters.exceptions import FetchParseError, FetchValidationError
from source_registry.raw_archive import RawSnapshotArchive
from .bls import HTTPResponse

SOURCE_ID = "FRED_INTERMARKET"
API_URL = "https://api.stlouisfed.org/fred/series/observations"
SERIES_BY_PRODUCT = {
    "US_2Y_TREASURY_YIELD": "DGS2",
    "US_10Y_TREASURY_YIELD": "DGS10",
    "US_10Y_REAL_TREASURY_YIELD": "DFII10",
    "USD_BROAD_TRADE_WEIGHTED_INDEX": "DTWEXBGS",
    "SP500_INDEX": "SP500",
    "US_VIX_CLOSE": "VIXCLS",
    "WTI_CRUDE_OIL_PRICE": "DCOILWTICO",
    "BRENT_CRUDE_OIL_PRICE": "DCOILBRENTEU",
    "EURUSD_DAILY_REFERENCE_RATE": "DEXUSEU",
}
UTC = timezone.utc


class FREDALFREDVintageProvider:
    """Archive ALFRED output_type=2, retaining realtime_start/end per vintage.

    API key is passed explicitly by the caller. No environment variables are read.
    Returned records are not Observation objects: FRED vintage boundaries are
    date-grained, not verified intraday publication timestamps.
    """
    def __init__(self, *, transport: Any, archive: RawSnapshotArchive,
                 api_key: str, clock: Callable[[], datetime] | None = None,
                 observation_start: str = "2000-01-01", observation_end: str = "9999-12-31"):
        if not callable(getattr(transport, "request", None)):
            raise TypeError("transport must provide request(method, url, ...)")
        if not isinstance(archive, RawSnapshotArchive):
            raise TypeError("archive must be a RawSnapshotArchive")
        if not isinstance(api_key, str) or len(api_key.strip()) != 32:
            raise ValueError("a 32-character FRED API key must be explicitly supplied")
        for value in (observation_start, observation_end):
            datetime.strptime(value, "%Y-%m-%d")
        if observation_start > observation_end:
            raise ValueError("observation_start must not exceed observation_end")
        self.transport, self.archive, self.api_key = transport, archive, api_key
        self.clock = clock or (lambda: datetime.now(UTC))
        self.observation_start, self.observation_end = observation_start, observation_end

    def acquire(self, product_id: str, *, realtime_start: str, realtime_end: str) -> dict[str, Any]:
        if product_id not in SERIES_BY_PRODUCT:
            raise FetchValidationError(f"Unsupported FRED product: {product_id}")
        start = datetime.strptime(realtime_start, "%Y-%m-%d").date()
        end = datetime.strptime(realtime_end, "%Y-%m-%d").date()
        if start > end:
            raise ValueError("realtime_start must not exceed realtime_end")
        series_id = SERIES_BY_PRODUCT[product_id]
        params = {"series_id": series_id, "api_key": self.api_key, "file_type": "json",
                  "output_type": "2", "sort_order": "asc", "limit": "100000",
                  "observation_start": self.observation_start, "observation_end": self.observation_end,
                  "realtime_start": realtime_start, "realtime_end": realtime_end}
        url = API_URL + "?" + urlencode(params)
        response = self.transport.request("GET", url, headers={"Accept": "application/json"})
        if response.status != 200:
            raise FetchValidationError(f"FRED API returned HTTP {response.status}")
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("provider clock must be timezone-aware")
        safe_url = API_URL + "?" + urlencode({k: v for k, v in params.items() if k != "api_key"})
        snapshot = self.archive.append(source_id=SOURCE_ID, product_id=product_id,
            source_url=safe_url, retrieved_at_utc=now.astimezone(UTC), http_status=response.status,
            content_type=response.content_type, payload=response.body, response_headers=response.headers,
            request_metadata={"provider": "FRED_ALFRED", "series_id": series_id,
                "output_type": 2, "realtime_start": realtime_start, "realtime_end": realtime_end,
                "observation_start": self.observation_start, "observation_end": self.observation_end})
        try:
            document = json.loads(response.body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchParseError("FRED response is not valid JSON") from exc
        if "error_code" in document:
            raise FetchValidationError("FRED API error: " + str(document.get("error_message", document["error_code"])))
        rows = document.get("observations")
        if not isinstance(rows, list):
            raise FetchParseError("FRED response has no observations array")
        output = []
        for row in rows:
            if not isinstance(row, dict):
                raise FetchParseError("FRED observation must be an object")
            try:
                period = datetime.strptime(row["date"], "%Y-%m-%d").date()
                vintage_from = datetime.strptime(row["realtime_start"], "%Y-%m-%d").date()
                vintage_to = datetime.strptime(row["realtime_end"], "%Y-%m-%d").date()
            except (KeyError, TypeError, ValueError) as exc:
                raise FetchParseError("FRED vintage row has invalid date fields") from exc
            if vintage_from > vintage_to:
                raise FetchValidationError("FRED vintage interval is inverted")
            raw_value = row.get("value")
            if raw_value == ".":
                value = None
            else:
                try:
                    value = Decimal(str(raw_value))
                except (InvalidOperation, ValueError) as exc:
                    raise FetchParseError("FRED observation value is not numeric") from exc
                if not value.is_finite():
                    raise FetchValidationError("FRED observation value is not finite")
            output.append({"reference_period": period.isoformat(),
                "value": None if value is None else format(value, "f"),
                "vintage_start_date": vintage_from.isoformat(), "vintage_end_date": vintage_to.isoformat(),
                "publication_timestamp_status": "DATE_GRAIN_ONLY_NOT_INTRADAY_VERIFIED",
                "pit_observation_ready": False})
        return {"source_id": SOURCE_ID, "product_id": product_id, "series_id": series_id,
            "snapshot_id": snapshot.snapshot_id, "payload_sha256": snapshot.payload_sha256,
            "retrieved_at_utc": snapshot.retrieved_at_utc, "vintage_grain": "DATE",
            "pit_observation_ready": False, "records": output}

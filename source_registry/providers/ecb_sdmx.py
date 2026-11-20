from __future__ import annotations

"""ECB SDMX historical-version acquisition with raw evidence preservation."""

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any, Callable
from urllib.parse import quote, urlencode

from source_registry.adapters.exceptions import FetchParseError, FetchValidationError
from source_registry.raw_archive import RawSnapshotArchive
from .bls import HTTPResponse

SOURCE_ID = "ECB_INTERMARKET"
BASE_URL = "https://data-api.ecb.europa.eu/service/data"
UTC = timezone.utc


def parse_ecb_sdmx_csv(payload: bytes) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8-sig")
        reader = csv.DictReader(StringIO(text))
        if not reader.fieldnames:
            raise FetchParseError("ECB SDMX CSV has no header")
        names = {name.casefold(): name for name in reader.fieldnames}
        time_col = names.get("time_period") or names.get("time")
        value_col = names.get("obs_value") or names.get("observation_value")
        if not time_col or not value_col:
            raise FetchParseError("ECB SDMX CSV lacks TIME_PERIOD or OBS_VALUE")
        rows = []
        revision_counts: dict[str, int] = {}
        for row in reader:
            period = row.get(time_col, "").strip()
            value_text = row.get(value_col, "").strip()
            if not period or not value_text:
                continue
            try:
                value = Decimal(value_text)
            except InvalidOperation as exc:
                raise FetchParseError("ECB OBS_VALUE is not numeric") from exc
            if not value.is_finite():
                raise FetchValidationError("ECB OBS_VALUE must be finite")
            revision_counts[period] = revision_counts.get(period, 0) + 1
            rows.append({"reference_period": period, "value": format(value, "f"),
                         "revision_ordinal_in_response": revision_counts[period],
                         "sdmx_attributes": {k: v for k, v in row.items() if k not in (time_col, value_col)}})
        return rows
    except UnicodeDecodeError as exc:
        raise FetchParseError("ECB SDMX CSV is not UTF-8") from exc


class ECBSdmxHistoricalProvider:
    """Fetch one explicitly configured SDMX flow/key with includeHistory=true.

    Flow/key are required arguments; no unverified ECB series key is guessed.
    The provider archives the exact response and exposes revision metadata, but
    does not invent a publication timestamp from TIME_PERIOD or retrieval time.
    """
    def __init__(self, *, transport: Any, archive: RawSnapshotArchive,
                 flow_ref: str, series_key: str, clock: Callable[[], datetime] | None = None):
        if not callable(getattr(transport, "request", None)):
            raise TypeError("transport must provide request(method, url, ...)")
        if not isinstance(archive, RawSnapshotArchive):
            raise TypeError("archive must be a RawSnapshotArchive")
        if not flow_ref.strip() or not series_key.strip():
            raise ValueError("an exact ECB flow_ref and series_key must be supplied")
        self.transport, self.archive = transport, archive
        self.flow_ref, self.series_key = flow_ref, series_key
        self.clock = clock or (lambda: datetime.now(UTC))

    def acquire(self, product_id: str, *, start_period: str, end_period: str) -> dict[str, Any]:
        if product_id != "DE_10Y_GOVERNMENT_YIELD":
            raise FetchValidationError(f"Unsupported ECB product: {product_id}")
        if start_period > end_period:
            raise ValueError("start_period must not exceed end_period")
        path = f"{BASE_URL}/{quote(self.flow_ref, safe=',')}/{quote(self.series_key, safe='.') }"
        params = {"startPeriod": start_period, "endPeriod": end_period,
                  "includeHistory": "true", "format": "csvdata"}
        url = path + "?" + urlencode(params)
        response = self.transport.request("GET", url, headers={"Accept": "text/csv"})
        if response.status != 200:
            raise FetchValidationError(f"ECB SDMX returned HTTP {response.status}")
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("provider clock must be timezone-aware")
        snapshot = self.archive.append(source_id=SOURCE_ID, product_id=product_id,
            source_url=url, retrieved_at_utc=now.astimezone(UTC), http_status=response.status,
            content_type=response.content_type, payload=response.body, response_headers=response.headers,
            request_metadata={"provider": "ECB_SDMX_2_1", "flow_ref": self.flow_ref,
                "series_key": self.series_key, "includeHistory": True,
                "start_period": start_period, "end_period": end_period})
        records = parse_ecb_sdmx_csv(response.body)
        return {"source_id": SOURCE_ID, "product_id": product_id, "flow_ref": self.flow_ref,
            "series_key": self.series_key, "snapshot_id": snapshot.snapshot_id,
            "payload_sha256": snapshot.payload_sha256, "retrieved_at_utc": snapshot.retrieved_at_utc,
            "history_requested": True, "pit_observation_ready": False,
            "publication_timestamp_status": "NOT_PROVIDED_BY_SDMX_CSV",
            "records": records}

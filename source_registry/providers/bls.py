from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import re
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from source_registry.adapters.exceptions import FetchParseError, FetchValidationError
from source_registry.adapters.models import FetchRequest
from source_registry.raw_archive import RawSnapshotArchive

BLS_SOURCE_ID = "US_BLS_MACRO"
BLS_CPI_PRODUCT_ID = "US_CPI_ALL_ITEMS_INDEX"
BLS_CPI_SERIES_ID = "CUUR0000SA0"
BLS_CPI_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_CPI_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/cpi.htm"
BLS_CPI_ARCHIVE_BASE = "https://www.bls.gov/news.release/archives/cpi_"
ET = ZoneInfo("America/New_York")
UTC = timezone.utc


@dataclass(frozen=True)
class HTTPResponse:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes

    @property
    def content_type(self) -> str:
        return next(
            (value for key, value in self.headers.items() if key.casefold() == "content-type"),
            "application/octet-stream",
        )


class UrllibTransport:
    """HTTPS-only transport with host allowlisting and bounded responses."""

    def __init__(self, *, allowed_hosts: set[str], timeout_seconds: float = 25.0,
                 max_response_bytes: int = 20 * 1024 * 1024) -> None:
        if not allowed_hosts or any(not isinstance(host, str) or not host for host in allowed_hosts):
            raise ValueError("allowed_hosts must contain host names")
        if timeout_seconds <= 0 or max_response_bytes <= 0:
            raise ValueError("timeout and response size limits must be positive")
        self.allowed_hosts = {host.casefold() for host in allowed_hosts}
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def request(self, method: str, url: str, *, body: bytes | None = None,
                headers: Mapping[str, str] | None = None) -> HTTPResponse:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.casefold() not in self.allowed_hosts:
            raise ValueError("provider URL is not on the HTTPS host allowlist")
        request_headers = dict(headers or {})
        request_headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/157.0.0.0 Safari/537.36")
        request_headers.setdefault("Accept-Language", "en-US,en;q=0.9")
        request = Request(url, data=body, headers=request_headers, method=method.upper())
        with urlopen(request, timeout=self.timeout_seconds) as response:
            final_url = response.geturl()
            final = urlsplit(final_url)
            if final.scheme != "https" or not final.hostname or final.hostname.casefold() not in self.allowed_hosts:
                raise ValueError("provider redirected outside the HTTPS host allowlist")
            payload = response.read(self.max_response_bytes + 1)
            if len(payload) > self.max_response_bytes:
                raise ValueError("provider response exceeds configured size limit")
            return HTTPResponse(
                url=final_url,
                status=int(response.status),
                headers={key: value for key, value in response.headers.items()},
                body=payload,
            )


class _HTMLTables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "table":
            if self._table is None:
                self._table = []
                self._table_depth = 1
            else:
                self._table_depth += 1
        elif self._table is not None and self._table_depth == 1:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th") and self._row is not None:
                self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._table is None:
            return
        if tag in ("td", "th") and self._cell is not None:
            value = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            assert self._row is not None
            self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth == 0:
                self.tables.append(self._table)
                self._table = None


def _month_key(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().replace(".", ""))
    for fmt in ("%B %Y", "%b %Y"):
        try:
            return datetime.strptime(normalized, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    raise FetchParseError(f"Unrecognized BLS reference month: {value!r}")


def _release_date(value: str) -> datetime:
    normalized = re.sub(r"\s+", " ", value.strip().replace(".", ""))
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            pass
    raise FetchParseError(f"Unrecognized BLS release date: {value!r}")


def _release_time(value: str) -> tuple[int, int]:
    normalized = re.sub(r"\s+", " ", value.strip()).upper()
    try:
        parsed = datetime.strptime(normalized, "%I:%M %p")
    except ValueError as exc:
        raise FetchParseError(f"Unrecognized BLS release time: {value!r}") from exc
    return parsed.hour, parsed.minute


def parse_bls_release_calendar(html: str) -> dict[str, datetime]:
    if not isinstance(html, str) or not html.strip():
        raise FetchParseError("BLS release calendar HTML is empty")
    parser = _HTMLTables()
    parser.feed(html)
    parser.close()
    output: dict[str, datetime] = {}
    for table in parser.tables:
        header_index = None
        indexes: dict[str, int] = {}
        for row_index, row in enumerate(table):
            lowered = [cell.casefold() for cell in row]
            if all(label in lowered for label in ("reference month", "release date", "release time")):
                header_index = row_index
                indexes = {label: lowered.index(label) for label in (
                    "reference month", "release date", "release time"
                )}
                break
        if header_index is None:
            continue
        for row in table[header_index + 1:]:
            if len(row) <= max(indexes.values()):
                continue
            try:
                key = _month_key(row[indexes["reference month"]])
                day = _release_date(row[indexes["release date"]])
                hour, minute = _release_time(row[indexes["release time"]])
            except FetchParseError:
                continue
            output[key] = datetime(
                day.year, day.month, day.day, hour, minute, tzinfo=ET
            ).astimezone(UTC)
    if not output:
        raise FetchParseError("No dated Reference Month / Release Date / Release Time rows found")
    return output


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def parse_cpi_archive_release(html: str, reference_period: str) -> tuple[Decimal, datetime]:
    """Extract the original unadjusted CPI-U all-items index and embargo timestamp."""
    if not isinstance(html, str) or not html.strip():
        raise FetchParseError("CPI archive release HTML is empty")
    parser = _HTMLTables()
    parser.feed(html)
    parser.close()

    index_value: Decimal | None = None
    for table in parser.tables:
        has_index_header = any(
            "unadjusted indexes" in cell.casefold()
            for row in table for cell in row
        )
        if not has_index_header:
            continue
        for row in table:
            if not row or row[0].strip().casefold() != "all items":
                continue
            if len(row) < 6:
                raise FetchParseError("CPI Table 1 All items row has too few columns")
            try:
                candidate = Decimal(row[5].replace(",", "").strip())
            except InvalidOperation as exc:
                raise FetchParseError("CPI Table 1 current unadjusted index is not numeric") from exc
            if not candidate.is_finite():
                raise FetchParseError("CPI Table 1 current unadjusted index is not finite")
            index_value = candidate
            break
        if index_value is not None:
            break
    if index_value is None:
        raise FetchParseError("CPI Table 1 unadjusted All items index was not found")

    text_parser = _VisibleText()
    text_parser.feed(html)
    text_parser.close()
    visible = re.sub(r"\s+", " ", " ".join(text_parser.parts))
    match = re.search(
        r"embargoed until\s+(\d{1,2}:\d{2}\s+[ap]\.m\.)\s*\(ET\)\s*"
        r"([A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2},\s+\d{4})",
        visible,
        flags=re.IGNORECASE,
    )
    if not match:
        raise FetchParseError("CPI archive release does not expose its original embargo timestamp")
    time_text = match.group(1).replace(".", "").upper()
    try:
        clock = datetime.strptime(time_text, "%I:%M %p")
        day = datetime.strptime(match.group(2), "%A, %B %d, %Y")
    except ValueError as exc:
        raise FetchParseError("CPI archive embargo timestamp could not be parsed") from exc
    published = datetime(
        day.year, day.month, day.day, clock.hour, clock.minute, tzinfo=ET
    ).astimezone(UTC)

    title = re.search(
        r"CONSUMER PRICE INDEX\s*-\s*([A-Z]+)\s+(\d{4})",
        visible,
        flags=re.IGNORECASE,
    )
    if not title:
        raise FetchParseError("CPI archive release title does not identify its reference month")
    actual_period = _month_key(f"{title.group(1)} {title.group(2)}")
    if actual_period != reference_period:
        raise FetchValidationError(
            f"CPI archive period mismatch: expected {reference_period}, got {actual_period}"
        )
    return index_value, published


class BLSCPIRecordsProvider:
    """Fetch and archive BLS CPI API + calendar + original release evidence.

    CPI-U all-items (CUUR0000SA0) is unadjusted. Each API value is accepted only
    after it matches the corresponding original BLS CPI release archive table.
    The original embargo timestamp, not retrieval time, supplies publication time.
    """

    def __init__(self, *, transport: Any, archive: RawSnapshotArchive,
                 clock: Callable[[], datetime] | None = None,
                 lookback_years: int = 1) -> None:
        if not callable(getattr(transport, "request", None)):
            raise TypeError("transport must provide request(method, url, ...)")
        if not isinstance(archive, RawSnapshotArchive):
            raise TypeError("archive must be a RawSnapshotArchive")
        if lookback_years < 1 or lookback_years > 5:
            raise ValueError("lookback_years must be between 1 and 5")
        self.transport = transport
        self.archive = archive
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lookback_years = lookback_years

    def _archive(self, response: HTTPResponse, *, product_id: str,
                 retrieved_at: datetime, request_metadata: Mapping[str, Any]) -> None:
        if response.status != 200:
            raise FetchValidationError(f"BLS provider returned HTTP {response.status}")
        self.archive.append(
            source_id=BLS_SOURCE_ID,
            product_id=product_id,
            source_url=response.url,
            retrieved_at_utc=retrieved_at,
            http_status=response.status,
            content_type=response.content_type,
            payload=response.body,
            response_headers=response.headers,
            request_metadata=request_metadata,
        )

    def __call__(self, request: FetchRequest) -> list[dict[str, str]]:
        if (request.source_id, request.product_id) != (BLS_SOURCE_ID, BLS_CPI_PRODUCT_ID):
            raise FetchValidationError("BLS CPI provider source/product mismatch")
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("provider clock must be timezone-aware")
        now = now.astimezone(UTC)
        start_year = now.year - self.lookback_years
        end_year = now.year
        body = json.dumps({
            "seriesid": [BLS_CPI_SERIES_ID],
            "startyear": str(start_year),
            "endyear": str(end_year),
        }).encode("utf-8")
        api_response = self.transport.request(
            "POST", BLS_CPI_API_URL, body=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        self._archive(api_response, product_id=request.product_id,
                      retrieved_at=self.clock(), request_metadata={
                          "provider": "BLS_PUBLIC_DATA_API_V2",
                          "series_id": BLS_CPI_SERIES_ID,
                          "startyear": str(start_year),
                          "endyear": str(end_year),
                      })

        calendar_response = self.transport.request(
            "GET", BLS_CPI_CALENDAR_URL, headers={"Accept": "text/html"}
        )
        self._archive(calendar_response, product_id=request.product_id,
                      retrieved_at=self.clock(), request_metadata={
                          "provider": "BLS_CPI_RELEASE_CALENDAR",
                          "reference": "CPI",
                      })

        try:
            api_document = json.loads(api_response.body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchParseError("BLS API response is not valid JSON") from exc
        if api_document.get("status") != "REQUEST_SUCCEEDED":
            raise FetchValidationError(
                "BLS API did not report REQUEST_SUCCEEDED: "
                + repr(api_document.get("message", []))
            )
        series = api_document.get("Results", {}).get("series", [])
        if not isinstance(series, list) or len(series) != 1:
            raise FetchParseError("BLS API response must contain exactly one requested series")
        if series[0].get("seriesID") != BLS_CPI_SERIES_ID:
            raise FetchValidationError("BLS API returned an unexpected series ID")

        try:
            calendar = parse_bls_release_calendar(calendar_response.body.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise FetchParseError("BLS release calendar is not valid UTF-8") from exc

        cutoff = request.since or datetime(start_year, now.month, 1, tzinfo=UTC)
        raw_data = series[0].get("data")
        if not isinstance(raw_data, list):
            raise FetchParseError("BLS API series data must be a list")

        output: list[dict[str, str]] = []
        seen_periods: set[str] = set()
        for item in raw_data:
            if not isinstance(item, Mapping):
                raise FetchParseError("BLS API data item must be an object")
            period_code = item.get("period")
            year = item.get("year")
            if not isinstance(year, str) or not isinstance(period_code, str):
                raise FetchParseError("BLS API item requires year and period")
            if not re.fullmatch(r"M(0[1-9]|1[0-2])", period_code):
                continue
            month = int(period_code[1:])
            period = f"{int(year):04d}-{month:02d}"
            effective = datetime(int(year), month, 1, tzinfo=UTC)
            if effective < cutoff:
                continue
            value_text = item.get("value")
            if not isinstance(value_text, str) or value_text.strip() in ("", "-"):
                continue
            try:
                api_value = Decimal(value_text)
            except InvalidOperation as exc:
                raise FetchParseError(f"BLS CPI value is not numeric for {period}") from exc
            if not api_value.is_finite():
                raise FetchValidationError(f"BLS CPI value is not finite for {period}")
            if period in seen_periods:
                raise FetchValidationError(f"BLS API returned duplicate CPI period {period}")
            release_at = calendar.get(period)
            if release_at is None:
                raise FetchValidationError(
                    f"BLS release calendar has no publication mapping for {period}"
                )
            archive_url = f"{BLS_CPI_ARCHIVE_BASE}{release_at.astimezone(ET):%m%d%Y}.htm"
            release_response = self.transport.request(
                "GET", archive_url, headers={"Accept": "text/html"}
            )
            self._archive(release_response, product_id=request.product_id,
                          retrieved_at=self.clock(), request_metadata={
                              "provider": "BLS_ORIGINAL_CPI_RELEASE",
                              "reference_period": period,
                              "scheduled_published_at_utc": release_at.isoformat(),
                          })
            try:
                archived_value, archived_published_at = parse_cpi_archive_release(
                    release_response.body.decode("utf-8-sig"), period
                )
            except UnicodeDecodeError as exc:
                raise FetchParseError(f"BLS CPI archive for {period} is not valid UTF-8") from exc
            if archived_published_at != release_at:
                raise FetchValidationError(
                    f"BLS schedule/archive publication mismatch for {period}: "
                    f"{release_at.isoformat()} != {archived_published_at.isoformat()}"
                )
            if archived_value != api_value:
                raise FetchValidationError(
                    f"BLS current API value does not match original release for {period}: "
                    f"{api_value} != {archived_value}"
                )
            output.append({
                "reference_period": period,
                "value": format(archived_value, "f"),
                "published_at_utc": archived_published_at.isoformat(),
                "source_record_id": f"{BLS_CPI_SERIES_ID}:{period}",
            })
            seen_periods.add(period)

        if not output:
            raise FetchValidationError("BLS CPI acquisition produced no archive-verified observations")
        output.sort(key=lambda row: row["reference_period"])
        return output

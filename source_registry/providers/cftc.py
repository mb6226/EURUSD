from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
import json
import re
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from source_registry.adapters.exceptions import FetchParseError, FetchValidationError
from source_registry.raw_archive import RawSnapshotArchive

CFTC_SOURCE_ID = "CFTC_TFF_POSITIONING"
CFTC_PRODUCTS = (
    "EURO_FX_DEALER_NET_OI_PCT",
    "EURO_FX_ASSET_MANAGER_NET_OI_PCT",
    "EURO_FX_LEVERAGED_MONEY_NET_OI_PCT",
)
CFTC_CONTRACT_MARKET_CODE = "099741"
CFTC_DATASET_ID = "gpe5-46if"
CFTC_API_BASE = f"https://publicreporting.cftc.gov/resource/{CFTC_DATASET_ID}.json"
CFTC_RELEASE_SCHEDULE_URL = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm"
CFTC_SPECIAL_ANNOUNCEMENTS_URL = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm"
ET = ZoneInfo("America/New_York")
UTC = timezone.utc


class _HTMLTables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "table":
            if self._table is None:
                self._table = []
                self._depth = 1
            else:
                self._depth += 1
        elif self._table is not None and self._depth == 1:
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
            assert self._row is not None
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self._depth -= 1
            if self._depth == 0:
                self.tables.append(self._table)
                self._table = None


def _date_from_text(value: str, *, field: str) -> date:
    match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", value)
    if not match:
        raise FetchParseError(f"CFTC {field} is not an MM/DD/YYYY date: {value!r}")
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError as exc:
        raise FetchParseError(f"CFTC {field} is invalid: {value!r}") from exc


def parse_cftc_special_release_dates(html: str) -> dict[date, date]:
    """Parse report-date -> actual new publication-date mappings.

    The first occurrence wins because the official page presents the latest
    revised catch-up schedule before earlier superseded announcements.
    """
    parser = _HTMLTables()
    parser.feed(html)
    parser.close()
    output: dict[date, date] = {}
    for table in parser.tables:
        header_index = None
        indexes: dict[str, int] = {}
        for index, row in enumerate(table):
            lowered = [cell.casefold() for cell in row]
            labels = ("cot report date", "original publish date", "new publish date")
            if all(label in lowered for label in labels):
                header_index = index
                indexes = {label: lowered.index(label) for label in labels}
                break
        if header_index is None:
            continue
        for row in table[header_index + 1:]:
            if len(row) <= max(indexes.values()):
                continue
            try:
                report = _date_from_text(row[indexes["cot report date"]], field="report date")
                published = _date_from_text(row[indexes["new publish date"]], field="new publish date")
            except FetchParseError:
                continue
            output.setdefault(report, published)
    if not output:
        raise FetchParseError("CFTC special announcements contain no dated report/publication table")
    return output


def parse_cftc_regular_release_dates(html: str, *, year: int = 2026) -> set[date]:
    """Parse the official month/day release calendar for a specific year."""
    parser = _HTMLTables()
    parser.feed(html)
    parser.close()
    months = {
        name.casefold(): number
        for number, name in enumerate((
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ), start=1)
    }
    output: set[date] = set()
    found_schedule_table = False
    for table in parser.tables:
        header_index = None
        for index, row in enumerate(table):
            lowered = [cell.casefold() for cell in row]
            if "month" in lowered and "dates" in lowered:
                header_index = index
                found_schedule_table = True
                break
        if header_index is None:
            continue
        for row in table[header_index + 1:]:
            if len(row) < 2:
                continue
            month_number = months.get(row[0].strip().casefold())
            if month_number is None:
                continue
            for cell in row[1:]:
                match = re.search(r"(?<!\d)(\d{1,2})\s*\*?", cell)
                if not match:
                    continue
                day_number = int(match.group(1))
                try:
                    output.add(date(year, month_number, day_number))
                except ValueError:
                    continue
    if not found_schedule_table or not output:
        raise FetchParseError(f"CFTC {year} regular release schedule could not be parsed")
    return output


def build_cftc_publication_map(
    report_dates: list[date],
    *,
    regular_release_dates: set[date],
    special_release_dates: dict[date, date],
) -> dict[date, datetime]:
    """Join each Tuesday report date to its evidenced actual 3:30 p.m. ET release."""
    result: dict[date, datetime] = {}
    for report_date in sorted(set(report_dates)):
        if report_date in special_release_dates:
            release_date = special_release_dates[report_date]
        else:
            candidates = sorted(
                day for day in regular_release_dates
                if report_date < day <= report_date + timedelta(days=7)
            )
            if len(candidates) != 1:
                raise FetchValidationError(
                    f"CFTC report date {report_date.isoformat()} has "
                    f"{len(candidates)} matching scheduled release dates"
                )
            release_date = candidates[0]
        if release_date <= report_date:
            raise FetchValidationError("CFTC publication date must follow report date")
        result[report_date] = datetime.combine(
            release_date, time(15, 30), tzinfo=ET
        ).astimezone(UTC)
    return result


class CFTCOfficialSnapshotProvider:
    """Acquire and PIT-normalize official TFF Futures-Only EURO FX reports.

    Exact catch-up publication dates are taken from CFTC's special-announcement
    tables. Normal 2026 dates are joined against the official 2026 release
    calendar. CFTC states the release time is 3:30 p.m. Eastern. If any report
    cannot be joined uniquely, the provider fails closed before PIT ingestion.
    """

    def __init__(self, *, transport: Any, archive: RawSnapshotArchive,
                 clock: Callable[[], datetime] | None = None,
                 lookback_days: int = 365, max_rows: int = 5000) -> None:
        if not callable(getattr(transport, "request", None)):
            raise TypeError("transport must provide request(method, url, ...)")
        if not isinstance(archive, RawSnapshotArchive):
            raise TypeError("archive must be a RawSnapshotArchive")
        if lookback_days < 30 or lookback_days > 730:
            raise ValueError("lookback_days must be between 30 and 730")
        if max_rows < 1 or max_rows > 50000:
            raise ValueError("max_rows must be between 1 and 50000")
        self.transport = transport
        self.archive = archive
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lookback_days = lookback_days
        self.max_rows = max_rows
        self._records_by_product: dict[str, list[dict[str, str]]] = {}

    def _archive(self, response: Any, *, retrieved: datetime,
                 request_metadata: dict[str, Any]) -> None:
        if response.status != 200:
            raise FetchValidationError(f"CFTC provider returned HTTP {response.status}")
        for product_id in CFTC_PRODUCTS:
            self.archive.append(
                source_id=CFTC_SOURCE_ID,
                product_id=product_id,
                source_url=response.url,
                retrieved_at_utc=retrieved,
                http_status=response.status,
                content_type=response.content_type,
                payload=response.body,
                response_headers=response.headers,
                request_metadata=request_metadata,
            )

    def acquire(self) -> dict[str, Any]:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("provider clock must be timezone-aware")
        now = now.astimezone(UTC)
        start = (now - timedelta(days=self.lookback_days)).date().isoformat()
        where = (
            f"cftc_contract_market_code='{CFTC_CONTRACT_MARKET_CODE}' "
            f"AND report_date_as_yyyy_mm_dd >= '{start}T00:00:00.000'"
        )
        query = urlencode({
            "$where": where,
            "$order": "report_date_as_yyyy_mm_dd ASC",
            "$limit": str(self.max_rows),
        })
        url = f"{CFTC_API_BASE}?{query}"
        response = self.transport.request(
            "GET", url, headers={"Accept": "application/json"}
        )
        if response.status != 200:
            raise FetchValidationError(f"CFTC API returned HTTP {response.status}")
        retrieved = self.clock().astimezone(UTC)
        try:
            rows = json.loads(response.body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchParseError("CFTC TFF response is not valid JSON") from exc
        if not isinstance(rows, list):
            raise FetchParseError("CFTC TFF response must be a JSON array")
        if len(rows) > self.max_rows:
            raise FetchValidationError("CFTC response exceeded requested row limit")

        required = {
            "cftc_contract_market_code",
            "report_date_as_yyyy_mm_dd",
            "open_interest_all",
            "dealer_positions_long_all",
            "dealer_positions_short_all",
            "asset_mgr_positions_long",
            "asset_mgr_positions_short",
            "lev_money_positions_long",
            "lev_money_positions_short",
        }
        parsed_rows: list[tuple[date, dict[str, Any]]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise FetchParseError(f"CFTC row {index} must be an object")
            missing = required.difference(row)
            if missing:
                raise FetchParseError(
                    f"CFTC row {index} missing fields: {', '.join(sorted(missing))}"
                )
            if str(row["cftc_contract_market_code"]).strip() != CFTC_CONTRACT_MARKET_CODE:
                raise FetchValidationError("CFTC response contains a non-EURO-FX contract")
            raw_date = row["report_date_as_yyyy_mm_dd"]
            if not isinstance(raw_date, str) or len(raw_date) < 10:
                raise FetchValidationError("CFTC report date is malformed")
            try:
                report_day = date.fromisoformat(raw_date[:10])
            except ValueError as exc:
                raise FetchValidationError("CFTC report date is malformed") from exc
            if report_day.weekday() != 1:
                raise FetchValidationError("CFTC report date is not a Tuesday")
            parsed_rows.append((report_day, row))

        report_dates = [item[0] for item in parsed_rows]
        if not parsed_rows:
            raise FetchValidationError("CFTC TFF query returned no EURO FX records")
        if len(report_dates) != len(set(report_dates)):
            raise FetchValidationError("CFTC TFF response contains duplicate report dates")
        if report_dates != sorted(report_dates):
            raise FetchValidationError("CFTC TFF response is not ordered by report date")

        # Preserve exact provider payload before any release-calendar parsing.
        self._archive(response, retrieved=retrieved, request_metadata={
            "provider": "CFTC_SOCRATA_PUBLIC_REPORTING",
            "dataset_id": CFTC_DATASET_ID,
            "report": "TFF_FUTURES_ONLY",
            "contract_market_code": CFTC_CONTRACT_MARKET_CODE,
            "report_date_start": start,
            "row_count": len(rows),
        })

        schedule = self.transport.request(
            "GET", CFTC_RELEASE_SCHEDULE_URL, headers={"Accept": "text/html"}
        )
        self._archive(schedule, retrieved=self.clock().astimezone(UTC),
                      request_metadata={
                          "provider": "CFTC_OFFICIAL_RELEASE_SCHEDULE",
                          "schedule_year": 2026,
                      })
        special = self.transport.request(
            "GET", CFTC_SPECIAL_ANNOUNCEMENTS_URL, headers={"Accept": "text/html"}
        )
        self._archive(special, retrieved=self.clock().astimezone(UTC),
                      request_metadata={
                          "provider": "CFTC_HISTORICAL_SPECIAL_ANNOUNCEMENTS",
                          "purpose": "catch_up_publication_date_mapping",
                      })

        try:
            regular_dates = parse_cftc_regular_release_dates(
                schedule.body.decode("utf-8-sig"), year=2026
            )
            special_dates = parse_cftc_special_release_dates(
                special.body.decode("utf-8-sig")
            )
        except UnicodeDecodeError as exc:
            raise FetchParseError("CFTC release-calendar HTML is not valid UTF-8") from exc
        publication_map = build_cftc_publication_map(
            report_dates,
            regular_release_dates=regular_dates,
            special_release_dates=special_dates,
        )

        category_fields = {
            "dealer": ("dealer_positions_long_all", "dealer_positions_short_all"),
            "asset_manager": ("asset_mgr_positions_long", "asset_mgr_positions_short"),
            "leveraged_money": ("lev_money_positions_long", "lev_money_positions_short"),
        }
        self._records_by_product = {product: [] for product in CFTC_PRODUCTS}
        product_categories = {
            "EURO_FX_DEALER_NET_OI_PCT": "dealer",
            "EURO_FX_ASSET_MANAGER_NET_OI_PCT": "asset_manager",
            "EURO_FX_LEVERAGED_MONEY_NET_OI_PCT": "leveraged_money",
        }
        for report_day, row in parsed_rows:
            published = publication_map[report_day]
            common = {
                "report_date": report_day.isoformat(),
                "published_at_utc": published.isoformat(),
                "contract_market_code": CFTC_CONTRACT_MARKET_CODE,
                "open_interest": str(row["open_interest_all"]),
                "dealer_long": str(row["dealer_positions_long_all"]),
                "dealer_short": str(row["dealer_positions_short_all"]),
                "asset_manager_long": str(row["asset_mgr_positions_long"]),
                "asset_manager_short": str(row["asset_mgr_positions_short"]),
                "leveraged_money_long": str(row["lev_money_positions_long"]),
                "leveraged_money_short": str(row["lev_money_positions_short"]),
                "source_record_id": f"{CFTC_CONTRACT_MARKET_CODE}|{report_day.isoformat()}",
            }
            for product_id in product_categories:
                self._records_by_product[product_id].append(dict(common))

        return {
            "source_id": CFTC_SOURCE_ID,
            "dataset_id": CFTC_DATASET_ID,
            "contract_market_code": CFTC_CONTRACT_MARKET_CODE,
            "rows": len(parsed_rows),
            "first_report_date": min(report_dates).isoformat(),
            "last_report_date": max(report_dates).isoformat(),
            "retrieved_at_utc": retrieved.isoformat(),
            "products_archived": list(CFTC_PRODUCTS),
            "release_schedule_dates": len(regular_dates),
            "special_release_date_mappings": len(special_dates),
            "publication_map_rows": len(publication_map),
            "first_published_at_utc": min(publication_map.values()).isoformat(),
            "last_published_at_utc": max(publication_map.values()).isoformat(),
            "pit_records_ready": True,
            "pit_observations_persisted": 0,
            "reason": "Every Tuesday report date is joined to an official scheduled or special-announcement publication date at 3:30 p.m. America/New_York.",
        }

    def records_for_product(self, product_id: str) -> list[dict[str, str]]:
        if product_id not in CFTC_PRODUCTS:
            raise ValueError(f"Unregistered CFTC product: {product_id}")
        if not self._records_by_product:
            raise RuntimeError("acquire() must complete before records_for_product()")
        return [dict(row) for row in self._records_by_product[product_id]]

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from source_registry.adapters.models import FetchRequest
from source_registry.providers.bls import (
    BLSCPIRecordsProvider,
    HTTPResponse,
    parse_bls_release_calendar,
    parse_cpi_archive_release,
)
from source_registry.providers.cftc import (
    CFTCOfficialSnapshotProvider,
    build_cftc_publication_map,
    parse_cftc_regular_release_dates,
    parse_cftc_special_release_dates,
)
from source_registry.raw_archive import RawSnapshotArchive

UTC = timezone.utc
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

CALENDAR = """<html><table>
<tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr>
<tr><td>October 2026</td><td>Nov. 10, 2026</td><td>08:30 AM</td></tr>
</table></html>"""

CPI_RELEASE = """<html><body>
<p>Transmission of material in this release is embargoed until
8:30 a.m. (ET) Tuesday, November 10, 2026</p>
<p>CONSUMER PRICE INDEX - OCTOBER 2026</p>
<table>
<tr><th>Expenditure category</th><th>Relative importance</th><th>Sep. 2026</th>
<th>Unadjusted indexes</th><th>Oct. 2025</th><th>Sep. 2026</th><th>Oct. 2026</th>
<th>Unadjusted percent change</th></tr>
<tr><td>All items</td><td>100.000</td><td>-</td><td>-</td><td>336.940</td>
<td>337.511</td><td>-</td></tr>
</table></body></html>"""

CFTC_SCHEDULE = """<html><table>
<tr><th>Month</th><th>Dates</th><th></th><th></th><th></th></tr>
<tr><td>January</td><td>05*</td><td>09</td><td>16</td><td>23</td></tr>
<tr><td>November</td><td>06</td><td>16*</td><td>20</td><td>30*</td></tr>
</table></html>"""

CFTC_SPECIAL = """<html><table>
<tr><th>COT Report Date</th><th>Original Publish Date</th><th>New Publish Date</th></tr>
<tr><td>11/25/2025</td><td>12/01/2025</td><td>12/15/2025</td></tr>
<tr><td>12/02/2025</td><td>12/05/2025</td><td>12/17/2025</td></tr>
</table></html>"""


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, body=None, headers=None):
        self.calls.append((method, url, body, headers))
        if not self.responses:
            raise AssertionError("Unexpected provider request")
        return self.responses.pop(0)


class BLSProviderTests(unittest.TestCase):
    def test_release_calendar_parses_local_time_to_utc(self):
        result = parse_bls_release_calendar(CALENDAR)
        self.assertEqual(result["2026-10"], datetime(2026, 11, 10, 13, 30, tzinfo=UTC))

    def test_archive_parser_extracts_original_index_and_embargo(self):
        value, published = parse_cpi_archive_release(CPI_RELEASE, "2026-10")
        self.assertEqual(str(value), "337.511")
        self.assertEqual(published, datetime(2026, 11, 10, 13, 30, tzinfo=UTC))

    def test_archive_parser_rejects_wrong_reference_period(self):
        with self.assertRaises(ValueError):
            parse_cpi_archive_release(CPI_RELEASE, "2026-09")

    def test_provider_archives_raw_evidence_before_returning_normalized_records(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        archive = RawSnapshotArchive(
            Path(temp.name) / "raw.sqlite",
            allowed_products={"US_BLS_MACRO": {"US_CPI_ALL_ITEMS_INDEX"}},
        )
        api = {
            "status": "REQUEST_SUCCEEDED",
            "Results": {"series": [{
                "seriesID": "CUUR0000SA0",
                "data": [{"year": "2026", "period": "M10", "value": "337.511"}],
            }]},
        }
        transport = FakeTransport([
            HTTPResponse("https://api.bls.gov/publicAPI/v1/timeseries/data/", 200,
                         {"Content-Type": "application/json"}, json.dumps(api).encode()),
            HTTPResponse("https://www.bls.gov/schedule/news_release/cpi.htm?lv=true", 200,
                         {"Content-Type": "text/html"}, CALENDAR.encode()),
            HTTPResponse("https://www.bls.gov/news.release/archives/cpi_11102026.htm", 200,
                         {"Content-Type": "text/html"}, CPI_RELEASE.encode()),
        ])
        provider = BLSCPIRecordsProvider(transport=transport, archive=archive, clock=lambda: NOW)
        records = provider(FetchRequest(
            "US_BLS_MACRO", "US_CPI_ALL_ITEMS_INDEX",
            datetime(2026, 10, 1, tzinfo=UTC),
        ))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["reference_period"], "2026-10")
        self.assertEqual(records[0]["value"], "337.511")
        self.assertEqual(records[0]["published_at_utc"], "2026-11-10T13:30:00+00:00")
        self.assertEqual(len(archive.list_snapshots()), 3)

    def test_provider_fails_closed_when_api_value_differs_from_original_release(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        archive = RawSnapshotArchive(
            Path(temp.name) / "raw.sqlite",
            allowed_products={"US_BLS_MACRO": {"US_CPI_ALL_ITEMS_INDEX"}},
        )
        api = {
            "status": "REQUEST_SUCCEEDED",
            "Results": {"series": [{
                "seriesID": "CUUR0000SA0",
                "data": [{"year": "2026", "period": "M10", "value": "337.999"}],
            }]},
        }
        transport = FakeTransport([
            HTTPResponse("https://api.bls.gov/publicAPI/v1/timeseries/data/", 200,
                         {"Content-Type": "application/json"}, json.dumps(api).encode()),
            HTTPResponse("https://www.bls.gov/schedule/news_release/cpi.htm?lv=true", 200,
                         {"Content-Type": "text/html"}, CALENDAR.encode()),
            HTTPResponse("https://www.bls.gov/news.release/archives/cpi_11102026.htm", 200,
                         {"Content-Type": "text/html"}, CPI_RELEASE.encode()),
        ])
        provider = BLSCPIRecordsProvider(transport=transport, archive=archive, clock=lambda: NOW)
        with self.assertRaises(ValueError):
            provider(FetchRequest(
                "US_BLS_MACRO", "US_CPI_ALL_ITEMS_INDEX",
                datetime(2026, 10, 1, tzinfo=UTC),
            ))


class CFTCReleaseCalendarTests(unittest.TestCase):
    def test_regular_schedule_parses_month_days_and_holiday_markers(self):
        result = parse_cftc_regular_release_dates(CFTC_SCHEDULE)
        self.assertIn(date(2026, 1, 5), result)
        self.assertIn(date(2026, 11, 16), result)
        self.assertIn(date(2026, 11, 30), result)

    def test_special_schedule_uses_explicit_new_publish_dates(self):
        result = parse_cftc_special_release_dates(CFTC_SPECIAL)
        self.assertEqual(result[date(2025, 11, 25)], date(2025, 12, 15))
        self.assertEqual(result[date(2025, 12, 2)], date(2025, 12, 17))

    def test_publication_map_uses_special_mapping_then_regular_schedule(self):
        result = build_cftc_publication_map(
            [date(2025, 11, 25), date(2026, 11, 10)],
            regular_release_dates={date(2026, 11, 16)},
            special_release_dates={date(2025, 11, 25): date(2025, 12, 15)},
        )
        self.assertEqual(result[date(2025, 11, 25)], datetime(2025, 12, 15, 20, 30, tzinfo=UTC))
        self.assertEqual(result[date(2026, 11, 10)], datetime(2026, 11, 16, 20, 30, tzinfo=UTC))


class CFTCProviderTests(unittest.TestCase):
    def _archive(self, temp):
        return RawSnapshotArchive(Path(temp.name) / "raw.sqlite", allowed_products={
            "CFTC_TFF_POSITIONING": {
                "EURO_FX_DEALER_NET_OI_PCT",
                "EURO_FX_ASSET_MANAGER_NET_OI_PCT",
                "EURO_FX_LEVERAGED_MONEY_NET_OI_PCT",
            }
        })

    def _row(self, code="099741"):
        return {
            "cftc_contract_market_code": code,
            "report_date_as_yyyy_mm_dd": "2026-11-10T00:00:00.000",
            "open_interest_all": "100000",
            "dealer_positions_long_all": "10000",
            "dealer_positions_short_all": "9000",
            "asset_mgr_positions_long": "20000",
            "asset_mgr_positions_short": "15000",
            "lev_money_positions_long": "12000",
            "lev_money_positions_short": "13000",
        }

    def test_cftc_historical_records_are_joined_to_official_publication_time(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        archive = self._archive(temp)
        api_body = json.dumps([self._row()]).encode()
        transport = FakeTransport([
            HTTPResponse("https://publicreporting.cftc.gov/resource/gpe5-46if.json?$limit=5000",
                         200, {"Content-Type": "application/json"}, api_body),
            HTTPResponse("https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm",
                         200, {"Content-Type": "text/html"}, CFTC_SCHEDULE.encode()),
            HTTPResponse("https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm",
                         200, {"Content-Type": "text/html"}, CFTC_SPECIAL.encode()),
        ])
        provider = CFTCOfficialSnapshotProvider(transport=transport, archive=archive, clock=lambda: NOW)
        report = provider.acquire()
        self.assertEqual(report["rows"], 1)
        self.assertEqual(report["publication_map_rows"], 1)
        self.assertTrue(report["pit_records_ready"])
        records = provider.records_for_product("EURO_FX_DEALER_NET_OI_PCT")
        self.assertEqual(records[0]["published_at_utc"], "2026-11-16T20:30:00+00:00")
        self.assertEqual(records[0]["dealer_long"], "10000")
        self.assertEqual(len(archive.list_snapshots()), 9)

    def test_cftc_provider_rejects_wrong_contract_before_archiving(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        archive = self._archive(temp)
        transport = FakeTransport([
            HTTPResponse("https://publicreporting.cftc.gov/resource/gpe5-46if.json",
                         200, {"Content-Type": "application/json"},
                         json.dumps([self._row("123456")]).encode())
        ])
        provider = CFTCOfficialSnapshotProvider(transport=transport, archive=archive, clock=lambda: NOW)
        with self.assertRaises(ValueError):
            provider.acquire()
        self.assertEqual(archive.list_snapshots(), [])


if __name__ == "__main__":
    unittest.main()

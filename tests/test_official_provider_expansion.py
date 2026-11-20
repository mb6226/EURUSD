import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from source_registry.providers.bls import HTTPResponse
from source_registry.providers.fred import FREDALFREDVintageProvider, SERIES_BY_PRODUCT
from source_registry.providers.ecb_sdmx import ECBSdmxHistoricalProvider, parse_ecb_sdmx_csv
from source_registry.raw_archive import RawSnapshotArchive

UTC = timezone.utc
NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)

class FakeTransport:
    def __init__(self, response): self.response, self.calls = response, []
    def request(self, method, url, *, body=None, headers=None):
        self.calls.append((method, url, body, headers))
        return self.response

class OfficialProviderExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_fred_alfred_preserves_vintage_intervals_without_fabricating_release_time(self):
        payload = json.dumps({"observations": [
            {"date": "2026-10-01", "realtime_start": "2026-11-10", "realtime_end": "2026-11-19", "value": "4.12"},
            {"date": "2026-10-01", "realtime_start": "2026-11-20", "realtime_end": "9999-12-31", "value": "4.10"},
        ]}).encode()
        transport = FakeTransport(HTTPResponse("https://api.stlouisfed.org/fred/series/observations", 200,
            {"Content-Type": "application/json"}, payload))
        archive = RawSnapshotArchive(self.root / "fred.sqlite", allowed_products={"FRED_INTERMARKET": {"US_10Y_TREASURY_YIELD"}})
        provider = FREDALFREDVintageProvider(transport=transport, archive=archive, api_key="a" * 32, clock=lambda: NOW)
        result = provider.acquire("US_10Y_TREASURY_YIELD", realtime_start="2026-11-01", realtime_end="2026-11-20")
        self.assertEqual(result["series_id"], "DGS10")
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["records"][0]["vintage_start_date"], "2026-11-10")
        self.assertFalse(result["pit_observation_ready"])
        self.assertEqual(result["records"][0]["publication_timestamp_status"], "DATE_GRAIN_ONLY_NOT_INTRADAY_VERIFIED")
        self.assertNotIn("a" * 32, archive.list_snapshots()[0]["source_url"])
        self.assertEqual(len(archive.list_snapshots()), 1)

    def test_fred_allowlist_covers_daily_rates_usd_equity_volatility_energy_and_fx_reference(self):
        expected = {
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
        self.assertEqual(SERIES_BY_PRODUCT, expected)
        for product_id in expected:
            self.assertRegex(product_id, r"^[A-Z][A-Z0-9_]+$")

    def test_fred_requires_explicit_api_key_and_rejects_inverted_vintage_range(self):
        archive = RawSnapshotArchive(self.root / "fred.sqlite", allowed_products={"FRED_INTERMARKET": {"US_10Y_TREASURY_YIELD"}})
        transport = FakeTransport(HTTPResponse("https://api.stlouisfed.org", 200, {"Content-Type": "application/json"}, b'{"observations":[]}'))
        with self.assertRaises(ValueError): FREDALFREDVintageProvider(transport=transport, archive=archive, api_key="")
        provider = FREDALFREDVintageProvider(transport=transport, archive=archive, api_key="a" * 32, clock=lambda: NOW)
        with self.assertRaises(ValueError): provider.acquire("US_10Y_TREASURY_YIELD", realtime_start="2026-11-20", realtime_end="2026-11-01")
        self.assertEqual(transport.calls, [])

    def test_ecb_csv_parser_preserves_revision_attributes(self):
        payload = b"KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\nA,2026-10-01,2.75,A\nA,2026-10-01,2.70,B\n"
        rows = parse_ecb_sdmx_csv(payload)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["value"], "2.75")
        self.assertEqual(rows[1]["sdmx_attributes"]["OBS_STATUS"], "B")

    def test_ecb_provider_requests_history_archives_response_and_does_not_claim_pit_ready(self):
        payload = b"KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\nA,2026-10-01,2.75,A\n"
        transport = FakeTransport(HTTPResponse("https://data-api.ecb.europa.eu/service/data/EXR/X", 200,
            {"Content-Type": "text/csv"}, payload))
        archive = RawSnapshotArchive(self.root / "ecb.sqlite", allowed_products={"ECB_INTERMARKET": {"DE_10Y_GOVERNMENT_YIELD"}})
        provider = ECBSdmxHistoricalProvider(transport=transport, archive=archive,
            flow_ref="YC", series_key="B.DE.EUR.4F.G_N_A.SV_C_YM.SR_10Y", clock=lambda: NOW)
        result = provider.acquire("DE_10Y_GOVERNMENT_YIELD", start_period="2020", end_period="2026")
        self.assertTrue(result["history_requested"])
        self.assertFalse(result["pit_observation_ready"])
        self.assertEqual(result["records"][0]["reference_period"], "2026-10-01")
        self.assertIn("includeHistory=true", transport.calls[0][1])
        self.assertEqual(len(archive.list_snapshots()), 1)

    def test_ecb_provider_requires_explicit_flow_and_key(self):
        archive = RawSnapshotArchive(self.root / "ecb.sqlite", allowed_products={"ECB_INTERMARKET": {"DE_10Y_GOVERNMENT_YIELD"}})
        transport = FakeTransport(HTTPResponse("https://data-api.ecb.europa.eu", 200, {"Content-Type": "text/csv"}, b"x"))
        with self.assertRaises(ValueError): ECBSdmxHistoricalProvider(transport=transport, archive=archive, flow_ref="", series_key="x")

if __name__ == "__main__": unittest.main()

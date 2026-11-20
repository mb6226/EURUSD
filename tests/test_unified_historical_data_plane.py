from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from source_registry.adapters.models import FetchResult, Observation
from source_registry.data_plane import PointInTimeDataPlane
from source_registry.observation_store import PointInTimeObservationStore
from eurusd_ai_monitor.storage.market_data_store import Candle, MarketDataStore

UTC = timezone.utc
AS_OF = datetime(2026, 11, 20, 12, tzinfo=UTC)


def product(product_id="RATE", unit="percent"):
    return {
        "product_id": product_id,
        "measure": "benchmark rate",
        "data_type": "TIME_SERIES",
        "unit": unit,
        "observation_frequency": "DAILY",
        "effective_date_field": "effective_at_utc",
        "publication_time_field": "published_at_utc",
        "value_kind": "SCALAR",
    }


def registry(unit="percent"):
    return {"schema_version": 1, "sources": [{
        "source_id": "FRED_INTERMARKET", "name": "FRED", "category": "FINANCIAL_MARKETS",
        "topics": ["rates", "intermarket"], "enabled": True, "auto_fetch": False,
        "publisher": {"authority_tier": "OFFICIAL"},
        "products": [product(unit=unit)],
    }]}


def persist(store, value="4.25", *, unit="percent", retrieved_day=19, retrieved_hour=13, published_day=19, record_id="US10Y"):
    observation = Observation(
        source_id="FRED_INTERMARKET", product_id="RATE", value=Decimal(value), unit=unit,
        effective_at_utc=datetime(2026, 11, 19, 0, tzinfo=UTC),
        published_at_utc=datetime(2026, 11, published_day, 12, tzinfo=UTC),
        source_record_id=record_id,
    )
    result = FetchResult(
        source_id="FRED_INTERMARKET", product_id="RATE", observations=(observation,),
        source_url="https://example.test/rates", record_count=1,
        retrieved_at_utc=datetime(2026, 11, retrieved_day, retrieved_hour, tzinfo=UTC),
    )
    return store.persist_fetch_result(result)


class UnifiedHistoricalDataPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "observations.sqlite"
        self.writer = PointInTimeObservationStore(self.path)
        self.reader = PointInTimeObservationStore.open_read_only(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def plane(self, unit="percent"):
        return PointInTimeDataPlane(registry=registry(unit), observation_store=self.reader)

    def test_clean_observation_is_available_in_both_evidence_and_analytics_views(self):
        persist(self.writer)
        report = self.plane().read_unified_as_of(AS_OF)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["read_mode"], "STRICT_SYSTEM_KNOWLEDGE")
        self.assertEqual(report["evidence_observation_count"], 1)
        self.assertEqual(report["quality_eligible_product_count"], 1)
        evidence = report["evidence_domains"]["intermarket"]["products"][0]
        analytics = report["analytics_domains"]["intermarket"]["products"][0]
        self.assertEqual(len(evidence["observations"]), 1)
        self.assertEqual(analytics["status"], "ELIGIBLE")
        self.assertEqual(analytics["eligible_observation_count"], 1)
        self.assertTrue(report["policy"]["raw_eligible_evidence_preserved"])

    def test_unit_mismatch_is_quarantined_but_original_evidence_is_preserved(self):
        persist(self.writer, unit="basis_points")
        report = self.plane().read_unified_as_of(AS_OF)
        evidence = report["evidence_domains"]["intermarket"]["products"][0]
        analytics = report["analytics_domains"]["intermarket"]["products"][0]
        self.assertEqual(len(evidence["observations"]), 1)
        self.assertEqual(analytics["status"], "QUARANTINED")
        self.assertEqual(analytics["eligible_observation_count"], 0)
        self.assertIn("UNIT_MISMATCH", {x["code"] for x in report["quality_report"]["products"][0]["issues"]})

    def test_future_publication_and_future_retrieval_are_excluded_by_strict_read(self):
        persist(self.writer, published_day=21, retrieved_day=21)
        report = self.plane().read_unified_as_of(AS_OF)
        self.assertEqual(report["evidence_observation_count"], 0)
        self.assertEqual(report["analytics_domains"]["intermarket"]["products"][0]["status"], "QUARANTINED")

    def test_revision_history_is_visible_at_cutoff_without_replacing_original_versions(self):
        persist(self.writer, value="4.20", retrieved_day=19, record_id="US10Y")
        persist(self.writer, value="4.25", retrieved_day=20, retrieved_hour=10, record_id="US10Y")
        report = self.plane().read_unified_as_of(AS_OF)
        revision = report["quality_report"]["products"][0]["revision_history"]
        self.assertEqual(revision["revision_count"], 1)
        self.assertEqual(revision["max_absolute_value_delta"], "0.05")
        self.assertEqual(report["evidence_observation_count"], 1)
        self.assertEqual(len(report["evidence_domains"]["intermarket"]["products"][0]["observations"]), 1)

    def test_snapshot_hash_is_deterministic_for_same_as_of_evidence(self):
        persist(self.writer)
        first = self.plane().read_unified_as_of(AS_OF)
        second = self.plane().read_unified_as_of(AS_OF)
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        self.assertEqual(len(first["snapshot_sha256"]), 64)

    def test_snapshot_hash_binds_registry_contract_version(self):
        persist(self.writer)
        first = self.plane().read_unified_as_of(AS_OF)
        changed_registry = registry()
        changed_registry["sources"][0]["products"][0]["measure"] = "changed contract"
        changed = PointInTimeDataPlane(
            registry=changed_registry, observation_store=self.reader
        ).read_unified_as_of(AS_OF)
        self.assertNotEqual(first["registry_sha256"], changed["registry_sha256"])
        self.assertNotEqual(first["snapshot_sha256"], changed["snapshot_sha256"])

    def test_naive_cutoff_is_rejected(self):
        with self.assertRaises(ValueError):
            self.plane().read_unified_as_of(datetime(2026, 11, 20, 12))

    def test_unconfigured_store_does_not_create_database_or_claim_ready(self):
        missing = Path(self.temp.name) / "not-created.sqlite"
        plane = PointInTimeDataPlane(registry=registry(), observation_store=None)
        report = plane.read_unified_as_of(AS_OF)
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertFalse(missing.exists())

    def test_versioned_spot_candles_join_as_separate_strict_pit_stream(self):
        market_path = Path(self.temp.name) / "market.sqlite"
        writer = MarketDataStore(market_path)
        candle = Candle(
            broker_server="Headway-Demo", symbol="EURUSD", timeframe="M1",
            candle_open_time_utc=datetime(2026, 11, 20, 11, 58, tzinfo=UTC),
            open="1.15000", high="1.15020", low="1.14990", close="1.15010",
            tick_volume=12, spread=8, real_volume=0,
        )
        writer.upsert_candles(
            [candle], as_of_utc=AS_OF,
            observed_at_utc=AS_OF, source_id="MT5_COPY_RATES",
            provenance={"bar_time_basis":"UTC", "price_basis":{"price_basis":"BID"}},
        )
        reader = MarketDataStore.open_read_only(market_path)
        report = PointInTimeDataPlane(
            registry=registry(), observation_store=self.reader,
            market_data_store=reader,
        ).read_unified_as_of(AS_OF)
        self.assertEqual(report["spot_market_archive"]["status"], "AVAILABLE")
        stream = report["spot_market_archive"]["streams"][0]
        self.assertEqual(stream["status"], "PASS")
        self.assertEqual(stream["price_basis"], "BID")
        self.assertEqual(len(stream["candles"]), 1)
        self.assertEqual(stream["candles"][0]["values"]["close"], "1.15010")
        self.assertTrue(report["policy"]["spot_candles_use_separate_append_only_version_ledger"])

    def test_unknown_spot_price_basis_is_quarantined(self):
        market_path = Path(self.temp.name) / "unknown-basis.sqlite"
        writer = MarketDataStore(market_path)
        candle = Candle(
            broker_server="Headway-Demo", symbol="EURUSD", timeframe="M1",
            candle_open_time_utc=datetime(2026, 11, 20, 11, 58, tzinfo=UTC),
            open="1.15000", high="1.15020", low="1.14990", close="1.15010",
            tick_volume=12, spread=8, real_volume=0,
        )
        writer.upsert_candles([candle], as_of_utc=AS_OF, observed_at_utc=AS_OF,
            source_id="MT5_COPY_RATES", provenance={"bar_time_basis":"UTC", "price_basis":{"price_basis":"UNKNOWN"}})
        report = PointInTimeDataPlane(registry=registry(), observation_store=self.reader,
            market_data_store=MarketDataStore.open_read_only(market_path)).read_unified_as_of(AS_OF)
        stream = report["spot_market_archive"]["streams"][0]
        self.assertEqual(stream["status"], "BLOCKED")
        self.assertIn("PRICE_BASIS_UNVERIFIED", stream["issues"])
        self.assertEqual(len(stream["evidence_candles"]), 1)
        self.assertEqual(stream["candles"], [])

    def test_legacy_spot_database_is_reported_unattested_without_migration(self):
        import sqlite3
        market_path = Path(self.temp.name) / "legacy-market.sqlite"
        connection = sqlite3.connect(market_path)
        connection.execute("CREATE TABLE candles (broker_server TEXT, symbol TEXT, timeframe TEXT, candle_open_time_utc TEXT)")
        connection.execute("INSERT INTO candles VALUES ('Headway-Demo','EURUSD','M1','2026-11-19T00:00:00Z')")
        connection.execute("PRAGMA user_version=3")
        connection.commit()
        connection.close()
        reader = MarketDataStore.open_read_only(market_path)
        report = PointInTimeDataPlane(
            registry=registry(), observation_store=self.reader,
            market_data_store=reader,
        ).read_unified_as_of(AS_OF)
        self.assertEqual(report["spot_market_archive"]["status"], "PROVENANCE_UNAVAILABLE")
        self.assertEqual(report["spot_market_archive"]["legacy_candle_count"], 1)
        self.assertFalse(report["spot_market_archive"]["eligible_for_analytics"])
        check = sqlite3.connect(market_path)
        try:
            self.assertEqual(check.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertNotIn("candle_versions", {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")})
        finally:
            check.close()

    def test_lower_upper_range_contract_is_supported(self):
        from source_registry.data_quality import assess_product_quality
        item = product()
        item["value_kind"] = "RANGE"
        row = {"source_id":"FRED_INTERMARKET", "product_id":"RATE", "observation_key":"range",
               "effective_at_utc":"2026-11-19T00:00:00Z", "published_at_utc":"2026-11-19T12:00:00Z",
               "retrieved_at_utc":"2026-11-19T13:00:00Z", "value":{"lower":1,"upper":2}, "unit":"percent"}
        result = assess_product_quality(item, [row], as_of_utc=AS_OF)
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()

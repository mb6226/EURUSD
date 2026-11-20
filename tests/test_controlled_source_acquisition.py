import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from source_registry.acquisition_plan import (
    build_acquisition_plan,
    build_acquisition_plan_from_paths,
)
from source_registry.raw_archive import RawSnapshotArchive

UTC = timezone.utc


class ControlledAcquisitionPlanTests(unittest.TestCase):
    def test_plan_is_complete_and_has_no_side_effect_flags(self):
        registry = {
            "sources": [
                {
                    "source_id": "EUROSTAT_MACRO",
                    "name": "Eurostat",
                    "category": "ECONOMIC_DATA",
                    "topics": ["EUR"],
                    "enabled": True,
                    "auto_fetch": False,
                    "products": [{"product_id": "EA_HICP", "unit": "index"}],
                },
                {
                    "source_id": "LBMA_INTERMARKET",
                    "name": "LBMA",
                    "category": "FINANCIAL_MARKETS",
                    "topics": ["gold"],
                    "enabled": True,
                    "auto_fetch": False,
                    "products": [{"product_id": "GOLD", "unit": "usd"}],
                },
            ]
        }
        plan = build_acquisition_plan(registry)
        self.assertEqual(plan["registered_source_count"], 2)
        self.assertEqual(plan["registered_product_count"], 2)
        self.assertEqual(plan["network_requests_made"], 0)
        self.assertFalse(plan["databases_created_or_mutated"])
        self.assertFalse(plan["automatic_fetch_enabled"])
        self.assertEqual(
            plan["domains"]["macro_fundamentals"][0]["pit_readiness"],
            "FORWARD_SNAPSHOTS_ONLY",
        )
        self.assertEqual(
            plan["domains"]["intermarket"][0]["pit_readiness"],
            "LICENSE_REVIEW_REQUIRED",
        )

    def test_validated_repository_registry_produces_full_nine_source_plan(self):
        plan = build_acquisition_plan_from_paths()
        self.assertEqual(plan["registered_source_count"], 9)
        self.assertEqual(plan["registered_product_count"], 23)
        self.assertEqual(plan["enabled_product_count"], 23)
        self.assertEqual(plan["network_requests_made"], 0)
        self.assertEqual(
            plan["readiness_counts_by_product"]["RELEASE_TIMESTAMP_REQUIRED"], 4
        )
        self.assertEqual(
            plan["readiness_counts_by_product"]["FORWARD_SNAPSHOTS_ONLY"], 2
        )

    def test_unknown_source_fails_closed_in_plan(self):
        plan = build_acquisition_plan({
            "sources": [{
                "source_id": "UNMAPPED",
                "enabled": True,
                "auto_fetch": True,
                "products": [{"product_id": "X"}],
            }]
        })
        row = plan["domains"]["unclassified"][0]
        self.assertEqual(row["pit_readiness"], "BLOCKED_UNMAPPED_SOURCE")


class RawSnapshotArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "raw" / "snapshots.sqlite"
        self.archive = RawSnapshotArchive(
            self.path,
            allowed_products={"US_BLS_MACRO": {"US_CPI_ALL_ITEMS_INDEX"}},
            max_payload_bytes=1024,
        )
        self.args = {
            "source_id": "US_BLS_MACRO",
            "product_id": "US_CPI_ALL_ITEMS_INDEX",
            "source_url": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            "retrieved_at_utc": datetime(2026, 11, 20, 12, tzinfo=UTC),
            "http_status": 200,
            "content_type": "application/json",
            "payload": b'{"status":"REQUEST_SUCCEEDED"}',
            "response_headers": {"ETag": '"abc"', "Last-Modified": "Fri, 20 Nov 2026 12:00:00 GMT"},
            "request_metadata": {"startyear": "2025", "endyear": "2026"},
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_payload_is_preserved_with_hash_and_transport_metadata(self):
        result = self.archive.append(**self.args)
        self.assertTrue(result.inserted)
        self.assertEqual(result.payload_sha256, __import__("hashlib").sha256(self.args["payload"]).hexdigest())
        self.assertEqual(self.archive.get_payload(result.snapshot_id), self.args["payload"])
        row = self.archive.list_snapshots()[0]
        self.assertEqual(row["etag"], '"abc"')
        self.assertEqual(row["request_metadata"]["startyear"], "2025")

    def test_identical_snapshot_is_idempotent(self):
        first = self.archive.append(**self.args)
        second = self.archive.append(**self.args)
        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(len(self.archive.list_snapshots()), 1)

    def test_new_retrieval_of_revised_payload_appends_a_new_snapshot(self):
        first = self.archive.append(**self.args)
        revised = dict(self.args)
        revised["retrieved_at_utc"] = datetime(2026, 11, 21, 12, tzinfo=UTC)
        revised["payload"] = b'{"status":"REQUEST_SUCCEEDED","revision":2}'
        second = self.archive.append(**revised)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(len(self.archive.list_snapshots()), 2)

    def test_registry_factory_excludes_disabled_sources(self):
        registry = {
            "sources": [
                {
                    "source_id": "US_BLS_MACRO", "enabled": True,
                    "products": [{"product_id": "US_CPI_ALL_ITEMS_INDEX"}],
                },
                {
                    "source_id": "DISABLED", "enabled": False,
                    "products": [{"product_id": "SECRET_PRODUCT"}],
                },
            ]
        }
        archive = RawSnapshotArchive.from_registry(
            Path(self.temp.name) / "registry.sqlite", registry=registry
        )
        with self.assertRaises(ValueError):
            archive.append(**{**self.args, "source_id": "DISABLED", "product_id": "SECRET_PRODUCT"})

    def test_sensitive_url_and_metadata_values_are_redacted(self):
        result = self.archive.append(**{
            **self.args,
            "source_url": "https://api.bls.gov/data?series=CUUR0000SA0&api-key=supersecret",
            "request_metadata": {"api_key": "supersecret", "startyear": "2025"},
            "response_headers": {"ETag": "abc", "Set-Cookie": "session=secret", "X-API-Key": "also-secret"},
        })
        row = self.archive.list_snapshots()[0]
        self.assertIn("api-key=%3Credacted%3E", row["source_url"])
        self.assertEqual(row["request_metadata"]["api_key"], "<redacted>")
        self.assertEqual(row["response_headers"]["Set-Cookie"], "<redacted>")
        self.assertEqual(row["response_headers"]["X-API-Key"], "<redacted>")

    def test_unregistered_source_product_is_rejected(self):
        with self.assertRaises(ValueError):
            self.archive.append(**{**self.args, "product_id": "NOT_REGISTERED"})

    def test_non_https_or_failed_response_is_rejected(self):
        with self.assertRaises(ValueError):
            self.archive.append(**{**self.args, "source_url": "http://api.bls.gov/x"})
        with self.assertRaises(ValueError):
            self.archive.append(**{**self.args, "http_status": 500})

    def test_oversized_or_empty_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            self.archive.append(**{**self.args, "payload": b""})
        with self.assertRaises(ValueError):
            self.archive.append(**{**self.args, "payload": b"x" * 1025})

    def test_naive_retrieval_time_is_rejected(self):
        with self.assertRaises(ValueError):
            self.archive.append(**{
                **self.args, "retrieved_at_utc": datetime(2026, 11, 20, 12)
            })

    def test_append_only_database_rejects_update_and_delete(self):
        result = self.archive.append(**self.args)
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE raw_snapshots SET content_type='text/plain' WHERE snapshot_id=?",
                    (result.snapshot_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM raw_snapshots WHERE snapshot_id=?",
                    (result.snapshot_id,),
                )
        finally:
            connection.close()


if ( __name__ == "__main__"):
    unittest.main()

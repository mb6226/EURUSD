import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from source_registry.adapters.models import FetchResult, Observation
from source_registry.data_plane import PointInTimeDataPlane
from source_registry.observation_store import PointInTimeObservationStore

UTC = timezone.utc
AS_OF = datetime(2026, 5, 5, 12, tzinfo=UTC)


def stamp(day):
    return datetime(2026, 5, day, 9, tzinfo=UTC)


def observation(source, product, value, day, published_day=None):
    return Observation(
        source_id=source,
        product_id=product,
        value=Decimal(value),
        unit="index_points",
        effective_at_utc=stamp(day),
        published_at_utc=stamp(published_day if published_day is not None else day),
        source_record_id=f"{product}:{day}",
    )


def fetch(store, item):
    result = FetchResult(
        source_id=item.source_id,
        product_id=item.product_id,
        observations=(item,),
        source_url="https://example.test/data",
        record_count=1,
        retrieved_at_utc=stamp(4),
    )
    store.persist_fetch_result(result)


class PointInTimeDataPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "observations.sqlite"
        self.writer = PointInTimeObservationStore(self.db)
        self.registry = {
            "schema_version": 1,
            "sources": [
                {
                    "source_id": "ECB_POLICY_RATES",
                    "name": "ECB rates",
                    "category": "MONETARY_POLICY",
                    "topics": ["EUR", "policy_rate"],
                    "enabled": True,
                    "auto_fetch": False,
                    "products": [{"product_id": "ECB_DEPOSIT", "unit": "percent"}],
                },
                {
                    "source_id": "US_BLS_MACRO",
                    "name": "US macro",
                    "category": "ECONOMIC_DATA",
                    "topics": ["USD", "inflation"],
                    "enabled": True,
                    "auto_fetch": False,
                    "products": [{"product_id": "US_CPI", "unit": "index"}],
                },
                {
                    "source_id": "CFTC_TFF_POSITIONING",
                    "name": "CFTC positioning",
                    "category": "FINANCIAL_MARKETS",
                    "topics": ["COT", "futures_positioning"],
                    "enabled": True,
                    "auto_fetch": False,
                    "products": [{"product_id": "EURO_NET", "unit": "percent"}],
                },
                {
                    "source_id": "FRED_INTERMARKET",
                    "name": "FRED",
                    "category": "FINANCIAL_MARKETS",
                    "topics": ["rates", "equities"],
                    "enabled": True,
                    "auto_fetch": False,
                    "products": [{"product_id": "US_10Y", "unit": "percent"}],
                },
                {
                    "source_id": "DISABLED_SOURCE",
                    "name": "Disabled",
                    "category": "ECONOMIC_DATA",
                    "topics": [],
                    "enabled": False,
                    "auto_fetch": False,
                    "products": [{"product_id": "DISABLED_PRODUCT", "unit": "x"}],
                },
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_registry_products_are_grouped_into_distinct_market_domains(self):
        plane = PointInTimeDataPlane(
            registry=self.registry,
            observation_store=PointInTimeObservationStore.open_read_only(self.db),
        )
        requests = plane.build_observation_requests()
        self.assertEqual(set(requests), {
            "monetary_policy", "macro_fundamentals",
            "positioning_sentiment", "intermarket",
        })
        self.assertNotIn(("DISABLED_SOURCE", "DISABLED_PRODUCT"),
                         [pair for pairs in requests.values() for pair in pairs])

    def test_single_batched_as_of_read_reports_per_product_and_domain_coverage(self):
        fetch(self.writer, observation("ECB_POLICY_RATES", "ECB_DEPOSIT", "2.5", 1))
        fetch(self.writer, observation("CFTC_TFF_POSITIONING", "EURO_NET", "12.0", 2))
        plane = PointInTimeDataPlane(
            registry=self.registry,
            observation_store=PointInTimeObservationStore.open_read_only(self.db),
        )
        report = plane.read_as_of(AS_OF)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["enabled_product_count"], 4)
        self.assertEqual(report["disabled_product_count"], 1)
        self.assertEqual(report["available_product_count"], 2)
        self.assertEqual(report["observation_count"], 2)
        self.assertEqual(report["domains"]["monetary_policy"]["status"], "AVAILABLE")
        self.assertEqual(report["domains"]["macro_fundamentals"]["status"], "MISSING")
        self.assertEqual(
            report["domains"]["positioning_sentiment"]["products"][0]["observations"][0]["value"],
            "12.0",
        )
        self.assertTrue(report["policy"]["unknown_publication_excluded"])
        self.assertFalse(report["policy"]["automatic_fetch"])

    def test_future_published_observation_is_not_visible_at_cutoff(self):
        future = Observation(
            source_id="ECB_POLICY_RATES",
            product_id="ECB_DEPOSIT",
            value=Decimal("3.0"),
            unit="percent",
            effective_at_utc=stamp(2),
            published_at_utc=datetime(2026, 5, 6, 9, tzinfo=UTC),
            source_record_id="future-release",
        )
        fetch(self.writer, future)
        plane = PointInTimeDataPlane(
            registry=self.registry,
            observation_store=PointInTimeObservationStore.open_read_only(self.db),
        )
        report = plane.read_as_of(AS_OF)
        self.assertEqual(report["available_product_count"], 0)
        self.assertEqual(report["status"], "MISSING")

    def test_missing_database_is_not_created_by_from_paths(self):
        from source_registry.registry_loader import DEFAULT_REGISTRY_PATH, DEFAULT_SCHEMA_DIR

        missing = Path(self.temp.name) / "not-created.sqlite"
        plane = PointInTimeDataPlane.from_paths(
            registry_path=DEFAULT_REGISTRY_PATH,
            schema_dir=DEFAULT_SCHEMA_DIR,
            observation_db_path=missing,
            market_db_path=Path(self.temp.name) / "missing-market.sqlite",
        )
        report = plane.read_as_of(AS_OF)
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertEqual(report["store_status"], "NOT_CONFIGURED")
        self.assertEqual(report["enabled_product_count"], 23)
        self.assertFalse(missing.exists())

    def test_writer_store_is_rejected_to_preserve_read_only_boundary(self):
        with self.assertRaises(ValueError):
            PointInTimeDataPlane(
                registry=self.registry,
                observation_store=self.writer,
            )

    def test_public_availability_mode_is_explicit_and_unattested_products_stay_missing(self):
        from source_registry.historical_availability import HistoricalAvailabilityLedger
        ledger = HistoricalAvailabilityLedger(Path(self.temp.name) / "attestations.sqlite")
        plane = PointInTimeDataPlane(
            registry=self.registry,
            observation_store=PointInTimeObservationStore.open_read_only(self.db),
        )
        report = plane.read_public_availability_as_of(AS_OF, ledger=ledger)
        self.assertEqual(report["read_mode"], "RECONSTRUCTED_PUBLIC_AVAILABILITY")
        self.assertEqual(report["status"], "MISSING")
        self.assertTrue(report["policy"]["requires_per_observation_attestation"])
        self.assertFalse(report["policy"]["retrieval_time_filter_bypassed"])

    def test_naive_as_of_is_rejected(self):
        plane = PointInTimeDataPlane(
            registry=self.registry,
            observation_store=None,
        )
        with self.assertRaises(ValueError):
            plane.read_as_of(datetime(2026, 5, 5, 12))


if __name__ == "__main__":
    unittest.main()

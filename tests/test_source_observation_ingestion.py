import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from source_registry.adapters.models import FetchRequest, FetchResult, Observation
from source_registry.ingestion import (
    AdapterNotRegisteredError,
    IngestionValidationError,
    ProductNotRegisteredError,
    SourceDisabledError,
    SourceNotRegisteredError,
    SourceObservationIngestion,
)
from source_registry.observation_store import PointInTimeObservationStore

UTC = timezone.utc
RETRIEVED = datetime(2026, 2, 2, 12, tzinfo=UTC)
PUBLISHED = datetime(2026, 2, 1, 9, tzinfo=UTC)
EFFECTIVE = datetime(2026, 2, 1, 0, tzinfo=UTC)


def make_result(source_id="TEST_SOURCE", product_id="TEST_RATE"):
    observation = Observation(
        source_id=source_id,
        product_id=product_id,
        value=Decimal("3.75"),
        unit="percent_per_annum",
        effective_at_utc=EFFECTIVE,
        published_at_utc=PUBLISHED,
        source_record_id="RATE_2026_02",
    )
    return FetchResult(
        source_id=source_id,
        product_id=product_id,
        observations=(observation,),
        source_url="https://example.test/rates",
        record_count=1,
    )


class FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else make_result()
        self.error = error
        self.requests = []

    def fetch(self, request: FetchRequest) -> FetchResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


class SourceObservationIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PointInTimeObservationStore(
            Path(self.temp.name) / "observations.sqlite"
        )
        self.registry = {
            "schema_version": 1,
            "sources": [{
                "source_id": "TEST_SOURCE",
                "enabled": True,
                "products": [{"product_id": "TEST_RATE"}],
            }],
        }
        self.adapter = FakeAdapter()
        self.service = SourceObservationIngestion(
            registry=self.registry,
            adapters={("TEST_SOURCE", "TEST_RATE"): self.adapter},
            store=self.store,
            clock=lambda: RETRIEVED,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_fetch_stamps_retrieval_time_and_persists(self):
        summary = self.service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(summary.observations_received, 1)
        self.assertEqual(summary.persistence.observations_inserted, 1)
        self.assertEqual(summary.retrieved_at_utc, RETRIEVED)
        rows = self.store.get_as_of(
            "TEST_SOURCE", "TEST_RATE", RETRIEVED
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["retrieved_at_utc"], "2026-02-02T12:00:00.000000Z")
        self.assertEqual(rows[0]["value"], "3.75")

    def test_since_is_forwarded_to_adapter(self):
        since = datetime(2026, 1, 1, tzinfo=UTC)
        self.service.ingest("TEST_SOURCE", "TEST_RATE", since=since)
        self.assertEqual(self.adapter.requests[0].since, since)

    def test_identical_ingestion_is_idempotent(self):
        first = self.service.ingest("TEST_SOURCE", "TEST_RATE")
        second = self.service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(first.persistence.observations_inserted, 1)
        self.assertEqual(second.persistence.observations_unchanged, 1)
        self.assertEqual(self.store.count_observations(), 1)

    def test_unknown_source_fails_before_adapter(self):
        with self.assertRaises(SourceNotRegisteredError):
            self.service.ingest("UNKNOWN", "TEST_RATE")
        self.assertEqual(self.adapter.requests, [])
        self.assertEqual(self.store.count_observations(), 0)

    def test_disabled_source_fails_closed(self):
        self.registry["sources"][0]["enabled"] = False
        service = SourceObservationIngestion(
            registry=self.registry,
            adapters={("TEST_SOURCE", "TEST_RATE"): self.adapter},
            store=self.store,
            clock=lambda: RETRIEVED,
        )
        with self.assertRaises(SourceDisabledError):
            service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(self.adapter.requests, [])
        self.assertEqual(self.store.count_observations(), 0)

    def test_unregistered_product_fails_before_adapter(self):
        with self.assertRaises(ProductNotRegisteredError):
            self.service.ingest("TEST_SOURCE", "UNKNOWN_PRODUCT")
        self.assertEqual(self.adapter.requests, [])

    def test_missing_adapter_fails_closed(self):
        service = SourceObservationIngestion(
            registry=self.registry,
            adapters={},
            store=self.store,
            clock=lambda: RETRIEVED,
        )
        with self.assertRaises(AdapterNotRegisteredError):
            service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(self.store.count_observations(), 0)

    def test_adapter_result_identity_must_match_request(self):
        wrong = FakeAdapter(result=make_result("OTHER_SOURCE", "OTHER_RATE"))
        service = SourceObservationIngestion(
            registry=self.registry,
            adapters={("TEST_SOURCE", "TEST_RATE"): wrong},
            store=self.store,
            clock=lambda: RETRIEVED,
        )
        with self.assertRaises(IngestionValidationError):
            service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(self.store.count_observations(), 0)

    def test_non_fetch_result_is_rejected(self):
        adapter = FakeAdapter(result={"not": "a FetchResult"})
        service = SourceObservationIngestion(
            registry=self.registry,
            adapters={("TEST_SOURCE", "TEST_RATE"): adapter},
            store=self.store,
            clock=lambda: RETRIEVED,
        )
        with self.assertRaises(IngestionValidationError):
            service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(self.store.count_observations(), 0)

    def test_naive_ingestion_clock_is_rejected_before_persist(self):
        service = SourceObservationIngestion(
            registry=self.registry,
            adapters={("TEST_SOURCE", "TEST_RATE"): self.adapter},
            store=self.store,
            clock=lambda: datetime(2026, 2, 2, 12),
        )
        with self.assertRaises(ValueError):
            service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(self.store.count_observations(), 0)

    def test_publication_after_retrieval_is_rejected_as_lookahead(self):
        future = Observation(
            source_id="TEST_SOURCE",
            product_id="TEST_RATE",
            value=Decimal("4.00"),
            unit="percent_per_annum",
            effective_at_utc=EFFECTIVE,
            published_at_utc=datetime(2026, 2, 3, 9, tzinfo=UTC),
            source_record_id="RATE_FUTURE_PUBLICATION",
        )
        adapter = FakeAdapter(result=FetchResult(
            source_id="TEST_SOURCE",
            product_id="TEST_RATE",
            observations=(future,),
            source_url="https://example.test/rates",
            record_count=1,
        ))
        service = SourceObservationIngestion(
            registry=self.registry,
            adapters={("TEST_SOURCE", "TEST_RATE"): adapter},
            store=self.store,
            clock=lambda: RETRIEVED,
        )
        with self.assertRaises(IngestionValidationError):
            service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(self.store.count_observations(), 0)

    def test_adapter_failure_propagates_without_persisting(self):
        failure = RuntimeError("provider unavailable")
        adapter = FakeAdapter(error=failure)
        service = SourceObservationIngestion(
            registry=self.registry,
            adapters={("TEST_SOURCE", "TEST_RATE"): adapter},
            store=self.store,
            clock=lambda: RETRIEVED,
        )
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            service.ingest("TEST_SOURCE", "TEST_RATE")
        self.assertEqual(self.store.count_observations(), 0)


if __name__ == "__main__":
    unittest.main()

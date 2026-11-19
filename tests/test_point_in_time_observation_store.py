import sqlite3
from contextlib import closing
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from source_registry.adapters.models import FetchResult, Observation
from source_registry.observation_store import PointInTimeObservationStore

UTC = timezone.utc


def stamp(day, hour=0):
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def result(value, retrieved, published=stamp(1), record_id="GDP_Q1"):
    observation = Observation(
        source_id="TEST_SOURCE",
        product_id="TEST_PRODUCT",
        value=Decimal(value),
        unit="index",
        effective_at_utc=stamp(1),
        published_at_utc=published,
        source_record_id=record_id,
    )
    return FetchResult(
        source_id="TEST_SOURCE",
        product_id="TEST_PRODUCT",
        observations=(observation,),
        source_url="https://example.com/data",
        record_count=1,
        retrieved_at_utc=retrieved,
    )


class PointInTimeObservationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PointInTimeObservationStore(
            Path(self.temp.name) / "observations.sqlite"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_persists_and_returns_published_observation_as_of(self):
        summary = self.store.persist_fetch_result(result("101.2", stamp(2)))
        rows = self.store.get_as_of("TEST_SOURCE", "TEST_PRODUCT", stamp(3))
        self.assertEqual(summary.observations_inserted, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], "101.2")
        self.assertEqual(rows[0]["source_url"], "https://example.com/data")

    def test_excludes_data_retrieved_after_as_of(self):
        self.store.persist_fetch_result(result("101.2", stamp(4)))
        self.assertEqual(
            self.store.get_as_of("TEST_SOURCE", "TEST_PRODUCT", stamp(3)),
            [],
        )

    def test_excludes_data_not_yet_published_at_as_of(self):
        self.store.persist_fetch_result(
            result("101.2", stamp(3), published=stamp(4))
        )
        self.assertEqual(
            self.store.get_as_of("TEST_SOURCE", "TEST_PRODUCT", stamp(3)),
            [],
        )

    def test_unknown_publication_time_is_excluded_by_default(self):
        self.store.persist_fetch_result(
            result("101.2", stamp(2), published=None)
        )
        self.assertEqual(
            self.store.get_as_of("TEST_SOURCE", "TEST_PRODUCT", stamp(3)),
            [],
        )
        rows = self.store.get_as_of(
            "TEST_SOURCE", "TEST_PRODUCT", stamp(3),
            include_unknown_publication=True,
        )
        self.assertEqual(len(rows), 1)

    def test_revised_value_is_append_only_and_as_of_selects_correct_version(self):
        self.store.persist_fetch_result(result("100.0", stamp(2)))
        self.store.persist_fetch_result(result("101.0", stamp(4)))
        before_revision = self.store.get_as_of(
            "TEST_SOURCE", "TEST_PRODUCT", stamp(3)
        )
        after_revision = self.store.get_as_of(
            "TEST_SOURCE", "TEST_PRODUCT", stamp(5)
        )
        self.assertEqual(before_revision[0]["value"], "100.0")
        self.assertEqual(after_revision[0]["value"], "101.0")
        self.assertEqual(after_revision[0]["version"], 2)
        self.assertEqual(self.store.count_observations(), 2)

    def test_identical_fetch_is_idempotent(self):
        item = result("101.2", stamp(2))
        first = self.store.persist_fetch_result(item)
        second = self.store.persist_fetch_result(item)
        self.assertEqual(first.observations_inserted, 1)
        self.assertEqual(second.observations_unchanged, 1)
        self.assertEqual(self.store.count_observations(), 1)

    def test_same_payload_fetched_later_is_not_a_data_revision(self):
        self.store.persist_fetch_result(result("101.2", stamp(2)))
        summary = self.store.persist_fetch_result(result("101.2", stamp(4)))
        self.assertEqual(summary.observations_unchanged, 1)
        self.assertEqual(summary.observations_revised, 0)
        self.assertEqual(self.store.count_observations(), 1)
        rows = self.store.get_as_of("TEST_SOURCE", "TEST_PRODUCT", stamp(5))
        self.assertEqual(rows[0]["retrieved_at_utc"], "2026-01-02T00:00:00.000000Z")

    def test_revision_counts_are_reported(self):
        self.store.persist_fetch_result(result("100.0", stamp(2)))
        summary = self.store.persist_fetch_result(result("101.0", stamp(4)))
        self.assertEqual(summary.observations_revised, 1)
        self.assertEqual(summary.observations_inserted, 1)

    def test_future_effective_observation_is_excluded_by_default(self):
        future = Observation(
            source_id="TEST_SOURCE",
            product_id="TEST_PRODUCT",
            value=Decimal("105"),
            unit="index",
            effective_at_utc=stamp(5),
            published_at_utc=stamp(2),
            source_record_id="FUTURE",
        )
        item = FetchResult(
            source_id="TEST_SOURCE", product_id="TEST_PRODUCT",
            observations=(future,), source_url="https://example.com/data",
            record_count=1, retrieved_at_utc=stamp(2),
        )
        self.store.persist_fetch_result(item)
        self.assertEqual(
            self.store.get_as_of("TEST_SOURCE", "TEST_PRODUCT", stamp(3)),
            [],
        )
        self.assertEqual(
            len(self.store.get_as_of(
                "TEST_SOURCE", "TEST_PRODUCT", stamp(3),
                include_future_effective=True,
            )),
            1,
        )

    def test_naive_as_of_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.get_as_of(
                "TEST_SOURCE", "TEST_PRODUCT", datetime(2026, 1, 3)
            )

    def test_invalid_result_is_rejected(self):
        invalid = FetchResult(
            source_id="TEST_SOURCE", product_id="TEST_PRODUCT",
            observations=(), source_url="https://example.com/data",
            record_count=0,
        )
        with self.assertRaises(ValueError):
            self.store.persist_fetch_result(invalid)

    def test_append_only_guards_prevent_update_and_delete(self):
        self.store.persist_fetch_result(result("101.2", stamp(2)))
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE observations SET unit='changed'")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM observations")

    def test_separate_sources_and_products_do_not_collide(self):
        self.store.persist_fetch_result(result("101.2", stamp(2)))
        other = Observation(
            source_id="OTHER_SOURCE", product_id="OTHER_PRODUCT",
            value=Decimal("9"), unit="index", effective_at_utc=stamp(1),
            published_at_utc=stamp(1), source_record_id="GDP_Q1",
        )
        self.store.persist_fetch_result(FetchResult(
            source_id="OTHER_SOURCE", product_id="OTHER_PRODUCT",
            observations=(other,), source_url="https://example.org/data",
            record_count=1, retrieved_at_utc=stamp(2),
        ))
        self.assertEqual(self.store.count_observations(), 2)


if __name__ == "__main__":
    unittest.main()

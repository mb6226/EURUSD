from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from source_registry.adapters.models import FetchResult, Observation
from source_registry.data_quality import assess_product_quality, assess_registry_quality
from source_registry.observation_store import PointInTimeObservationStore

UTC = timezone.utc
AS_OF = datetime(2026, 11, 20, 12, tzinfo=UTC)


def row(value="1.25", *, unit="percent", effective="2026-11-19T00:00:00Z", published="2026-11-19T12:00:00Z", retrieved="2026-11-19T12:05:00Z", key="natural:test", version=1):
    return {"source_id":"TEST", "product_id":"RATE", "observation_key":key,
            "version":version, "effective_at_utc":effective,
            "published_at_utc":published, "retrieved_at_utc":retrieved,
            "value":value, "unit":unit}


PRODUCT = {"product_id":"RATE", "unit":"percent", "observation_frequency":"DAILY"}


class DataQualityTests(unittest.TestCase):
    def test_valid_fresh_record_passes(self):
        result = assess_product_quality(PRODUCT, [row()], as_of_utc=AS_OF)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["eligible_for_downstream_analytics"])
        self.assertEqual(result["quality_score"], 100)

    def test_unknown_publication_time_blocks_even_if_value_is_present(self):
        result = assess_product_quality(PRODUCT, [row(published=None)], as_of_utc=AS_OF)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("PUBLICATION_TIME_UNVERIFIED", {x["code"] for x in result["issues"]})
        self.assertFalse(result["eligible_for_downstream_analytics"])

    def test_unit_mismatch_blocks(self):
        result = assess_product_quality(PRODUCT, [row(unit="basis_points")], as_of_utc=AS_OF)
        self.assertIn("UNIT_MISMATCH", {x["code"] for x in result["issues"]})
        self.assertEqual(result["status"], "BLOCKED")

    def test_future_effective_publication_or_retrieval_time_blocks(self):
        cases = [
            row(effective="2026-11-21T00:00:00Z"),
            row(published="2026-11-21T00:00:00Z", retrieved="2026-11-21T00:05:00Z"),
            row(retrieved="2026-11-21T00:05:00Z"),
        ]
        for item in cases:
            with self.subTest(item=item):
                result = assess_product_quality(PRODUCT, [item], as_of_utc=AS_OF)
                self.assertEqual(result["status"], "BLOCKED")

    def test_retrieval_before_publication_blocks(self):
        result = assess_product_quality(PRODUCT, [row(published="2026-11-19T12:00:00Z", retrieved="2026-11-19T11:00:00Z")], as_of_utc=AS_OF)
        self.assertIn("RETRIEVED_BEFORE_PUBLICATION", {x["code"] for x in result["issues"]})

    def test_invalid_nonfinite_and_reversed_range_values_block(self):
        for value in ("NaN", "Infinity", {"low":"2", "high":"1"}, {"unexpected":"3"}):
            with self.subTest(value=value):
                result = assess_product_quality(PRODUCT, [row(value=value)], as_of_utc=AS_OF)
                self.assertIn("NONFINITE_OR_INVALID_VALUE", {x["code"] for x in result["issues"]})

    def test_stale_daily_product_is_warning_and_not_eligible(self):
        result = assess_product_quality(PRODUCT, [row(effective="2026-11-01T00:00:00Z", published="2026-11-01T12:00:00Z", retrieved="2026-11-01T12:05:00Z")], as_of_utc=AS_OF)
        self.assertEqual(result["status"], "STALE")
        self.assertFalse(result["eligible_for_downstream_analytics"])
        self.assertIn("STALE_PRODUCT", {x["code"] for x in result["issues"]})

    def test_missing_observations_block(self):
        result = assess_product_quality(PRODUCT, [], as_of_utc=AS_OF)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("NO_OBSERVATIONS", {x["code"] for x in result["issues"]})

    def test_revision_summary_counts_changed_versions_and_delta(self):
        history = [
            row("1.20", key="record:x", version=1, retrieved="2026-11-19T12:05:00Z"),
            row("1.25", key="record:x", version=2, retrieved="2026-11-20T10:05:00Z"),
        ]
        result = assess_product_quality(PRODUCT, [history[-1]], as_of_utc=AS_OF, revision_history=history)
        self.assertEqual(result["revision_history"]["observation_keys_with_revisions"], 1)
        self.assertEqual(result["revision_history"]["revision_count"], 1)
        self.assertEqual(result["revision_history"]["max_absolute_value_delta"], "0.05")

    def test_registry_quality_report_is_deterministic_and_does_not_mutate_inputs(self):
        registry = {"sources":[{"source_id":"TEST", "enabled":True, "products":[PRODUCT]}]}
        observations = {("TEST", "RATE"):[row()]}
        before = repr((registry, observations))
        first = assess_registry_quality(registry, observations, as_of_utc=AS_OF)
        second = assess_registry_quality(registry, observations, as_of_utc=AS_OF)
        self.assertEqual(first, second)
        self.assertEqual(repr((registry, observations)), before)
        self.assertTrue(first["policy"]["no_database_mutation"])
        self.assertTrue(first["policy"]["quality_gate_not_yet_wired_into_fusion"])

    def test_store_revision_history_preserves_both_versions_and_as_of_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PointInTimeObservationStore(Path(directory) / "observations.sqlite")
            def persist(value, retrieved):
                observation = Observation("TEST", "RATE", Decimal(value), "percent",
                    datetime(2026, 11, 19, tzinfo=UTC), datetime(2026, 11, 19, 11, tzinfo=UTC), "same-record")
                store.persist_fetch_result(FetchResult("TEST", "RATE", (observation,),
                    "https://example.com/rates", 1, retrieved))
            persist("1.20", datetime(2026, 11, 19, 12, tzinfo=UTC))
            persist("1.25", datetime(2026, 11, 20, 10, tzinfo=UTC))
            history = store.get_revision_history("TEST", "RATE")
            earlier = store.get_revision_history("TEST", "RATE", as_of_utc=datetime(2026, 11, 20, 9, tzinfo=UTC))
            self.assertEqual([x["version"] for x in history], [1, 2])
            self.assertEqual(len(earlier), 1)
            self.assertEqual(earlier[0]["value"], "1.20")


if __name__ == "__main__":
    unittest.main()

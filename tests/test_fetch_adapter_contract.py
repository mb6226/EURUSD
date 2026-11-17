import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from source_registry.adapters import (
    DecimalRange,
    FetchAdapter,
    FetchRequest,
    FetchResult,
    Observation,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FETCH_RESULT_SCHEMA = (
    PROJECT_ROOT
    / "source_registry"
    / "schemas"
    / "fetch_result.schema.json"
)


class FetchAdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(FETCH_RESULT_SCHEMA.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(
            self.schema,
            format_checker=FormatChecker(),
        )

    def make_observation(self, **overrides):
        values = {
            "source_id": "ECB_POLICY_RATES",
            "product_id": "ECB_MAIN_REFINANCING_RATE",
            "value": Decimal("2.1500"),
            "unit": "percent_per_annum",
            "effective_at_utc": datetime(
                2026, 11, 1, tzinfo=timezone.utc
            ),
            "published_at_utc": None,
            "source_record_id": None,
        }
        values.update(overrides)
        return Observation(**values)

    def make_result(self, observations=None, **overrides):
        observations = (
            (self.make_observation(),)
            if observations is None
            else tuple(observations)
        )
        values = {
            "source_id": "ECB_POLICY_RATES",
            "product_id": "ECB_MAIN_REFINANCING_RATE",
            "observations": observations,
            "retrieved_at_utc": datetime(
                2026, 11, 17, 12, tzinfo=timezone.utc
            ),
            "source_url": "https://www.ecb.europa.eu/example",
            "record_count": len(observations),
        }
        values.update(overrides)
        return FetchResult(**values)

    def test_execution_layer_stamps_retrieval_time(self):
        result = FetchResult(
            source_id="ECB_POLICY_RATES",
            product_id="ECB_MAIN_REFINANCING_RATE",
            observations=(self.make_observation(),),
            source_url="https://www.ecb.europa.eu/example",
            record_count=1,
        )

        with self.assertRaisesRegex(ValueError, "execution layer"):
            result.to_dict()

        retrieved_at = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        stamped = result.with_retrieved_at(retrieved_at)

        self.assertIsNone(result.retrieved_at_utc)
        self.assertEqual(stamped.retrieved_at_utc, retrieved_at)
        self.assertEqual(
            stamped.to_dict()["retrieved_at_utc"],
            "2026-11-17T12:00:00.000000Z",
        )

    def test_decimal_is_preserved_and_serialized_as_exact_string(self):
        observation = self.make_observation(value=Decimal("2.1500"))
        result = self.make_result((observation,))

        self.assertIsInstance(observation.value, Decimal)
        self.assertEqual(result.to_dict()["observations"][0]["value"], "2.1500")
        self.assertIsInstance(result.to_dict()["observations"][0]["value"], str)

    def test_float_values_are_rejected(self):
        with self.assertRaisesRegex(TypeError, "must be Decimal"):
            self.make_observation(value=2.15)

    def test_decimal_range_preserves_both_bounds(self):
        value = DecimalRange(Decimal("3.75"), Decimal("4.00"))
        observation = self.make_observation(value=value)
        result = self.make_result((observation,))
        serialized_value = result.to_dict()["observations"][0]["value"]

        self.assertEqual(value.low, Decimal("3.75"))
        self.assertEqual(value.high, Decimal("4.00"))
        self.assertEqual(serialized_value, {"low": "3.75", "high": "4.00"})
        self.validator.validate(result.to_dict())

    def test_decimal_range_rejects_reversed_or_non_decimal_bounds(self):
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            DecimalRange(Decimal("4.00"), Decimal("3.75"))
        with self.assertRaisesRegex(TypeError, "must be Decimal"):
            DecimalRange(3.75, Decimal("4.00"))
        with self.assertRaisesRegex(ValueError, "must be finite"):
            DecimalRange(Decimal("NaN"), Decimal("4.00"))

    def test_result_validation_and_serialization_reject_mutated_range(self):
        value = DecimalRange(Decimal("3.75"), Decimal("4.00"))
        observation = self.make_observation(value=value)
        result = self.make_result((observation,))
        result = result.with_retrieved_at(
            datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        )

        object.__setattr__(value, "low", Decimal("4.01"))

        with self.assertRaisesRegex(ValueError, "must not exceed"):
            result.validate()
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            result.to_dict()

    def test_non_finite_decimal_values_are_rejected(self):
        for value in (Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "must be finite"
            ):
                self.make_observation(value=value)

    def test_non_utc_aware_timestamps_are_normalized_to_utc(self):
        offset = timezone(timedelta(hours=2))
        request = FetchRequest(
            "ECB_POLICY_RATES",
            "ECB_MAIN_REFINANCING_RATE",
            datetime(2026, 11, 17, 14, tzinfo=offset),
        )
        observation = self.make_observation(
            effective_at_utc=datetime(2026, 11, 1, 2, tzinfo=offset),
            published_at_utc=datetime(2026, 10, 30, 12, tzinfo=offset),
        )
        result = self.make_result(
            (observation,),
            retrieved_at_utc=datetime(2026, 11, 17, 14, tzinfo=offset),
        )

        self.assertEqual(request.since.utcoffset(), timedelta(0))
        self.assertEqual(
            observation.effective_at_utc,
            datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
        payload = result.to_dict()
        self.assertEqual(
            payload["observations"][0]["published_at_utc"],
            "2026-10-30T10:00:00.000000Z",
        )
        self.assertEqual(
            payload["retrieved_at_utc"],
            "2026-11-17T12:00:00.000000Z",
        )

    def test_naive_timestamps_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            FetchRequest(
                "ECB_POLICY_RATES",
                "ECB_MAIN_REFINANCING_RATE",
                datetime(2026, 11, 17),
            )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.make_observation(effective_at_utc=datetime(2026, 11, 1))

    def test_published_time_remains_null_and_distinct_from_retrieval_time(self):
        result = self.make_result()
        payload = result.to_dict()

        self.assertIsNone(payload["observations"][0]["published_at_utc"])
        self.assertNotEqual(
            payload["observations"][0]["effective_at_utc"],
            payload["retrieved_at_utc"],
        )

    def test_result_rejects_mismatched_count_and_product(self):
        with self.assertRaisesRegex(ValueError, "record_count"):
            self.make_result(record_count=2)

        other_product = self.make_observation(product_id="ECB_DEPOSIT_RATE")
        with self.assertRaisesRegex(ValueError, "must match"):
            self.make_result((other_product,))

    def test_result_rejects_duplicate_observations(self):
        observation = self.make_observation(source_record_id="record-1")
        duplicate = self.make_observation(source_record_id="record-1")

        with self.assertRaisesRegex(ValueError, "duplicate observation"):
            self.make_result((observation, duplicate))

    def test_result_rejects_duplicate_natural_keys(self):
        observation = self.make_observation()
        duplicate = self.make_observation()

        with self.assertRaisesRegex(ValueError, "duplicate observation"):
            self.make_result((observation, duplicate))

    def test_serialized_result_matches_fetch_result_schema(self):
        result = self.make_result()
        self.validator.validate(result.to_dict())

    def test_schema_rejects_float_values_and_non_utc_timestamps(self):
        payload = self.make_result().to_dict()
        payload["observations"][0]["value"] = 2.15
        self.assertTrue(list(self.validator.iter_errors(payload)))

        payload = self.make_result().to_dict()
        payload["observations"][0]["value"] = {
            "low": 3.75,
            "high": "4.00",
        }
        self.assertTrue(list(self.validator.iter_errors(payload)))

        payload = self.make_result().to_dict()
        payload["retrieved_at_utc"] = "2026-11-17T12:00:00+00:00"
        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_fetch_adapter_is_a_runtime_checkable_protocol(self):
        class Adapter:
            def fetch(self, request):
                return self.make_result()

        self.assertIsInstance(Adapter(), FetchAdapter)


if __name__ == "__main__":
    unittest.main()

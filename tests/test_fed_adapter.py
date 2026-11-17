import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from source_registry.adapters import (
    FetchAdapter,
    FetchParseError,
    FetchRequest,
    FetchValidationError,
)
from source_registry.adapters.fed import (
    FED_OPEN_MARKET_URL,
    FedAdapter,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FETCH_RESULT_SCHEMA = (
    PROJECT_ROOT
    / "source_registry"
    / "schemas"
    / "fetch_result.schema.json"
)

HISTORICAL_FOMC_FIXTURE = (
    {
        "effective_date": "2024-12-19",
        "lower_bound": "4.25",
        "upper_bound": "4.50",
        "published_at_utc": None,
    },
    {
        "effective_date": "2024-11-08",
        "lower_bound": "4.50",
        "upper_bound": "4.75",
        "published_at_utc": None,
    },
    {
        "effective_date": "2024-09-19",
        "lower_bound": "4.75",
        "upper_bound": "5.00",
        "published_at_utc": None,
    },
)


class FedAdapterTests(unittest.TestCase):
    def setUp(self):
        self.request = FetchRequest(
            source_id="FED_FOMC_POLICY",
            product_id="FED_TARGET_RANGE",
        )

    def test_normalizes_sample_target_range_without_network(self):
        sample_rows = [
            {
                "effective_date": "2026-10-29",
                "lower_bound": "3.75",
                "upper_bound": "4.00",
                "published_at_utc": None,
                "source_record_id": "sample-fomc-2026-10-28",
            }
        ]
        calls = []

        def sample_provider(request):
            calls.append(request)
            return sample_rows

        adapter = FedAdapter(sample_provider)
        result = adapter.fetch(self.request)
        observation = result.observations[0]

        self.assertIsInstance(adapter, FetchAdapter)
        self.assertEqual(calls, [self.request])
        self.assertEqual(result.source_url, FED_OPEN_MARKET_URL)
        self.assertEqual(result.record_count, 1)
        self.assertIsNone(result.retrieved_at_utc)
        self.assertEqual(observation.value.low, Decimal("3.75"))
        self.assertEqual(observation.value.high, Decimal("4.00"))
        self.assertEqual(
            observation.effective_at_utc,
            datetime(2026, 10, 29, tzinfo=timezone.utc),
        )
        self.assertIsNone(observation.published_at_utc)
        self.assertEqual(
            observation.source_record_id,
            "sample-fomc-2026-10-28",
        )

        stamped = result.with_retrieved_at(
            datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        )
        payload = stamped.to_dict()
        schema = json.loads(FETCH_RESULT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).validate(payload)
        self.assertEqual(
            payload["observations"][0]["value"],
            {"low": "3.75", "high": "4.00"},
        )

    def test_preserves_publication_time_separately_from_effective_date(self):
        adapter = FedAdapter(
            lambda request: [
                {
                    "effective_date": "2026-10-29",
                    "lower_bound": "3.75",
                    "upper_bound": "4.00",
                    "published_at_utc": "2026-10-28T18:00:00Z",
                }
            ]
        )

        observation = adapter.fetch(self.request).observations[0]

        self.assertEqual(
            observation.effective_at_utc,
            datetime(2026, 10, 29, tzinfo=timezone.utc),
        )
        self.assertEqual(
            observation.published_at_utc,
            datetime(2026, 10, 28, 18, tzinfo=timezone.utc),
        )

    def test_orders_historical_fomc_changes_chronologically(self):
        adapter = FedAdapter(lambda request: HISTORICAL_FOMC_FIXTURE)

        result = adapter.fetch(self.request)
        observations = result.observations

        self.assertEqual(
            [item.effective_at_utc.date().isoformat() for item in observations],
            ["2024-09-19", "2024-11-08", "2024-12-19"],
        )
        self.assertEqual(
            [(item.value.low, item.value.high) for item in observations],
            [
                (Decimal("4.75"), Decimal("5.00")),
                (Decimal("4.50"), Decimal("4.75")),
                (Decimal("4.25"), Decimal("4.50")),
            ],
        )
        for previous, current in zip(observations, observations[1:]):
            with self.subTest(effective_at=current.effective_at_utc):
                self.assertEqual(
                    current.value.low - previous.value.low,
                    Decimal("-0.25"),
                )
                self.assertEqual(
                    current.value.high - previous.value.high,
                    Decimal("-0.25"),
                )

    def test_rejects_unsupported_source_or_product_before_provider_call(self):
        provider_calls = []
        adapter = FedAdapter(lambda request: provider_calls.append(request) or [])

        with self.assertRaises(FetchValidationError):
            adapter.fetch(FetchRequest("ECB_POLICY_RATES", "FED_TARGET_RANGE"))
        with self.assertRaises(FetchValidationError):
            adapter.fetch(FetchRequest("FED_FOMC_POLICY", "ECB_DEPOSIT_RATE"))

        self.assertEqual(provider_calls, [])

    def test_rejects_incomplete_or_malformed_records(self):
        adapter = FedAdapter(lambda request: [{"effective_date": "2026-10-29"}])

        with self.assertRaises(FetchParseError):
            adapter.fetch(self.request)

        adapter = FedAdapter(lambda request: ["not a record"])
        with self.assertRaises(FetchParseError):
            adapter.fetch(self.request)

    def test_rejects_invalid_decimal_and_reversed_range(self):
        for row in (
            {
                "effective_date": "2026-10-29",
                "lower_bound": "not-a-number",
                "upper_bound": "4.00",
            },
            {
                "effective_date": "2026-10-29",
                "lower_bound": "4.00",
                "upper_bound": "3.75",
            },
            {
                "effective_date": "2026-10-29",
                "lower_bound": 3.75,
                "upper_bound": "4.00",
            },
        ):
            with self.subTest(row=row), self.assertRaises(
                FetchValidationError
            ):
                FedAdapter(lambda request, row=row: [row]).fetch(self.request)

    def test_rejects_duplicate_records(self):
        row = {
            "effective_date": "2026-10-29",
            "lower_bound": "3.75",
            "upper_bound": "4.00",
        }
        adapter = FedAdapter(lambda request: [row, row])

        with self.assertRaisesRegex(
            FetchValidationError,
            "Duplicate Fed target-range record for effective date",
        ):
            adapter.fetch(self.request)

    def test_rejects_conflicting_records_with_same_effective_date(self):
        rows = [
            {
                "effective_date": "2024-12-19",
                "lower_bound": "4.25",
                "upper_bound": "4.50",
            },
            {
                "effective_date": "2024-12-19",
                "lower_bound": "4.50",
                "upper_bound": "4.75",
            },
        ]

        with self.assertRaisesRegex(
            FetchValidationError,
            "Conflicting Fed target ranges for effective date 2024-12-19",
        ):
            FedAdapter(lambda request: rows).fetch(self.request)

    def test_empty_full_history_response_is_an_error(self):
        with self.assertRaisesRegex(
            FetchValidationError,
            "full-history response contains no target-range records",
        ):
            FedAdapter(lambda request: []).fetch(self.request)

    def test_empty_incremental_response_is_a_valid_empty_result(self):
        request = FetchRequest(
            source_id="FED_FOMC_POLICY",
            product_id="FED_TARGET_RANGE",
            since=datetime(2024, 12, 19, tzinfo=timezone.utc),
        )
        result = FedAdapter(lambda request: []).fetch(request)

        self.assertEqual(result.observations, ())
        self.assertEqual(result.record_count, 0)
        stamped = result.with_retrieved_at(
            datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        )
        schema = json.loads(FETCH_RESULT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).validate(stamped.to_dict())


if __name__ == "__main__":
    unittest.main()

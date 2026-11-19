import unittest
from datetime import datetime, timezone
from decimal import Decimal

from source_registry.adapters import FetchAdapter, FetchParseError, FetchRequest, FetchValidationError
from source_registry.adapters.ecb import (
    ECB_POLICY_RATES_URL,
    ECBPolicyRateAdapter,
)

UTC = timezone.utc


class ECBPolicyRateAdapterTests(unittest.TestCase):
    def setUp(self):
        self.request = FetchRequest(
            source_id="ECB_POLICY_RATES",
            product_id="ECB_DEPOSIT_FACILITY_RATE",
        )

    def test_normalizes_official_series_records_without_network(self):
        calls = []
        rows = [
            {
                "effective_date": "2024-09-18",
                "rate": "3.50",
                "published_at_utc": "2024-09-12T12:15:00Z",
                "source_record_id": "ecb-deposit-2024-09",
            },
            {
                "effective_date": "2024-10-23",
                "rate": "3.25",
                "published_at_utc": None,
                "source_record_id": "ecb-deposit-2024-10",
            },
        ]

        def provider(request):
            calls.append(request)
            return rows

        adapter = ECBPolicyRateAdapter(
            "ECB_DEPOSIT_FACILITY_RATE", provider
        )
        result = adapter.fetch(self.request)

        self.assertIsInstance(adapter, FetchAdapter)
        self.assertEqual(calls, [self.request])
        self.assertEqual(result.source_url, ECB_POLICY_RATES_URL)
        self.assertEqual(result.record_count, 2)
        self.assertIsNone(result.retrieved_at_utc)
        first, second = result.observations
        self.assertEqual(first.value, Decimal("3.50"))
        self.assertEqual(first.unit, "percent_per_annum")
        self.assertEqual(
            first.effective_at_utc,
            datetime(2024, 9, 18, tzinfo=UTC),
        )
        self.assertEqual(
            first.published_at_utc,
            datetime(2024, 9, 12, 12, 15, tzinfo=UTC),
        )
        self.assertEqual(first.source_record_id, "ecb-deposit-2024-09")
        self.assertEqual(second.value, Decimal("3.25"))
        self.assertIsNone(second.published_at_utc)

    def test_sorts_records_chronologically(self):
        adapter = ECBPolicyRateAdapter(
            "ECB_DEPOSIT_FACILITY_RATE",
            lambda request: [
                {"effective_date": "2024-10-23", "rate": "3.25"},
                {"effective_date": "2024-09-18", "rate": "3.50"},
            ],
        )
        dates = [
            item.effective_at_utc.date().isoformat()
            for item in adapter.fetch(self.request).observations
        ]
        self.assertEqual(dates, ["2024-09-18", "2024-10-23"])

    def test_supports_each_registry_product_as_a_separate_series(self):
        for product_id in (
            "ECB_DEPOSIT_FACILITY_RATE",
            "ECB_MAIN_REFINANCING_RATE",
            "ECB_MARGINAL_LENDING_RATE",
        ):
            with self.subTest(product_id=product_id):
                adapter = ECBPolicyRateAdapter(
                    product_id,
                    lambda request: [
                        {"effective_date": "2024-09-18", "rate": "3.50"}
                    ],
                )
                request = FetchRequest("ECB_POLICY_RATES", product_id)
                result = adapter.fetch(request)
                self.assertEqual(result.product_id, product_id)
                self.assertEqual(
                    result.observations[0].product_id, product_id
                )

    def test_rejects_wrong_source_or_product_before_provider_call(self):
        calls = []
        adapter = ECBPolicyRateAdapter(
            "ECB_DEPOSIT_FACILITY_RATE",
            lambda request: calls.append(request) or [],
        )
        with self.assertRaises(FetchValidationError):
            adapter.fetch(FetchRequest("FED_FOMC_POLICY", "ECB_DEPOSIT_FACILITY_RATE"))
        with self.assertRaises(FetchValidationError):
            adapter.fetch(FetchRequest("ECB_POLICY_RATES", "ECB_MAIN_REFINANCING_RATE"))
        self.assertEqual(calls, [])

    def test_rejects_unsupported_product_at_construction(self):
        with self.assertRaises(FetchValidationError):
            ECBPolicyRateAdapter("UNKNOWN_PRODUCT", lambda request: [])

    def test_rejects_missing_or_malformed_records(self):
        adapter = ECBPolicyRateAdapter(
            "ECB_DEPOSIT_FACILITY_RATE",
            lambda request: [{"effective_date": "2024-09-18"}],
        )
        with self.assertRaises(FetchParseError):
            adapter.fetch(self.request)
        adapter = ECBPolicyRateAdapter(
            "ECB_DEPOSIT_FACILITY_RATE", lambda request: ["not a row"]
        )
        with self.assertRaises(FetchParseError):
            adapter.fetch(self.request)

    def test_rejects_invalid_rates_and_naive_publication_time(self):
        for row in (
            {"effective_date": "2024-09-18", "rate": "NaN"},
            {"effective_date": "2024-09-18", "rate": 3.5},
            {
                "effective_date": "2024-09-18",
                "rate": "3.50",
                "published_at_utc": "2024-09-12T12:15:00",
            },
        ):
            with self.subTest(row=row), self.assertRaises(FetchValidationError):
                ECBPolicyRateAdapter(
                    "ECB_DEPOSIT_FACILITY_RATE", lambda request, row=row: [row]
                ).fetch(self.request)

    def test_rejects_duplicate_and_conflicting_effective_dates(self):
        row = {"effective_date": "2024-09-18", "rate": "3.50"}
        with self.assertRaisesRegex(FetchValidationError, "Duplicate ECB"):
            ECBPolicyRateAdapter(
                "ECB_DEPOSIT_FACILITY_RATE", lambda request: [row, row]
            ).fetch(self.request)

        conflicting = [
            row,
            {"effective_date": "2024-09-18", "rate": "3.75"},
        ]
        with self.assertRaisesRegex(FetchValidationError, "Conflicting ECB"):
            ECBPolicyRateAdapter(
                "ECB_DEPOSIT_FACILITY_RATE", lambda request: conflicting
            ).fetch(self.request)

    def test_empty_full_history_fails_but_empty_incremental_is_valid(self):
        adapter = ECBPolicyRateAdapter(
            "ECB_DEPOSIT_FACILITY_RATE", lambda request: []
        )
        with self.assertRaisesRegex(FetchValidationError, "full-history"):
            adapter.fetch(self.request)

        since = datetime(2024, 9, 18, tzinfo=UTC)
        incremental = FetchRequest(
            "ECB_POLICY_RATES", "ECB_DEPOSIT_FACILITY_RATE", since=since
        )
        result = adapter.fetch(incremental)
        self.assertEqual(result.observations, ())
        self.assertEqual(result.record_count, 0)


if __name__ == "__main__":
    unittest.main()

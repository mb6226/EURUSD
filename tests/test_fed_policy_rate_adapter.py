import unittest
from datetime import datetime, timezone
from decimal import Decimal

from source_registry.adapters import DecimalRange, FetchParseError, FetchRequest, FetchValidationError
from source_registry.adapters.fed import FedAdapter, FED_OPEN_MARKET_URL

UTC = timezone.utc


class FedPolicyRateAdapterTests(unittest.TestCase):
    def setUp(self):
        self.request = FetchRequest("FED_FOMC_POLICY", "FED_TARGET_RANGE")

    def test_normalizes_range_without_collapsing_to_midpoint(self):
        calls = []
        rows = [{
            "effective_date": "2024-09-19",
            "lower_bound": "4.75",
            "upper_bound": "5.00",
            "published_at_utc": "2024-09-18T18:00:00Z",
            "source_record_id": "fomc-2024-09",
        }]
        adapter = FedAdapter(lambda request: calls.append(request) or rows)
        result = adapter.fetch(self.request)
        self.assertEqual(calls, [self.request])
        self.assertEqual(result.source_url, FED_OPEN_MARKET_URL)
        self.assertEqual(result.record_count, 1)
        observation = result.observations[0]
        self.assertEqual(observation.value, DecimalRange(Decimal("4.75"), Decimal("5.00")))
        self.assertEqual(observation.unit, "percent_per_annum")
        self.assertEqual(observation.effective_at_utc, datetime(2024, 9, 19, tzinfo=UTC))
        self.assertEqual(observation.published_at_utc, datetime(2024, 9, 18, 18, tzinfo=UTC))
        self.assertEqual(observation.source_record_id, "fomc-2024-09")

    def test_sorts_records_chronologically(self):
        adapter = FedAdapter(lambda request: [
            {"effective_date": "2024-11-08", "lower_bound": "4.50", "upper_bound": "4.75"},
            {"effective_date": "2024-09-19", "lower_bound": "4.75", "upper_bound": "5.00"},
        ])
        dates = [item.effective_at_utc.date().isoformat() for item in adapter.fetch(self.request).observations]
        self.assertEqual(dates, ["2024-09-19", "2024-11-08"])

    def test_rejects_wrong_source_or_product(self):
        adapter = FedAdapter(lambda request: [])
        with self.assertRaises(FetchValidationError):
            adapter.fetch(FetchRequest("ECB_POLICY_RATES", "FED_TARGET_RANGE"))
        with self.assertRaises(FetchValidationError):
            adapter.fetch(FetchRequest("FED_FOMC_POLICY", "UNKNOWN"))

    def test_rejects_non_iterable_and_non_object_records(self):
        for provider in (lambda request: "not rows", lambda request: [42]):
            with self.subTest(provider=provider), self.assertRaises(FetchParseError):
                FedAdapter(provider).fetch(self.request)

    def test_rejects_missing_fields(self):
        adapter = FedAdapter(lambda request: [{"effective_date": "2024-09-19", "lower_bound": "4.75"}])
        with self.assertRaises(FetchParseError):
            adapter.fetch(self.request)

    def test_rejects_invalid_and_non_finite_bounds(self):
        rows = [
            {"effective_date": "2024-09-19", "lower_bound": "NaN", "upper_bound": "5.00"},
            {"effective_date": "2024-09-19", "lower_bound": 4.75, "upper_bound": "5.00"},
            {"effective_date": "2024-09-19", "lower_bound": "4.75", "upper_bound": "Infinity"},
        ]
        for row in rows:
            with self.subTest(row=row), self.assertRaises(FetchValidationError):
                FedAdapter(lambda request, row=row: [row]).fetch(self.request)

    def test_rejects_reversed_target_range(self):
        adapter = FedAdapter(lambda request: [{
            "effective_date": "2024-09-19", "lower_bound": "5.00", "upper_bound": "4.75"
        }])
        with self.assertRaises(FetchValidationError):
            adapter.fetch(self.request)

    def test_rejects_naive_publication_timestamp(self):
        adapter = FedAdapter(lambda request: [{
            "effective_date": "2024-09-19", "lower_bound": "4.75", "upper_bound": "5.00",
            "published_at_utc": "2024-09-18T18:00:00",
        }])
        with self.assertRaises(FetchValidationError):
            adapter.fetch(self.request)

    def test_rejects_duplicate_and_conflicting_effective_dates(self):
        row = {"effective_date": "2024-09-19", "lower_bound": "4.75", "upper_bound": "5.00"}
        with self.assertRaisesRegex(FetchValidationError, "Duplicate Fed"):
            FedAdapter(lambda request: [row, row]).fetch(self.request)
        conflict = [row, {"effective_date": "2024-09-19", "lower_bound": "4.50", "upper_bound": "4.75"}]
        with self.assertRaisesRegex(FetchValidationError, "Conflicting Fed"):
            FedAdapter(lambda request: conflict).fetch(self.request)

    def test_empty_full_history_fails_but_incremental_is_valid(self):
        adapter = FedAdapter(lambda request: [])
        with self.assertRaisesRegex(FetchValidationError, "full-history"):
            adapter.fetch(self.request)
        since = datetime(2024, 9, 19, tzinfo=UTC)
        result = adapter.fetch(FetchRequest("FED_FOMC_POLICY", "FED_TARGET_RANGE", since))
        self.assertEqual(result.observations, ())
        self.assertEqual(result.record_count, 0)


if __name__ == "__main__":
    unittest.main()

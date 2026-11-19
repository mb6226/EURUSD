import unittest
from datetime import datetime, timezone

from source_registry.adapters.intermarket import IntermarketSeriesAdapter
from source_registry.adapters.exceptions import FetchValidationError
from source_registry.adapters.models import FetchRequest


UTC = timezone.utc


class IntermarketSeriesAdapterTests(unittest.TestCase):
    def request(self, source="FRED_INTERMARKET", product="US_10Y_TREASURY_YIELD"):
        return FetchRequest(source, product)

    def adapter(self, records, source="FRED_INTERMARKET", product="US_10Y_TREASURY_YIELD"):
        return IntermarketSeriesAdapter(
            source_id=source, product_id=product,
            records_provider=lambda request: records,
        )

    def test_normalizes_observation_and_preserves_actual_publication_time(self):
        result = self.adapter([{
            "observed_at_utc": "2026-11-18T16:00:00Z",
            "published_at_utc": "2026-11-18T16:01:00Z",
            "value": "4.25",
        }]).fetch(self.request())
        item = result.observations[0]
        self.assertEqual(item.value.as_tuple().exponent, -2)
        self.assertEqual(item.unit, "percent_per_annum")
        self.assertEqual(item.effective_at_utc, datetime(2026,11,18,16,tzinfo=UTC))
        self.assertEqual(item.published_at_utc, datetime(2026,11,18,16,1,tzinfo=UTC))
        self.assertEqual(item.source_record_id, "US_10Y_TREASURY_YIELD|2026-11-18T16:00:00Z")

    def test_identity_is_stable_and_independent_of_provider_row_id(self):
        records = [{
            "observed_at_utc": "2026-11-18T16:00:00Z",
            "published_at_utc": "2026-11-18T16:01:00Z",
            "value": "4.25", "source_record_id": "provider-row-1",
        }]
        one = self.adapter(records).fetch(self.request()).observations[0].source_record_id
        records[0]["source_record_id"] = "provider-row-99"
        two = self.adapter(records).fetch(self.request()).observations[0].source_record_id
        self.assertEqual(one, two)

    def test_since_filters_by_observation_time_and_allows_empty_incremental(self):
        result = self.adapter([]).fetch(FetchRequest(
            "FRED_INTERMARKET", "US_10Y_TREASURY_YIELD",
            datetime(2026,11,1,tzinfo=UTC),
        ))
        self.assertEqual(result.record_count, 0)

    def test_full_history_empty_response_is_rejected(self):
        with self.assertRaises(FetchValidationError):
            self.adapter([]).fetch(self.request())

    def test_duplicate_observation_timestamp_is_rejected(self):
        row = {"observed_at_utc":"2026-11-18T16:00:00Z",
               "published_at_utc":"2026-11-18T16:01:00Z","value":"4.2"}
        with self.assertRaises(FetchValidationError):
            self.adapter([row,row]).fetch(self.request())

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(FetchValidationError):
            self.adapter([{"observed_at_utc":"2026-11-18T16:00:00",
                           "published_at_utc":"2026-11-18T16:01:00Z","value":"4.2"}]).fetch(self.request())

    def test_publication_before_observation_is_rejected(self):
        with self.assertRaises(FetchValidationError):
            self.adapter([{"observed_at_utc":"2026-11-18T16:00:00Z",
                           "published_at_utc":"2026-11-18T15:59:00Z","value":"4.2"}]).fetch(self.request())

    def test_non_finite_and_boolean_values_are_rejected(self):
        for value in ("NaN", "Infinity", True):
            with self.subTest(value=value), self.assertRaises(FetchValidationError):
                self.adapter([{"observed_at_utc":"2026-11-18T16:00:00Z",
                               "published_at_utc":"2026-11-18T16:01:00Z","value":value}]).fetch(self.request())

    def test_unknown_source_product_pair_is_rejected(self):
        with self.assertRaises(FetchValidationError):
            self.adapter([], source="UNKNOWN", product="UNKNOWN")

    def test_request_identity_mismatch_is_rejected(self):
        with self.assertRaises(FetchValidationError):
            self.adapter([]).fetch(self.request(product="SP500_INDEX"))


if __name__ == "__main__":
    unittest.main()

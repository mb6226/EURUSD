import unittest
from datetime import datetime, timezone
from decimal import Decimal

from source_registry.adapters import FetchRequest
from source_registry.adapters.exceptions import FetchParseError, FetchValidationError
from source_registry.adapters.macro_series import (
    EUROSTAT_SOURCE_ID, US_BLS_SOURCE_ID, OfficialMacroSeriesAdapter,
)

UTC = timezone.utc


class MacroSeriesAdapterTests(unittest.TestCase):
    def adapter(self, source=US_BLS_SOURCE_ID, product="US_CPI_ALL_ITEMS_INDEX", records=None):
        return OfficialMacroSeriesAdapter(
            source_id=source, product_id=product,
            records_provider=lambda request: records or [],
        )

    def request(self, source=US_BLS_SOURCE_ID, product="US_CPI_ALL_ITEMS_INDEX", since=None):
        return FetchRequest(source_id=source, product_id=product, since=since)

    def test_normalizes_monthly_cpi_and_generates_stable_record_id(self):
        adapter = self.adapter(records=[{
            "reference_period":"2026-10", "value":"330.125",
            "published_at_utc":"2026-11-12T13:30:00Z",
        }])
        result = adapter.fetch(self.request())
        row = result.observations[0]
        self.assertEqual(row.value, Decimal("330.125"))
        self.assertEqual(row.unit, "index_1982_84_100")
        self.assertEqual(row.effective_at_utc, datetime(2026,10,1,tzinfo=UTC))
        self.assertEqual(row.published_at_utc, datetime(2026,11,12,13,30,tzinfo=UTC))
        self.assertEqual(row.source_record_id, "US_CPI_ALL_ITEMS_INDEX:2026-10")

    def test_normalizes_eurostat_unemployment_product(self):
        adapter = self.adapter(
            source=EUROSTAT_SOURCE_ID, product="EA_UNEMPLOYMENT_RATE",
            records=[{"reference_period":"2026-09","value":"6.3",
                      "published_at_utc":"2026-10-30T10:00:00Z"}],
        )
        row = adapter.fetch(self.request(EUROSTAT_SOURCE_ID,"EA_UNEMPLOYMENT_RATE")).observations[0]
        self.assertEqual(row.unit, "percent_of_labor_force")
        self.assertEqual(row.value, Decimal("6.3"))

    def test_since_filters_older_reference_months(self):
        adapter = self.adapter(records=[
            {"reference_period":"2026-08","value":"328","published_at_utc":"2026-09-10T12:00:00Z"},
            {"reference_period":"2026-09","value":"329","published_at_utc":"2026-10-10T12:00:00Z"},
        ])
        result = adapter.fetch(self.request(since=datetime(2026,9,1,tzinfo=UTC)))
        self.assertEqual([item.effective_at_utc.month for item in result.observations],[9])

    def test_duplicate_reference_month_is_rejected(self):
        adapter = self.adapter(records=[
            {"reference_period":"2026-10","value":"330","published_at_utc":"2026-11-12T13:30:00Z"},
            {"reference_period":"2026-10","value":"331","published_at_utc":"2026-11-13T13:30:00Z"},
        ])
        with self.assertRaises(FetchValidationError):
            adapter.fetch(self.request())

    def test_missing_publication_timestamp_is_rejected(self):
        adapter = self.adapter(records=[{"reference_period":"2026-10","value":"330"}])
        with self.assertRaises(FetchParseError):
            adapter.fetch(self.request())

    def test_naive_publication_timestamp_is_rejected(self):
        adapter = self.adapter(records=[{
            "reference_period":"2026-10","value":"330",
            "published_at_utc":"2026-11-12T13:30:00",
        }])
        with self.assertRaises(FetchValidationError):
            adapter.fetch(self.request())

    def test_publication_before_reference_period_is_rejected(self):
        adapter = self.adapter(records=[{
            "reference_period":"2026-10","value":"330",
            "published_at_utc":"2026-09-30T13:30:00Z",
        }])
        with self.assertRaises(FetchValidationError):
            adapter.fetch(self.request())

    def test_invalid_period_and_non_finite_value_are_rejected(self):
        for period, value in (("2026-13","330"),("2026-10","NaN"),("2026-1","330")):
            adapter = self.adapter(records=[{
                "reference_period":period,"value":value,
                "published_at_utc":"2026-11-12T13:30:00Z",
            }])
            with self.subTest(period=period,value=value), self.assertRaises(FetchValidationError):
                adapter.fetch(self.request())

    def test_empty_full_history_is_rejected_but_empty_incremental_is_allowed(self):
        adapter = self.adapter(records=[])
        with self.assertRaises(FetchValidationError):
            adapter.fetch(self.request())
        result = adapter.fetch(self.request(since=datetime(2026,10,1,tzinfo=UTC)))
        self.assertEqual(result.record_count,0)

    def test_unknown_product_is_rejected(self):
        with self.assertRaises(FetchValidationError):
            self.adapter(product="US_GDP_GROWTH")


if __name__ == "__main__":
    unittest.main()

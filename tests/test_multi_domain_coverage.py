from __future__ import annotations

import unittest

from source_registry.coverage import build_multi_domain_coverage_report
from source_registry.registry_loader import load_registry
from source_registry.acquisition_plan import build_acquisition_plan
from source_registry.providers.fred import SERIES_BY_PRODUCT


class MultiDomainCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_registry_fred_products_and_provider_allowlist_are_consistent(self):
        fred = next(s for s in self.registry["sources"] if s["source_id"] == "FRED_INTERMARKET")
        registered = {p["product_id"] for p in fred["products"]}
        self.assertEqual(registered, set(SERIES_BY_PRODUCT))
        self.assertEqual(len(registered), 9)

    def test_coverage_report_distinguishes_registered_from_live_availability(self):
        report = build_multi_domain_coverage_report(self.registry)
        self.assertEqual(report["report_type"], "EURUSD_MULTI_DOMAIN_COVERAGE_ASSESSMENT")
        self.assertEqual(report["registered_source_count"], 9)
        self.assertEqual(report["registered_product_count"], 23)
        self.assertEqual(report["live_data_availability"], "NOT_ASSESSED_BY_REGISTRY_ONLY_REPORT")
        self.assertEqual(report["domains"]["energy"]["registry_status"], "REGISTERED")
        self.assertEqual(report["domains"]["rates_and_yields"]["registry_status"], "REGISTERED")
        self.assertEqual(report["domains"]["precious_metals"]["registry_status"], "REGISTERED")
        self.assertEqual(report["domains"]["news_and_geopolitics"]["registry_status"], "NOT_COVERED")
        self.assertEqual(report["domains"]["options_and_cross_currency"]["registry_status"], "NOT_COVERED")
        self.assertFalse(report["policy"]["auto_fetch_enabled"])

    def test_coverage_report_is_deterministic_and_does_not_mutate_registry(self):
        before = repr(self.registry)
        first = build_multi_domain_coverage_report(self.registry)
        second = build_multi_domain_coverage_report(self.registry)
        self.assertEqual(first, second)
        self.assertEqual(repr(self.registry), before)
        self.assertEqual(first["policy"]["network_requests_made"], 0)
        self.assertFalse(first["policy"]["databases_created_or_mutated"])

    def test_acquisition_plan_retains_fred_date_grain_and_auto_fetch_off(self):
        plan = build_acquisition_plan(self.registry)
        fred = next(s for s in plan["domains"]["intermarket"] if s["source_id"] == "FRED_INTERMARKET")
        self.assertEqual(len(fred["products"]), 9)
        self.assertEqual(fred["pit_readiness"], "DATE_GRAIN_VINTAGES_ONLY_NO_INTRADAY_PIT")
        self.assertFalse(fred["auto_fetch"])
        self.assertEqual(plan["network_requests_made"], 0)


if __name__ == "__main__":
    unittest.main()

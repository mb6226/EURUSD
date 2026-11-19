import unittest
from datetime import datetime, timezone

from eurusd_ai_monitor.engines.fundamental_engine import MacroFundamentalsEngine

UTC = timezone.utc
AS_OF = datetime(2026,11,19,12,tzinfo=UTC)


def row(source, product, value, month, published, retrieved, unit, version=1):
    return {
        "source_id":source,"product_id":product,"value":str(value),"unit":unit,
        "effective_at_utc":f"{month}-01T00:00:00Z",
        "published_at_utc":published,"retrieved_at_utc":retrieved,
        "source_record_id":f"{product}:{month}","version":version,
        "payload_sha256":("a" if source=="US_BLS_MACRO" else "b")*64,
    }


def inputs():
    return {
        "us_cpi_observations":[
            row("US_BLS_MACRO","US_CPI_ALL_ITEMS_INDEX","320","2025-10","2025-11-13T13:30:00Z","2025-11-13T14:00:00Z","index_1982_84_100"),
            row("US_BLS_MACRO","US_CPI_ALL_ITEMS_INDEX","330","2026-10","2026-11-12T13:30:00Z","2026-11-12T14:00:00Z","index_1982_84_100"),
        ],
        "us_unemployment_observations":[
            row("US_BLS_MACRO","US_UNEMPLOYMENT_RATE","4.2","2026-10","2026-11-06T13:30:00Z","2026-11-06T14:00:00Z","percent_of_labor_force"),
        ],
        "ea_hicp_observations":[
            row("EUROSTAT_MACRO","EA_HICP_ALL_ITEMS_INDEX","125","2025-10","2025-11-19T10:00:00Z","2025-11-19T11:00:00Z","index_2015_100"),
            row("EUROSTAT_MACRO","EA_HICP_ALL_ITEMS_INDEX","128.75","2026-10","2026-11-18T10:00:00Z","2026-11-18T11:00:00Z","index_2015_100"),
        ],
        "ea_unemployment_observations":[
            row("EUROSTAT_MACRO","EA_UNEMPLOYMENT_RATE","6.3","2026-10","2026-11-04T10:00:00Z","2026-11-04T11:00:00Z","percent_of_labor_force"),
        ],
    }


class MacroFundamentalsEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = MacroFundamentalsEngine(max_current_observation_age_days=75)

    def assess(self, **overrides):
        payload = inputs()
        payload.update(overrides)
        return self.engine.assess(as_of_utc=AS_OF, **payload)

    def test_calculates_yoy_inflation_and_unemployment_gaps(self):
        report = self.assess()
        self.assertEqual(report["status"],"AVAILABLE")
        self.assertEqual(report["inflation"]["us_cpi_yoy_percent"],"3.12500")
        self.assertEqual(report["inflation"]["euro_area_hicp_yoy_percent"],"3.00")
        self.assertEqual(report["inflation"]["us_minus_euro_area_inflation_pp"],"0.12500")
        self.assertEqual(report["unemployment"]["us_minus_euro_area_unemployment_pp"],"-2.1")
        self.assertEqual(report["decision_authority"],"ASSESSMENT_ONLY")
        self.assertEqual(report["trade_authority"],"NONE")
        self.assertEqual(report["order_execution"],"DISABLED")

    def test_excludes_future_publication_and_retrieval(self):
        payload=inputs()
        payload["us_cpi_observations"][-1]["published_at_utc"]="2026-11-20T00:00:00Z"
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertNotEqual(report["inflation"]["status"],"AVAILABLE")
        payload=inputs()
        payload["us_cpi_observations"][-1]["retrieved_at_utc"]="2026-11-20T00:00:00Z"
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertNotEqual(report["inflation"]["status"],"AVAILABLE")

    def test_excludes_future_effective_observations(self):
        payload=inputs()
        payload["us_unemployment_observations"][-1]["effective_at_utc"]="2026-12-01T00:00:00Z"
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertEqual(report["unemployment"]["status"],"UNAVAILABLE")

    def test_uses_latest_revision_known_at_cutoff(self):
        payload=inputs()
        revised=dict(payload["us_cpi_observations"][-1])
        revised["value"]="331"
        revised["version"]=2
        revised["retrieved_at_utc"]="2026-11-13T14:00:00Z"
        revised["published_at_utc"]="2026-11-12T13:30:00Z"
        payload["us_cpi_observations"].append(revised)
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertEqual(report["inflation"]["us_cpi_yoy_percent"],"3.437500")

    def test_uses_latest_common_inflation_month(self):
        payload=inputs()
        payload["us_cpi_observations"].append(
            row("US_BLS_MACRO","US_CPI_ALL_ITEMS_INDEX","332","2026-11","2026-11-19T08:00:00Z","2026-11-19T09:00:00Z","index_1982_84_100")
        )
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertEqual(report["inflation"]["reference_month"],"2026-10")

    def test_missing_year_ago_baseline_makes_inflation_unavailable(self):
        payload=inputs()
        payload["us_cpi_observations"]=payload["us_cpi_observations"][-1:]
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertEqual(report["inflation"]["status"],"UNAVAILABLE")

    def test_stale_current_series_is_not_used(self):
        payload=inputs()
        payload["us_cpi_observations"][-1]["effective_at_utc"]="2026-07-01T00:00:00Z"
        payload["us_cpi_observations"][-1]["source_record_id"]="US_CPI_ALL_ITEMS_INDEX:2026-07"
        payload["us_cpi_observations"][-1]["published_at_utc"]="2026-08-12T13:30:00Z"
        payload["us_cpi_observations"][-1]["retrieved_at_utc"]="2026-08-12T14:00:00Z"
        payload["ea_hicp_observations"].extend([
            row("EUROSTAT_MACRO","EA_HICP_ALL_ITEMS_INDEX","124","2025-07","2025-08-19T10:00:00Z","2025-08-19T11:00:00Z","index_2015_100"),
            row("EUROSTAT_MACRO","EA_HICP_ALL_ITEMS_INDEX","128","2026-07","2026-08-18T10:00:00Z","2026-08-18T11:00:00Z","index_2015_100"),
        ])
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertEqual(report["inflation"]["status"],"STALE")

    def test_unemployment_requires_common_reference_month(self):
        payload=inputs()
        payload["ea_unemployment_observations"][-1]["effective_at_utc"]="2026-09-01T00:00:00Z"
        payload["us_unemployment_observations"].append(
            row("US_BLS_MACRO","US_UNEMPLOYMENT_RATE","4.1","2026-09","2026-10-02T13:30:00Z","2026-10-02T14:00:00Z","percent_of_labor_force")
        )
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertEqual(report["unemployment"]["reference_month"],"2026-09")
        self.assertEqual(report["unemployment"]["status"],"STALE")

    def test_partial_report_preserves_available_dimension(self):
        payload=inputs()
        payload["ea_hicp_observations"]=[]
        report=self.engine.assess(as_of_utc=AS_OF,**payload)
        self.assertEqual(report["status"],"PARTIAL")
        self.assertEqual(report["unemployment"]["status"],"AVAILABLE")
        self.assertEqual(report["inflation"]["status"],"UNAVAILABLE")

    def test_wrong_identity_unit_and_bad_index_fail_closed(self):
        payload=inputs()
        payload["us_cpi_observations"][0]["product_id"]="WRONG"
        with self.assertRaises(ValueError):
            self.engine.assess(as_of_utc=AS_OF,**payload)
        payload=inputs()
        payload["us_cpi_observations"][0]["unit"]="percent"
        with self.assertRaises(ValueError):
            self.engine.assess(as_of_utc=AS_OF,**payload)
        payload=inputs()
        payload["us_cpi_observations"][-1]["value"]="0"
        with self.assertRaises(ValueError):
            self.engine.assess(as_of_utc=AS_OF,**payload)

    def test_naive_cutoff_and_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.assess(as_of_utc=datetime(2026,11,19,12),**inputs())
        with self.assertRaises(TypeError):
            self.engine.assess(as_of_utc=AS_OF,**{**inputs(),"us_cpi_observations":"bad"})


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from eurusd_ai_monitor.engines.fundamental_engine import MacroFundamentalsEngine
from source_registry.adapters.macro_series import (
    EUROSTAT_SOURCE_ID, US_BLS_SOURCE_ID, OfficialMacroSeriesAdapter,
)
from source_registry.ingestion import SourceObservationIngestion
from source_registry.observation_store import PointInTimeObservationStore
from source_registry.registry_loader import load_registry

UTC=timezone.utc
AS_OF=datetime(2026,11,19,12,tzinfo=UTC)
RETRIEVED=datetime(2026,11,19,11,tzinfo=UTC)


class MacroFundamentalsIntegrationTests(unittest.TestCase):
    def test_official_macro_adapters_ingest_into_pit_store_and_feed_specialist(self):
        records={
            ("US_BLS_MACRO","US_CPI_ALL_ITEMS_INDEX"):[
                {"reference_period":"2025-10","value":"320","published_at_utc":"2025-11-13T13:30:00Z"},
                {"reference_period":"2026-10","value":"330","published_at_utc":"2026-11-12T13:30:00Z"},
            ],
            ("US_BLS_MACRO","US_UNEMPLOYMENT_RATE"):[
                {"reference_period":"2026-10","value":"4.2","published_at_utc":"2026-11-06T13:30:00Z"},
            ],
            ("EUROSTAT_MACRO","EA_HICP_ALL_ITEMS_INDEX"):[
                {"reference_period":"2025-10","value":"125","published_at_utc":"2025-11-19T10:00:00Z"},
                {"reference_period":"2026-10","value":"128.75","published_at_utc":"2026-11-18T10:00:00Z"},
            ],
            ("EUROSTAT_MACRO","EA_UNEMPLOYMENT_RATE"):[
                {"reference_period":"2026-10","value":"6.3","published_at_utc":"2026-11-04T10:00:00Z"},
            ],
        }
        adapters={
            key:OfficialMacroSeriesAdapter(
                source_id=key[0],product_id=key[1],
                records_provider=lambda request, rows=rows: rows,
            )
            for key,rows in records.items()
        }
        registry=load_registry()
        with tempfile.TemporaryDirectory() as directory:
            store=PointInTimeObservationStore(Path(directory)/"macro.sqlite")
            ingestion=SourceObservationIngestion(
                registry=registry,adapters=adapters,store=store,
                clock=lambda:RETRIEVED,
            )
            for source_id,product_id in records:
                summary=ingestion.ingest(source_id,product_id)
                self.assertEqual(summary.observations_received,len(records[(source_id,product_id)]))
            stored={
                "us_cpi_observations":store.get_as_of("US_BLS_MACRO","US_CPI_ALL_ITEMS_INDEX",AS_OF),
                "us_unemployment_observations":store.get_as_of("US_BLS_MACRO","US_UNEMPLOYMENT_RATE",AS_OF),
                "ea_hicp_observations":store.get_as_of("EUROSTAT_MACRO","EA_HICP_ALL_ITEMS_INDEX",AS_OF),
                "ea_unemployment_observations":store.get_as_of("EUROSTAT_MACRO","EA_UNEMPLOYMENT_RATE",AS_OF),
            }
        report=MacroFundamentalsEngine().assess(as_of_utc=AS_OF,**stored)
        self.assertEqual(report["status"],"AVAILABLE")
        self.assertEqual(report["inflation"]["us_minus_euro_area_inflation_pp"],"0.12500")
        self.assertEqual(report["unemployment"]["us_minus_euro_area_unemployment_pp"],"-2.1")
        self.assertTrue(report["inflation"]["provenance"]["us_current"]["payload_sha256"])
        self.assertEqual(report["decision_authority"],"ASSESSMENT_ONLY")


if __name__=="__main__":
    unittest.main()

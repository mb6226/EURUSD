import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.engines.intermarket_intelligence_engine import (
    IntermarketIntelligenceEngine,
)
from source_registry.adapters.intermarket import IntermarketSeriesAdapter
from source_registry.ingestion import SourceObservationIngestion
from source_registry.observation_store import PointInTimeObservationStore
from source_registry.registry_loader import load_registry


UTC = timezone.utc
AS_OF = datetime(2026,11,19,23,tzinfo=UTC)
RETRIEVED = datetime(2026,11,19,22,tzinfo=UTC)
CHANGES = [Decimal(value) for value in (
    "1","-1","2","-2","3","-3","2","-1","1","-2",
    "3","-1","2","-3","1","-2","2","-1","3","-2",
    "1","-3","2","-1",
)]
SERIES = {
    ("BROKER_SPOT_REFERENCE","EURUSD_SPOT_REFERENCE"):("usd_per_eur","1.10","PRICE"),
    ("FRED_INTERMARKET","US_10Y_TREASURY_YIELD"):("percent_per_annum","4.0","YIELD"),
    ("ECB_INTERMARKET","DE_10Y_GOVERNMENT_YIELD"):("percent_per_annum","2.0","YIELD"),
    ("FRED_INTERMARKET","USD_BROAD_TRADE_WEIGHTED_INDEX"):("index_points","100","PRICE"),
    ("LBMA_INTERMARKET","GOLD_USD_TROY_OUNCE"):("usd_per_troy_ounce","2000","PRICE"),
    ("FRED_INTERMARKET","SP500_INDEX"):("index_points","6000","PRICE"),
}


def records(unit, initial, kind):
    value = Decimal(initial)
    output = []
    start = datetime(2026,10,26,16,tzinfo=UTC)
    output.append({"observed_at_utc":start.isoformat(),"published_at_utc":(start+timedelta(minutes=1)).isoformat(),"value":str(value)})
    for index, change in enumerate(CHANGES,1):
        if kind == "PRICE":
            value *= (Decimal(100)+change)/Decimal(100)
        else:
            value += change/Decimal(100)
        observed = start + timedelta(days=index)
        output.append({"observed_at_utc":observed.isoformat(),"published_at_utc":(observed+timedelta(minutes=1)).isoformat(),"value":str(value)})
    return output


class IntermarketIntegrationTests(unittest.TestCase):
    def test_registered_sources_ingest_through_pit_store_into_intermarket_engine(self):
        registry = load_registry()
        intermarket_sources = {
            source["source_id"]: source for source in registry["sources"]
            if source["source_id"] in {
                "FRED_INTERMARKET","ECB_INTERMARKET",
                "LBMA_INTERMARKET","BROKER_SPOT_REFERENCE",
            }
        }
        self.assertEqual(len(intermarket_sources),4)
        self.assertTrue(all(source["enabled"] for source in intermarket_sources.values()))
        self.assertTrue(all(source["auto_fetch"] is False for source in intermarket_sources.values()))

        adapters = {}
        for (source_id, product_id), (unit, initial, kind) in SERIES.items():
            rows = records(unit, initial, kind)
            adapters[(source_id,product_id)] = IntermarketSeriesAdapter(
                source_id=source_id, product_id=product_id,
                records_provider=lambda request, payload=rows: payload,
            )

        with tempfile.TemporaryDirectory() as directory:
            store = PointInTimeObservationStore(Path(directory)/"intermarket.sqlite")
            ingestion = SourceObservationIngestion(
                registry=registry, adapters=adapters, store=store,
                clock=lambda:RETRIEVED,
            )
            for source_id, product_id in SERIES:
                summary = ingestion.ingest(source_id,product_id)
                self.assertEqual(summary.observations_received,25)

            eurusd = store.get_as_of(
                "BROKER_SPOT_REFERENCE","EURUSD_SPOT_REFERENCE",AS_OF
            )
            drivers = {
                product_id:store.get_as_of(source_id,product_id,AS_OF)
                for (source_id,product_id) in SERIES
                if product_id != "EURUSD_SPOT_REFERENCE"
            }
            self.assertEqual(store.count_observations(),150)

        report = IntermarketIntelligenceEngine(
            lookback_observations=60, minimum_observations=20
        ).assess(
            as_of_utc=AS_OF, eurusd_observations=eurusd,
            driver_observations=drivers,
        )
        self.assertEqual(report["status"],"AVAILABLE")
        self.assertEqual(report["eurusd_observation_count"],25)
        self.assertEqual(report["drivers"]["GOLD_USD_TROY_OUNCE"]["status"],"AVAILABLE")
        self.assertTrue(report["drivers"]["GOLD_USD_TROY_OUNCE"]["provenance"]["payload_sha256"])
        self.assertEqual(report["decision_authority"],"ASSESSMENT_ONLY")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from source_registry.adapters.fed import FedAdapter
from source_registry.ingestion import SourceObservationIngestion
from source_registry.observation_store import PointInTimeObservationStore
from source_registry.registry_loader import load_registry

UTC = timezone.utc
RETRIEVED = datetime(2026, 11, 19, 12, tzinfo=UTC)


class FedIngestionIntegrationTests(unittest.TestCase):
    def test_registered_fed_target_range_flows_into_pit_store(self):
        registry = load_registry()
        adapter = FedAdapter(lambda request: [{
            "effective_date": "2024-09-19",
            "lower_bound": "4.75",
            "upper_bound": "5.00",
            "published_at_utc": "2024-09-18T18:00:00Z",
            "source_record_id": "fomc-2024-09",
        }])

        with tempfile.TemporaryDirectory() as directory:
            store = PointInTimeObservationStore(Path(directory) / "observations.sqlite")
            ingestion = SourceObservationIngestion(
                registry=registry,
                adapters={("FED_FOMC_POLICY", "FED_TARGET_RANGE"): adapter},
                store=store,
                clock=lambda: RETRIEVED,
            )
            summary = ingestion.ingest("FED_FOMC_POLICY", "FED_TARGET_RANGE")
            rows = store.get_as_of("FED_FOMC_POLICY", "FED_TARGET_RANGE", RETRIEVED)

        self.assertEqual(summary.observations_received, 1)
        self.assertEqual(summary.persistence.observations_inserted, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], {"low": "4.75", "high": "5.00"})
        self.assertEqual(rows[0]["unit"], "percent_per_annum")
        self.assertEqual(rows[0]["published_at_utc"], "2024-09-18T18:00:00.000000Z")
        self.assertEqual(rows[0]["retrieved_at_utc"], "2026-11-19T12:00:00.000000Z")


if __name__ == "__main__":
    unittest.main()

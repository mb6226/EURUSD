import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from source_registry.adapters.ecb import ECBPolicyRateAdapter
from source_registry.ingestion import SourceObservationIngestion
from source_registry.observation_store import PointInTimeObservationStore
from source_registry.registry_loader import load_registry

UTC = timezone.utc
RETRIEVED = datetime(2026, 11, 19, 12, tzinfo=UTC)


class ECBIngestionIntegrationTests(unittest.TestCase):
    def test_registered_ecb_product_flows_through_ingestion_into_pit_store(self):
        registry = load_registry()
        product_id = "ECB_DEPOSIT_FACILITY_RATE"
        adapter = ECBPolicyRateAdapter(
            product_id,
            lambda request: [
                {
                    "effective_date": "2024-09-18",
                    "rate": "3.50",
                    "published_at_utc": "2024-09-12T12:15:00Z",
                    "source_record_id": "ecb-deposit-2024-09",
                }
            ],
        )

        with tempfile.TemporaryDirectory() as directory:
            store = PointInTimeObservationStore(
                Path(directory) / "observations.sqlite"
            )
            ingestion = SourceObservationIngestion(
                registry=registry,
                adapters={("ECB_POLICY_RATES", product_id): adapter},
                store=store,
                clock=lambda: RETRIEVED,
            )

            summary = ingestion.ingest("ECB_POLICY_RATES", product_id)
            rows = store.get_as_of(
                "ECB_POLICY_RATES", product_id, RETRIEVED
            )

        self.assertEqual(summary.observations_received, 1)
        self.assertEqual(summary.persistence.observations_inserted, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], "3.50")
        self.assertEqual(rows[0]["unit"], "percent_per_annum")
        self.assertEqual(
            rows[0]["published_at_utc"], "2024-09-12T12:15:00.000000Z"
        )
        self.assertEqual(
            rows[0]["retrieved_at_utc"], "2026-11-19T12:00:00.000000Z"
        )


if __name__ == "__main__":
    unittest.main()

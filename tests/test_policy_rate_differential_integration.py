import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.engines.policy_rate_differential_engine import PolicyRateDifferentialEngine
from source_registry.adapters import DecimalRange, FetchResult, Observation
from source_registry.observation_store import PointInTimeObservationStore

UTC = timezone.utc
AS_OF = datetime(2026, 11, 19, 12, tzinfo=UTC)


class PolicyRateDifferentialIntegrationTests(unittest.TestCase):
    def test_ecb_and_fed_pit_store_records_flow_into_fundamental_specialist(self):
        ecb = Observation(
            source_id="ECB_POLICY_RATES",
            product_id="ECB_DEPOSIT_FACILITY_RATE",
            value=Decimal("2.00"),
            unit="percent_per_annum",
            effective_at_utc=datetime(2026, 10, 1, tzinfo=UTC),
            published_at_utc=datetime(2026, 9, 30, 12, tzinfo=UTC),
            source_record_id="ecb-deposit-2026-10",
        )
        fed = Observation(
            source_id="FED_FOMC_POLICY",
            product_id="FED_TARGET_RANGE",
            value=DecimalRange(Decimal("4.00"), Decimal("4.25")),
            unit="percent_per_annum",
            effective_at_utc=datetime(2026, 11, 8, tzinfo=UTC),
            published_at_utc=datetime(2026, 11, 7, 18, tzinfo=UTC),
            source_record_id="fed-fomc-2026-11",
        )

        with tempfile.TemporaryDirectory() as directory:
            store = PointInTimeObservationStore(Path(directory) / "observations.sqlite")
            store.persist_fetch_result(FetchResult(
                source_id=ecb.source_id,
                product_id=ecb.product_id,
                observations=(ecb,),
                source_url="https://www.ecb.europa.eu/",
                record_count=1,
                retrieved_at_utc=datetime(2026, 10, 1, 1, tzinfo=UTC),
            ))
            store.persist_fetch_result(FetchResult(
                source_id=fed.source_id,
                product_id=fed.product_id,
                observations=(fed,),
                source_url="https://www.federalreserve.gov/",
                record_count=1,
                retrieved_at_utc=datetime(2026, 11, 8, 1, tzinfo=UTC),
            ))
            ecb_rows = store.get_as_of(
                "ECB_POLICY_RATES", "ECB_DEPOSIT_FACILITY_RATE", AS_OF
            )
            fed_rows = store.get_as_of(
                "FED_FOMC_POLICY", "FED_TARGET_RANGE", AS_OF
            )

        report = PolicyRateDifferentialEngine(
            max_observation_age=timedelta(days=120)
        ).assess(
            as_of_utc=AS_OF,
            ecb_observations=ecb_rows,
            fed_observations=fed_rows,
        )
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(
            report["usd_minus_eur_spread"],
            {"low": "2.00", "high": "2.25"},
        )
        self.assertEqual(
            report["provenance"]["point_in_time_cutoff_utc"],
            AS_OF.isoformat(),
        )
        self.assertEqual(
            report["provenance"]["eur_reference"]["source_record_id"],
            "ecb-deposit-2026-10",
        )
        self.assertEqual(
            report["provenance"]["usd_reference"]["source_record_id"],
            "fed-fomc-2026-11",
        )


if __name__ == "__main__":
    unittest.main()

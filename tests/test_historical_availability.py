import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from source_registry.adapters.models import FetchResult, Observation
from source_registry.historical_availability import HistoricalAvailabilityLedger
from source_registry.observation_store import PointInTimeObservationStore
from source_registry.raw_archive import RawSnapshotArchive

UTC = timezone.utc
def dt(day, hour=0): return datetime(2026, 1, day, hour, tzinfo=UTC)

class PublicAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = PointInTimeObservationStore(root / "obs.sqlite")
        self.archive = RawSnapshotArchive(root / "raw.sqlite", allowed_products={"CFTC_TFF_POSITIONING": {"EURO_FX_DEALER_NET_OI_PCT"}})
        obs = Observation("CFTC_TFF_POSITIONING", "EURO_FX_DEALER_NET_OI_PCT", Decimal("1.25"), "percent_of_open_interest", dt(2), dt(3, 15), "EURO_FX_099741|2026-01-02")
        self.store.persist_fetch_result(FetchResult("CFTC_TFF_POSITIONING", "EURO_FX_DEALER_NET_OI_PCT", (obs,), "https://www.cftc.gov/data", 1, dt(10)))
        self.reader = PointInTimeObservationStore.open_read_only(self.store.db_path)
        self.row = self.reader.get_as_of("CFTC_TFF_POSITIONING", "EURO_FX_DEALER_NET_OI_PCT", dt(11))[0]
        self.ledger = HistoricalAvailabilityLedger(root / "attestations.sqlite")
        self.evidence = []
        for url, payload in [("https://www.cftc.gov/release", b"official release time"), ("https://publicreporting.cftc.gov/row", b"as-released row vintage")]:
            self.evidence.append(self.archive.append(source_id="CFTC_TFF_POSITIONING", product_id="EURO_FX_DEALER_NET_OI_PCT", source_url=url, retrieved_at_utc=dt(10), http_status=200, content_type="text/plain", payload=payload).snapshot_id)

    def _attest(self, status="AS_RELEASED_VALUE_VERIFIED"):
        return self.ledger.attest(observation=self.row, published_at_utc=dt(3, 15), evidence_snapshot_ids=self.evidence, archive=self.archive, observation_store=self.reader, attested_at_utc=dt(11), attestor="test-reviewer", method_version="test-v1", value_vintage_status=status)

    def test_public_mode_uses_attested_publication_not_late_local_retrieval(self):
        self._attest()
        self.assertEqual(self.reader.get_as_of("CFTC_TFF_POSITIONING", "EURO_FX_DEALER_NET_OI_PCT", dt(5)), [])
        rows = self.ledger.read_public_availability_as_of(self.reader, source_id="CFTC_TFF_POSITIONING", product_id="EURO_FX_DEALER_NET_OI_PCT", as_of_utc=dt(5))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["retrieved_at_utc"], "2026-01-10T00:00:00.000000Z")
        self.assertEqual(rows[0]["availability_mode"], "RECONSTRUCTED_PUBLIC_AVAILABILITY")

    def test_unattested_observations_are_excluded(self):
        self.assertEqual(self.ledger.read_public_availability_as_of(self.reader, source_id="CFTC_TFF_POSITIONING", product_id="EURO_FX_DEALER_NET_OI_PCT", as_of_utc=dt(20)), [])

    def test_future_publication_is_excluded(self):
        self._attest()
        self.assertEqual(self.ledger.read_public_availability_as_of(self.reader, source_id="CFTC_TFF_POSITIONING", product_id="EURO_FX_DEALER_NET_OI_PCT", as_of_utc=dt(3, 14)), [])

    def test_latest_or_unverified_value_vintage_cannot_be_attested(self):
        with self.assertRaises(ValueError): self._attest("LATEST_VALUE_ONLY")

    def test_missing_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.attest(observation=self.row, published_at_utc=dt(3, 15), evidence_snapshot_ids=[self.evidence[0]], archive=self.archive, observation_store=self.reader, attested_at_utc=dt(11), attestor="reviewer", method_version="v1", value_vintage_status="AS_RELEASED_VALUE_VERIFIED")

    def test_evidence_hash_tampering_is_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.attest(observation=self.row, published_at_utc=dt(3, 15), evidence_snapshot_ids=["not-a-snapshot", self.evidence[1]], archive=self.archive, observation_store=self.reader, attested_at_utc=dt(11), attestor="reviewer", method_version="v1", value_vintage_status="AS_RELEASED_VALUE_VERIFIED")

    def test_attestation_cannot_precede_retrieval(self):
        with self.assertRaises(ValueError):
            self.ledger.attest(observation=self.row, published_at_utc=dt(3, 15), evidence_snapshot_ids=self.evidence, archive=self.archive, observation_store=self.reader, attested_at_utc=dt(9), attestor="reviewer", method_version="v1", value_vintage_status="AS_RELEASED_VALUE_VERIFIED")

    def test_naive_cutoff_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.read_public_availability_as_of(self.reader, source_id="CFTC_TFF_POSITIONING", product_id="EURO_FX_DEALER_NET_OI_PCT", as_of_utc=datetime(2026, 1, 20))

if __name__ == "__main__": unittest.main()

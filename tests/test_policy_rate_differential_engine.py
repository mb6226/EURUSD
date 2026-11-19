import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.policy_rate_differential_engine import PolicyRateDifferentialEngine

UTC = timezone.utc
AS_OF = datetime(2026, 11, 19, 12, tzinfo=UTC)


def ecb(rate="2.00", *, effective="2026-10-01T00:00:00Z",
        published="2026-09-30T12:00:00Z", retrieved="2026-10-01T01:00:00Z"):
    return {"source_id":"ECB_POLICY_RATES","product_id":"ECB_DEPOSIT_FACILITY_RATE",
            "value":rate,"unit":"percent_per_annum","effective_at_utc":effective,
            "published_at_utc":published,"retrieved_at_utc":retrieved,
            "version":1,"source_record_id":"ecb-1","payload_sha256":"a"*64}


def fed(low="4.00", high="4.25", *, effective="2026-11-08T00:00:00Z",
        published="2026-11-07T18:00:00Z", retrieved="2026-11-08T01:00:00Z"):
    return {"source_id":"FED_FOMC_POLICY","product_id":"FED_TARGET_RANGE",
            "value":{"low":low,"high":high},"unit":"percent_per_annum",
            "effective_at_utc":effective,"published_at_utc":published,
            "retrieved_at_utc":retrieved,"version":1,"source_record_id":"fed-1",
            "payload_sha256":"b"*64}


class PolicyRateDifferentialEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = PolicyRateDifferentialEngine(max_observation_age=timedelta(days=120))

    def assess(self, e=None, f=None, at=AS_OF):
        return self.engine.assess(as_of_utc=at, ecb_observations=[] if e is None else e,
                                  fed_observations=[] if f is None else f)

    def test_calculates_usd_minus_eur_spread_and_preserves_range(self):
        report = self.assess([ecb()], [fed()])
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(report["usd_minus_eur_spread"], {"low":"2.00","high":"2.25"})
        self.assertEqual(report["decision_authority"], "ASSESSMENT_ONLY")
        self.assertEqual(report["trade_authority"], "NONE")
        self.assertEqual(report["order_execution"], "DISABLED")

    def test_selects_latest_effective_observation(self):
        older = ecb("1.50", effective="2026-08-01T00:00:00Z",
                    published="2026-07-31T12:00:00Z", retrieved="2026-08-01T01:00:00Z")
        report = self.assess([older, ecb()], [fed()])
        self.assertEqual(report["usd_minus_eur_spread"]["low"], "2.00")

    def test_excludes_future_publication_and_retrieval(self):
        future_pub = ecb(published="2026-11-20T00:00:00Z")
        future_retrieval = fed(retrieved="2026-11-20T00:00:00Z")
        report = self.assess([future_pub], [future_retrieval])
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertEqual(len(report["missing_products"]), 2)

    def test_excludes_future_effective_observation(self):
        report = self.assess([ecb(effective="2026-11-20T00:00:00Z")], [fed()])
        self.assertEqual(report["status"], "UNAVAILABLE")

    def test_missing_either_side_is_unavailable(self):
        self.assertEqual(self.assess([ecb()], None)["status"], "UNAVAILABLE")
        self.assertEqual(self.assess(None, [fed()])["status"], "UNAVAILABLE")

    def test_stale_evidence_is_not_used(self):
        old = ecb(effective="2026-01-01T00:00:00Z",
                  published="2025-12-31T12:00:00Z", retrieved="2026-01-01T01:00:00Z")
        report = self.assess([old], [fed()])
        self.assertEqual(report["status"], "STALE")
        self.assertIn("ECB_DEPOSIT_FACILITY_RATE", report["stale_products"])

    def test_unknown_publication_is_excluded(self):
        row = ecb()
        row["published_at_utc"] = None
        self.assertEqual(self.assess([row], [fed()])["status"], "UNAVAILABLE")

    def test_wrong_identity_fails_closed(self):
        row = ecb()
        row["product_id"] = "ECB_MAIN_REFINANCING_RATE"
        with self.assertRaises(ValueError):
            self.assess([row], [fed()])

    def test_wrong_units_fail_closed(self):
        row = fed()
        row["unit"] = "basis_points"
        with self.assertRaises(ValueError):
            self.assess([ecb()], [row])

    def test_malformed_range_fails_closed(self):
        for value in ({"low":"4.2"}, {"low":"NaN","high":"5"}, {"low":"5","high":"4"}):
            row = fed()
            row["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.assess([ecb()], [row])

    def test_non_finite_ecb_rate_fails_closed(self):
        with self.assertRaises(ValueError):
            self.assess([ecb("Infinity")], [fed()])

    def test_naive_as_of_is_rejected(self):
        with self.assertRaises(ValueError):
            self.assess([ecb()], [fed()], datetime(2026,11,19,12))

    def test_non_sequence_input_is_rejected(self):
        with self.assertRaises(TypeError):
            self.engine.assess(as_of_utc=AS_OF, ecb_observations="bad", fed_observations=[])

    def test_latest_revision_wins_for_same_effective_date(self):
        revised = ecb("2.25", retrieved="2026-10-02T01:00:00Z")
        revised["version"] = 2
        report = self.assess([ecb(), revised], [fed()])
        self.assertEqual(report["usd_minus_eur_spread"]["low"], "1.75")

    def test_provenance_identifies_both_sources_and_cutoff(self):
        report = self.assess([ecb()], [fed()])
        self.assertEqual(report["provenance"]["eur_reference"]["source_id"], "ECB_POLICY_RATES")
        self.assertEqual(report["provenance"]["usd_reference"]["source_id"], "FED_FOMC_POLICY")
        self.assertEqual(report["provenance"]["eur_reference"]["payload_sha256"], "a"*64)


if __name__ == "__main__":
    unittest.main()

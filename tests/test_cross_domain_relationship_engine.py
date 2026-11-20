import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.cross_domain_relationship_engine import CrossDomainRelationshipEngine


class CrossDomainRelationshipEngineTests(unittest.TestCase):
    def snapshot(self, *, domains=2, count=25):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        products = {}
        for d in range(domains):
            rows = []
            value = 100.0
            for i in range(count):
                at = start + timedelta(days=i)
                value += (i % 5) + 1
                rows.append({"source_id": f"SRC{d}", "product_id": f"P{d}", "unit": "index_points",
                    "value": str(value), "effective_at_utc": at.isoformat(),
                    "published_at_utc": (at + timedelta(hours=1)).isoformat(),
                    "retrieved_at_utc": (at + timedelta(hours=2)).isoformat(),
                    "payload_sha256": f"{i:064x}"})
            products[f"domain{d}"] = {"status": "ELIGIBLE", "products": [{"status": "ELIGIBLE",
                "source_id": f"SRC{d}", "product_id": f"P{d}", "observations": rows}]}
        return {"read_mode": "STRICT_SYSTEM_KNOWLEDGE", "as_of_utc": (start + timedelta(days=count+1)).isoformat(),
            "snapshot_sha256": "a" * 64, "analytics_domains": products}

    def test_exact_aligned_cross_domain_pair_available(self):
        result = CrossDomainRelationshipEngine(minimum_aligned_changes=20).assess(self.snapshot())
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["available_relationship_count"], 1)
        self.assertEqual(result["relationships"][0]["aligned_change_count"], 24)
        self.assertTrue(result["policy"]["exact_timestamp_alignment_only"])

    def test_single_observation_series_does_not_crash(self):
        result = CrossDomainRelationshipEngine().assess(self.snapshot(count=1))
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")

    def test_same_domain_pairs_are_excluded(self):
        result = CrossDomainRelationshipEngine(minimum_aligned_changes=20).assess(self.snapshot(domains=1))
        self.assertEqual(result["candidate_cross_domain_pair_count"], 0)
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")

    def test_short_history_is_not_promoted(self):
        result = CrossDomainRelationshipEngine(minimum_aligned_changes=20).assess(self.snapshot(count=8))
        self.assertEqual(result["relationships"][0]["status"], "INSUFFICIENT_DATA")

    def test_public_availability_mode_rejected(self):
        snap = self.snapshot(); snap["read_mode"] = "RECONSTRUCTED_PUBLIC_AVAILABILITY"
        with self.assertRaises(ValueError): CrossDomainRelationshipEngine().assess(snap)

    def test_future_observation_rejected_for_series(self):
        snap = self.snapshot()
        snap["analytics_domains"]["domain0"]["products"][0]["observations"][-1]["effective_at_utc"] = "2027-01-01T00:00:00+00:00"
        result = CrossDomainRelationshipEngine().assess(snap)
        self.assertIn("domain0:P0", result["excluded_series"])

    def test_noneligible_product_excluded(self):
        snap = self.snapshot(); snap["analytics_domains"]["domain0"]["products"][0]["status"] = "QUARANTINED"
        result = CrossDomainRelationshipEngine().assess(snap)
        self.assertIn("domain0:P0", result["excluded_series"])

    def test_missing_timestamps_are_not_filled(self):
        snap = self.snapshot()
        rows = snap["analytics_domains"]["domain1"]["products"][0]["observations"]
        rows.pop(5)
        result = CrossDomainRelationshipEngine(minimum_aligned_changes=20).assess(snap)
        self.assertEqual(result["relationships"][0]["aligned_change_count"], 23)

    def test_invalid_snapshot_and_sha_rejected(self):
        with self.assertRaises(TypeError): CrossDomainRelationshipEngine().assess([])
        snap = self.snapshot(); snap["snapshot_sha256"] = "bad"
        with self.assertRaises(ValueError): CrossDomainRelationshipEngine().assess(snap)

    def test_unsupported_unit_excluded(self):
        snap = self.snapshot()
        for row in snap["analytics_domains"]["domain0"]["products"][0]["observations"]: row["unit"] = "unknown"
        result = CrossDomainRelationshipEngine().assess(snap)
        self.assertEqual(result["excluded_series"]["domain0:P0"], "UNSUPPORTED_MEASURE_UNIT")

    def test_zero_variance_returns_insufficient(self):
        snap = self.snapshot()
        for d in range(2):
            rows = snap["analytics_domains"][f"domain{d}"]["products"][0]["observations"]
            for i, row in enumerate(rows):
                row["unit"] = "percent_per_annum"
                row["value"] = str(1 + i)
        result = CrossDomainRelationshipEngine(minimum_aligned_changes=20).assess(snap)
        self.assertEqual(result["relationships"][0]["status"], "INSUFFICIENT_DATA")


if __name__ == "__main__": unittest.main()

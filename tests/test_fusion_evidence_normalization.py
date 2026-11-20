from __future__ import annotations

import unittest
from datetime import datetime, timezone

from eurusd_ai_monitor.engines.fusion_engine import EvidenceDirection
from eurusd_ai_monitor.main import _fusion_evidence


class FusionEvidenceNormalizationTests(unittest.TestCase):
    def test_duplicate_references_are_collapsed_without_losing_order(self):
        evidence = _fusion_evidence(
            "technical",
            {
                "status": "AVAILABLE",
                "evaluated_at_utc": datetime(2026, 11, 19, tzinfo=timezone.utc).isoformat(),
                "source_id": "Headway",
            },
            direction=EvidenceDirection.UP,
            evidence_ids=("candle-1", "candle-1", "candle-2", "candle-2"),
            context_flags=("FLAG_A", "FLAG_A"),
        )

        self.assertEqual(evidence.evidence_ids, ("candle-1", "candle-2"))
        self.assertEqual(evidence.context_flags, ("FLAG_A",))
        self.assertEqual(evidence.source_ids, ("Headway",))
        self.assertEqual(evidence.direction, EvidenceDirection.UP)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from eurusd_ai_monitor.engines.fusion_engine import (
    DirectionalAgreement,
    EvidenceDirection,
    EvidenceStatus,
    FusionEngine,
    FusionStatus,
    SpecialistEvidence,
)


class OptionalVisualFusionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)

    def evidence(self, specialist, direction, *, context_flags=()):
        return SpecialistEvidence(
            specialist=specialist,
            status=EvidenceStatus.AVAILABLE,
            direction=direction,
            evaluated_at_utc=self.now,
            source_ids=("local-test",),
            evidence_ids=(),
            reason_codes=(),
            context_flags=context_flags,
        )

    def test_visual_context_is_retained_but_does_not_vote_or_block_fusion(self):
        items = (
            self.evidence("technical", EvidenceDirection.UP),
            self.evidence("price_action", EvidenceDirection.UP),
            self.evidence("macro_calendar", EvidenceDirection.NEUTRAL),
            self.evidence("news", EvidenceDirection.NEUTRAL),
            self.evidence(
                "visual",
                EvidenceDirection.NEUTRAL,
                context_flags=("VISUAL_M1_DIRECTION_DOWN", "VISUAL_M5_DIRECTION_DOWN"),
            ),
        )
        result = FusionEngine().assess(self.now, items)

        self.assertEqual(result.status, FusionStatus.READY_FOR_RULES)
        self.assertEqual(result.directional_agreement, DirectionalAgreement.ALIGNED)
        self.assertEqual(result.directional_bias, EvidenceDirection.UP)
        self.assertIn("VISUAL_M1_DIRECTION_DOWN", result.context_flags)
        self.assertIn("visual", [item.specialist for item in result.specialist_evidence])

    def test_visual_specialist_cannot_cast_directional_vote(self):
        with self.assertRaisesRegex(ValueError, "context-only specialists"):
            self.evidence("visual", EvidenceDirection.DOWN)


if __name__ == "__main__":
    unittest.main()

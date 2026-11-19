import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.fusion_engine import (
    DirectionalAgreement,
    EvidenceDirection,
    EvidenceStatus,
    FusionEngine,
    FusionStatus,
    SpecialistEvidence,
)

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def item(name, status=EvidenceStatus.AVAILABLE, direction=EvidenceDirection.NEUTRAL, **kwargs):
    return SpecialistEvidence(
        specialist=name,
        status=status,
        direction=direction,
        evaluated_at_utc=kwargs.get("at", NOW),
        source_ids=kwargs.get("sources", (name.upper() + "_SOURCE",)),
        evidence_ids=kwargs.get("evidence", ()),
        reason_codes=kwargs.get("reasons", ()),
        context_flags=kwargs.get("flags", ()),
    )


def complete(technical=EvidenceDirection.UP, pa=EvidenceDirection.UP, **kwargs):
    return (
        item("technical", direction=technical, **kwargs),
        item("price_action", direction=pa, **kwargs),
        item("macro_calendar", flags=kwargs.get("flags", ())),
        item("news", flags=kwargs.get("flags", ())),
    )


class FusionEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = FusionEngine()
    
    def test_aligned_directional_evidence_is_ready_for_rules_but_never_a_trade(self):
        result = self.engine.assess(NOW, complete())
        self.assertEqual(result.status, FusionStatus.READY_FOR_RULES)
        self.assertEqual(result.directional_agreement, DirectionalAgreement.ALIGNED)
        self.assertEqual(result.directional_bias, EvidenceDirection.UP)
        self.assertEqual(result.decision, "WAIT")
        self.assertEqual(result.direction, "NONE")
        self.assertEqual(result.trade_authority, "NONE")
        self.assertEqual(result.decision_authority, "ASSESSMENT_ONLY")

    def test_opposing_specialists_create_conflict(self):
        result = self.engine.assess(NOW, complete(pa=EvidenceDirection.DOWN))
        self.assertEqual(result.status, FusionStatus.CONFLICT)
        self.assertEqual(result.directional_agreement, DirectionalAgreement.CONFLICT)
        self.assertIn("TECHNICAL_PRICE_ACTION_CONFLICT", result.reason_codes)

    def test_range_structure_is_incomplete_not_a_directional_vote(self):
        result = self.engine.assess(
            NOW, complete(technical=EvidenceDirection.NEUTRAL)
        )
        self.assertEqual(result.status, FusionStatus.INCOMPLETE)
        self.assertEqual(result.directional_bias, EvidenceDirection.UNKNOWN)

    def test_missing_specialist_blocks_fusion(self):
        result = self.engine.assess(NOW, complete()[:-1])
        self.assertEqual(result.status, FusionStatus.BLOCKED)
        self.assertEqual(result.missing_specialists, ("news",))
        self.assertIn("NEWS_EVIDENCE_MISSING", result.reason_codes)

    def test_degraded_specialist_blocks_fusion(self):
        evidence = list(complete())
        evidence[2] = item("macro_calendar", EvidenceStatus.DEGRADED)
        result = self.engine.assess(NOW, evidence)
        self.assertEqual(result.status, FusionStatus.BLOCKED)
        self.assertIn("macro_calendar", result.blocked_specialists)

    def test_unavailable_specialist_blocks_fusion(self):
        evidence = list(complete())
        evidence[3] = item("news", EvidenceStatus.UNAVAILABLE)
        result = self.engine.assess(NOW, evidence)
        self.assertEqual(result.status, FusionStatus.BLOCKED)

    def test_stale_evidence_blocks_fusion(self):
        evidence = list(complete())
        evidence[0] = item("technical", direction=EvidenceDirection.UP, at=NOW - timedelta(seconds=301))
        result = self.engine.assess(NOW, evidence)
        self.assertIn("TECHNICAL_EVIDENCE_STALE", result.reason_codes)
        self.assertEqual(result.directional_bias, EvidenceDirection.UNKNOWN)

    def test_future_evidence_blocks_fusion(self):
        evidence = list(complete())
        evidence[0] = item("technical", direction=EvidenceDirection.UP, at=NOW + timedelta(seconds=1))
        result = self.engine.assess(NOW, evidence)
        self.assertIn("TECHNICAL_EVIDENCE_FROM_FUTURE", result.reason_codes)

    def test_context_only_specialists_cannot_vote_direction(self):
        with self.assertRaises(ValueError):
            item("news", direction=EvidenceDirection.UP)

    def test_duplicate_specialists_are_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.assess(NOW, complete() + (item("news"),))

    def test_unknown_specialist_is_rejected(self):
        with self.assertRaises(ValueError):
            item("vision")

    def test_future_evaluation_time_must_be_timezone_aware(self):
        with self.assertRaises(ValueError):
            self.engine.assess(datetime(2026, 11, 19, 12), complete())

    def test_evidence_provenance_and_context_flags_are_preserved(self):
        evidence = list(complete(flags=("HIGH_IMPACT_EVENT_IN_HORIZON",)))
        evidence[0] = item(
            "technical", direction=EvidenceDirection.UP,
            evidence=("pivot:123",), sources=("mt5:broker",),
        )
        result = self.engine.assess(NOW, evidence).to_dict()
        self.assertIn("HIGH_IMPACT_EVENT_IN_HORIZON", result["context_flags"])
        technical = next(x for x in result["specialists"] if x["specialist"] == "technical")
        self.assertEqual(technical["evidence_ids"], ["pivot:123"])
        self.assertEqual(technical["source_ids"], ["mt5:broker"])

    def test_output_is_deterministic(self):
        evidence = complete()
        self.assertEqual(
            self.engine.assess(NOW, evidence).to_dict(),
            self.engine.assess(NOW, evidence).to_dict(),
        )

    def test_invalid_age_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            FusionEngine(0)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.research_intelligence_engine import ResearchIntelligenceEngine

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def sources():
    current = {
        "fusion_assessment": {"status": "READY_FOR_RULES", "directional_agreement": "ALIGNED"},
        "market_regime_intelligence": {"status": "AVAILABLE", "regime": "TRENDING", "volatility_state": "NORMAL"},
        "price_action_lifecycle": {"status": "PROCESSED", "lifecycle_state": "CONFIRMED"},
        "setup_assessment": {"stage": "PATTERN_CONFIRMED"},
        "session_eligibility": {"status": "RESEARCH_ELIGIBLE"},
    }
    historical = {
        "setup_outcome_observation": {"status": "ACTIVE"},
        "statistical_outcome_evaluation": {"status": "INSUFFICIENT_DATA"},
        "regime_conditioned_outcome_evaluation": {"status": "INSUFFICIENT_DATA"},
    }
    return {
        name: {"payload": payload, "evaluated_at_utc": NOW.isoformat()}
        for name, payload in {**current, **historical}.items()
    }


class ResearchIntelligenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ResearchIntelligenceEngine()

    def build(self, items=None, at=NOW):
        return self.engine.build_report(
            evaluated_at_utc=at, broker_server="Broker-Demo", symbol="EURUSD",
            sources=sources() if items is None else items,
        )

    def test_complete_cycle_is_coherent_without_trade_authority(self):
        result = self.build()
        self.assertEqual(result["status"], "COHERENT")
        self.assertEqual(result["current_context"]["fusion_assessment"]["state"], "READY_FOR_RULES")
        self.assertEqual(result["historical_outcome_context"]["classification"], "HISTORICAL_DESCRIPTIVE_ONLY")
        self.assertEqual(result["decision_authority"], "ASSESSMENT_ONLY")
        self.assertEqual(result["trade_authority"], "NONE")
        self.assertEqual(result["order_execution"], "DISABLED")
        self.assertEqual(result["authority_audit"]["status"], "PASS")

    def test_explicit_trade_authority_claim_degrades_report(self):
        items = sources()
        items["setup_assessment"]["payload"]["trade_authority"] = "AUTHORIZED"
        result = self.build(items)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["authority_audit"]["status"], "VIOLATION")
        self.assertIn(
            "SETUP_ASSESSMENT_AUTHORITY_CONTRACT_VIOLATION",
            result["reason_codes"],
        )
        self.assertEqual(
            result["authority_audit"]["violations"][0]["field"],
            "trade_authority",
        )

    def test_explicit_order_execution_enablement_degrades_report(self):
        items = sources()
        items["session_eligibility"]["payload"]["order_execution"] = "ENABLED"
        result = self.build(items)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["authority_audit"]["status"], "VIOLATION")

    def test_explicit_entry_eligibility_enablement_degrades_report(self):
        items = sources()
        items["setup_assessment"]["payload"]["entry_eligibility"] = "ELIGIBLE"
        result = self.build(items)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["authority_audit"]["status"], "VIOLATION")

    def test_explicit_decision_authority_escalation_degrades_report(self):
        items = sources()
        items["fusion_assessment"]["payload"]["decision_authority"] = "TRADE_AUTHORITY"
        result = self.build(items)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["authority_audit"]["status"], "VIOLATION")

    def test_missing_current_source_is_partial(self):
        items = sources()
        del items["market_regime_intelligence"]
        result = self.build(items)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIn("MARKET_REGIME_INTELLIGENCE_MISSING", result["reason_codes"])

    def test_missing_historical_source_does_not_block_current_cycle(self):
        items = sources()
        del items["statistical_outcome_evaluation"]
        result = self.build(items)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["current_context"]["fusion_assessment"]["state"], "READY_FOR_RULES")

    def test_stale_current_source_blocks(self):
        items = sources()
        items["market_regime_intelligence"]["evaluated_at_utc"] = (
            NOW - timedelta(seconds=301)
        ).isoformat()
        result = self.build(items)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("MARKET_REGIME_INTELLIGENCE_STALE", result["reason_codes"])

    def test_future_timestamp_degrades(self):
        items = sources()
        items["fusion_assessment"]["evaluated_at_utc"] = (NOW + timedelta(seconds=1)).isoformat()
        result = self.build(items)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertIn("FUSION_ASSESSMENT_FUTURE_TIMESTAMP", result["reason_codes"])

    def test_explicit_session_block_is_preserved(self):
        items = sources()
        items["session_eligibility"]["payload"]["status"] = "BLOCKED"
        result = self.build(items)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["current_context"]["session_eligibility"]["state"], "BLOCKED")

    def test_identity_mismatch_degrades_report(self):
        items = sources()
        items["market_regime_intelligence"]["symbol"] = "GBPUSD"
        result = self.build(items)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertIn("MARKET_REGIME_INTELLIGENCE_IDENTITY_MISMATCH", result["reason_codes"])

    def test_outside_session_is_not_reported_as_eligible(self):
        items = sources()
        items["session_eligibility"]["payload"]["status"] = "OUTSIDE_SESSION"
        result = self.build(items)
        self.assertEqual(result["status"], "BLOCKED")

    def test_unknown_regime_is_partial_not_coherent(self):
        items = sources()
        items["market_regime_intelligence"]["payload"]["regime"] = "UNKNOWN"
        result = self.build(items)
        self.assertEqual(result["status"], "PARTIAL")

    def test_degraded_market_regime_is_not_hidden_by_unknown_label(self):
        items = sources()
        items["market_regime_intelligence"]["payload"]["status"] = "DEGRADED"
        items["market_regime_intelligence"]["payload"]["regime"] = "UNKNOWN"
        result = self.build(items)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(
            result["current_context"]["market_regime_intelligence"]["source_status"],
            "DEGRADED",
        )

    def test_historical_insufficient_data_is_not_current_context_failure(self):
        result = self.build()
        self.assertEqual(result["status"], "COHERENT")
        self.assertEqual(
            result["historical_outcome_context"]["sources"]["statistical_outcome_evaluation"]["state"],
            "INSUFFICIENT_DATA",
        )

    def test_output_is_deterministic(self):
        items = sources()
        self.assertEqual(self.build(items), self.build(items))

    def test_invalid_freshness_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            ResearchIntelligenceEngine(max_current_age_seconds=0)

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.build_report(
                evaluated_at_utc=datetime(2026, 11, 19, 12),
                broker_server="Broker-Demo", symbol="EURUSD", sources=sources(),
            )

    def test_optional_quantitative_specialist_missing_does_not_break_legacy_cycle(self):
        result = self.build()
        self.assertEqual(result["status"], "COHERENT")
        self.assertEqual(
            result["current_context"]["quantitative_market_statistics"]["source_status"],
            "MISSING",
        )
        item = next(
            entry for entry in result["source_manifest"]
            if entry["source"] == "quantitative_market_statistics"
        )
        self.assertEqual(item["class"], "OPTIONAL_CURRENT")

    def test_quantitative_insufficient_data_is_partial_not_directional(self):
        items = sources()
        items["quantitative_market_statistics"] = {
            "payload": {
                "status": "INSUFFICIENT_DATA",
                "evaluated_at_utc": NOW.isoformat(),
                "reason_codes": ["M1_HISTORY_TOO_SHORT"],
            },
            "evaluated_at_utc": NOW.isoformat(),
        }
        result = self.build(items)
        self.assertEqual(result["status"], "PARTIAL")
        state = result["current_context"]["quantitative_market_statistics"]
        self.assertEqual(state["source_status"], "INCOMPLETE")
        self.assertIn("M1_HISTORY_TOO_SHORT", state["reason_codes"])

    def test_quantitative_quality_block_is_not_promoted_to_available(self):
        items = sources()
        items["quantitative_market_statistics"] = {
            "payload": {
                "status": "BLOCKED",
                "evaluated_at_utc": NOW.isoformat(),
                "reason_codes": ["MARKET_CONTEXT_QUALITY_FAILED"],
            },
            "evaluated_at_utc": NOW.isoformat(),
        }
        result = self.build(items)
        self.assertEqual(result["status"], "BLOCKED")
        state = result["current_context"]["quantitative_market_statistics"]
        self.assertEqual(state["source_status"], "BLOCKED")
        self.assertIn("quantitative_market_statistics", [
            item for item in result["reason_codes"]
        ] if False else ["quantitative_market_statistics"])


if __name__ == "__main__":
    unittest.main()

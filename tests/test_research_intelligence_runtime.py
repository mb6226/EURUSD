import unittest
from datetime import datetime, timezone

from eurusd_ai_monitor.engines.research_intelligence_runtime import (
    build_research_intelligence_payload,
)
from eurusd_ai_monitor.engines.research_intelligence_engine import ResearchIntelligenceEngine
from eurusd_ai_monitor.engines.research_intelligence_sources import (
    RESEARCH_SOURCE_NAMES,
    build_research_intelligence_sources,
)

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


class FakeEngine:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else {"status": "COHERENT"}
        self.error = error
        self.calls = []

    def build_report(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class ResearchIntelligenceRuntimeTests(unittest.TestCase):
    def test_successful_report_is_returned_without_rewriting(self):
        report = {
            "status": "COHERENT",
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        engine = FakeEngine(result=report)
        sources = {"fusion_assessment": {"payload": {"status": "READY_FOR_RULES"}}}

        result = build_research_intelligence_payload(
            engine,
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            sources=sources,
        )

        self.assertIs(result, report)
        self.assertEqual(len(engine.calls), 1)
        self.assertIs(engine.calls[0]["sources"], sources)
        self.assertEqual(engine.calls[0]["symbol"], "EURUSD")

    def test_engine_exception_fails_closed(self):
        engine = FakeEngine(error=RuntimeError("synthetic failure"))

        result = build_research_intelligence_payload(
            engine,
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            sources={},
        )

        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(
            result["reason_codes"], ["RESEARCH_INTELLIGENCE_ERROR:RuntimeError"]
        )
        self.assertEqual(result["decision_authority"], "ASSESSMENT_ONLY")
        self.assertEqual(result["trade_authority"], "NONE")
        self.assertEqual(result["order_execution"], "DISABLED")

    def test_invalid_engine_result_fails_closed(self):
        engine = FakeEngine(result=None)
        engine.result = None

        result = build_research_intelligence_payload(
            engine,
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            sources={},
        )

        self.assertEqual(result["status"], "DEGRADED")
        self.assertIn("RESEARCH_INTELLIGENCE_ERROR:TypeError", result["reason_codes"])


    def test_source_envelope_preserves_specialist_timestamps_and_identity(self):
        payloads = {
            name: {
                "status": "AVAILABLE",
                "evaluated_at_utc": NOW.isoformat(),
                "broker_server": "Broker-Demo",
                "symbol": "EURUSD",
            }
            for name in RESEARCH_SOURCE_NAMES
        }
        payloads["fusion_assessment"]["status"] = "READY_FOR_RULES"
        payloads["market_regime_intelligence"]["regime"] = "TRENDING"
        payloads["price_action_lifecycle"]["status"] = "NO_LIFECYCLE"
        payloads["setup_assessment"]["stage"] = "WAIT"
        payloads["session_eligibility"]["status"] = "RESEARCH_ELIGIBLE"
        payloads["setup_outcome_observation"]["status"] = "ACTIVE"
        payloads["statistical_outcome_evaluation"]["status"] = "INSUFFICIENT_DATA"
        payloads["regime_conditioned_outcome_evaluation"]["status"] = "INSUFFICIENT_DATA"
        sources = build_research_intelligence_sources(
            payloads, broker_server="Broker-Demo", symbol="EURUSD"
        )
        report = ResearchIntelligenceEngine().build_report(
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            sources=sources,
        )
        self.assertEqual(len(report["source_manifest"]), 14)
        manifest_sources = {item["source"] for item in report["source_manifest"]}
        self.assertIn("liquidity_microstructure_intelligence", manifest_sources)
        self.assertIs(sources["liquidity_microstructure_intelligence"]["payload"], payloads["liquidity_microstructure_intelligence"])
        self.assertEqual(sources["liquidity_microstructure_intelligence"]["evaluated_at_utc"], NOW.isoformat())
        self.assertEqual(report["status"], "COHERENT")
        self.assertEqual(sources["market_regime_intelligence"]["evaluated_at_utc"], NOW.isoformat())

    def test_missing_optional_liquidity_source_is_explicit_in_envelope(self):
        sources = build_research_intelligence_sources(
            {}, broker_server="Broker-Demo", symbol="EURUSD"
        )
        self.assertIn("liquidity_microstructure_intelligence", sources)
        self.assertIsNone(sources["liquidity_microstructure_intelligence"]["payload"])
        self.assertEqual(sources["liquidity_microstructure_intelligence"]["broker_server"], "Broker-Demo")
        self.assertEqual(sources["liquidity_microstructure_intelligence"]["symbol"], "EURUSD")

    def test_missing_specialist_timestamp_is_not_replaced_by_cycle_time(self):
        payloads = {
            name: {"status": "AVAILABLE", "evaluated_at_utc": NOW.isoformat()}
            for name in RESEARCH_SOURCE_NAMES
        }
        payloads["market_regime_intelligence"].pop("evaluated_at_utc")
        sources = build_research_intelligence_sources(
            payloads, broker_server="Broker-Demo", symbol="EURUSD"
        )
        self.assertIsNone(sources["market_regime_intelligence"]["evaluated_at_utc"])
        report = ResearchIntelligenceEngine().build_report(
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            sources=sources,
        )
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn(
            "MARKET_REGIME_INTELLIGENCE_TIMESTAMP_INVALID",
            report["reason_codes"],
        )

    def test_explicit_specialist_identity_mismatch_is_not_overwritten(self):
        payloads = {
            name: {"status": "AVAILABLE", "evaluated_at_utc": NOW.isoformat()}
            for name in RESEARCH_SOURCE_NAMES
        }
        payloads["market_regime_intelligence"]["provenance"] = {
            "broker_server": "Other-Broker", "symbol": "GBPUSD"
        }
        sources = build_research_intelligence_sources(
            payloads, broker_server="Broker-Demo", symbol="EURUSD"
        )
        self.assertEqual(
            sources["market_regime_intelligence"]["broker_server"], "Other-Broker"
        )
        self.assertEqual(sources["market_regime_intelligence"]["symbol"], "GBPUSD")
        report = ResearchIntelligenceEngine().build_report(
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            sources=sources,
        )
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn(
            "MARKET_REGIME_INTELLIGENCE_IDENTITY_MISMATCH",
            report["reason_codes"],
        )

    def test_explicit_null_specialist_identity_is_not_treated_as_omitted(self):
        payloads = {
            name: {"status": "AVAILABLE", "evaluated_at_utc": NOW.isoformat()}
            for name in RESEARCH_SOURCE_NAMES
        }
        payloads["market_regime_intelligence"]["provenance"] = {"symbol": None}
        sources = build_research_intelligence_sources(
            payloads, broker_server="Broker-Demo", symbol="EURUSD"
        )
        self.assertEqual(sources["market_regime_intelligence"]["symbol"], "")
        report = ResearchIntelligenceEngine().build_report(
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            sources=sources,
        )
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn(
            "MARKET_REGIME_INTELLIGENCE_IDENTITY_MISMATCH",
            report["reason_codes"],
        )

    def test_source_envelope_rejects_invalid_cycle_identity(self):
        with self.assertRaises(ValueError):
            build_research_intelligence_sources(
                {}, broker_server="", symbol="EURUSD"
            )

if __name__ == "__main__":
    unittest.main()

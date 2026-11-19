import unittest
from datetime import datetime, timezone

from eurusd_ai_monitor.engines.research_intelligence_runtime import (
    build_research_intelligence_payload,
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


if __name__ == "__main__":
    unittest.main()

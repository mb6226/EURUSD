from datetime import datetime, timezone
import unittest

from eurusd_ai_monitor.engines.central_scenario_runtime import (
    build_central_scenario_payload,
)


NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


class CaptureEngine:
    def __init__(self):
        self.kwargs = None

    def assess(self, **kwargs):
        self.kwargs = kwargs
        return {"status": "CAPTURED"}


class CentralScenarioRuntimeTests(unittest.TestCase):
    def test_runtime_binds_every_specialist_and_cycle_context(self):
        engine = CaptureEngine()
        specialists = {
            name: {"status": "AVAILABLE", "evaluated_at_utc": NOW.isoformat()}
            for name in (
                "macro_fundamentals_intelligence",
                "policy_rate_differential_intelligence",
                "intermarket_intelligence",
                "positioning_sentiment_intelligence",
                "quantitative_market_statistics",
                "liquidity_microstructure_intelligence",
            )
        }
        values = {
            "technical_analysis": {"status": "ANALYZED"},
            "price_action_lifecycle": {"status": "PROCESSED"},
            "market_regime_intelligence": {"status": "AVAILABLE"},
            "fusion_assessment": {"status": "READY_FOR_RULES"},
            "macro_calendar": {"status": "AVAILABLE"},
            "news_intelligence": {"status": "AVAILABLE"},
        }
        result = build_central_scenario_payload(
            engine,
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            technical_analysis=values["technical_analysis"],
            price_action_lifecycle=values["price_action_lifecycle"],
            market_regime_intelligence=values["market_regime_intelligence"],
            fusion_assessment=values["fusion_assessment"],
            specialist_reports=specialists,
            macro_calendar=values["macro_calendar"],
            news_intelligence=values["news_intelligence"],
            setup_assessment={"stage": "PATTERN_CONFIRMED"},
            session_eligibility={"status": "WAIT_SETUP"},
            setup_outcome_observation={"status": "ACTIVE"},
            statistical_outcome_evaluation={"status": "INSUFFICIENT_DATA"},
            regime_conditioned_outcome_evaluation={"status": "INSUFFICIENT_DATA"},
        )
        self.assertEqual(result, {"status": "CAPTURED"})
        self.assertEqual(engine.kwargs["evaluated_at_utc"], NOW)
        self.assertEqual(engine.kwargs["broker_server"], "Broker-Demo")
        self.assertEqual(engine.kwargs["symbol"], "EURUSD")
        self.assertEqual(
            set(engine.kwargs["sources"]),
            {
                "technical_analysis", "price_action_lifecycle",
                "market_regime_intelligence", "fusion_assessment",
                "macro_fundamentals_intelligence",
                "policy_rate_differential_intelligence",
                "intermarket_intelligence", "positioning_sentiment_intelligence",
                "quantitative_market_statistics",
                "liquidity_microstructure_intelligence",
                "macro_calendar", "news_intelligence", "setup_assessment",
                "session_eligibility", "setup_outcome_observation",
                "statistical_outcome_evaluation",
                "regime_conditioned_outcome_evaluation",
            },
        )
        self.assertIs(
            engine.kwargs["sources"]["intermarket_intelligence"],
            specialists["intermarket_intelligence"],
        )
        self.assertIs(
            engine.kwargs["sources"]["technical_analysis"],
            values["technical_analysis"],
        )

    def test_missing_optional_specialists_remain_none(self):
        engine = CaptureEngine()
        build_central_scenario_payload(
            engine,
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            technical_analysis=None,
            price_action_lifecycle=None,
            market_regime_intelligence=None,
            fusion_assessment=None,
            specialist_reports={},
            macro_calendar=None,
            news_intelligence=None,
        )
        self.assertIsNone(
            engine.kwargs["sources"]["macro_fundamentals_intelligence"]
        )
        self.assertIsNone(
            engine.kwargs["sources"]["liquidity_microstructure_intelligence"]
        )

    def test_invalid_specialist_container_is_rejected(self):
        with self.assertRaises(TypeError):
            build_central_scenario_payload(
                CaptureEngine(),
                evaluated_at_utc=NOW,
                broker_server="Broker-Demo",
                symbol="EURUSD",
                technical_analysis=None,
                price_action_lifecycle=None,
                market_regime_intelligence=None,
                fusion_assessment=None,
                specialist_reports=[],
                macro_calendar=None,
                news_intelligence=None,
            )


if __name__ == "__main__":
    unittest.main()

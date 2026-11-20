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
            point_in_time_market_regime={"status": "INSUFFICIENT_EVIDENCE", "as_of_utc": NOW.isoformat()},
            point_in_time_quantitative_statistics={"status": "INSUFFICIENT_EVIDENCE", "as_of_utc": NOW.isoformat()},
            session_time_intelligence={"status": "PARTIAL", "as_of_utc": NOW.isoformat()},
            cross_domain_relationship_intelligence={"status": "INSUFFICIENT_EVIDENCE", "as_of_utc": NOW.isoformat()},
            unified_historical_data_plane={"status": "PARTIAL", "as_of_utc": NOW.isoformat(), "read_mode": "STRICT_SYSTEM_KNOWLEDGE"},
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
                "point_in_time_market_regime", "point_in_time_quantitative_statistics",
                "session_time_intelligence", "cross_domain_relationship_intelligence",
                "unified_historical_data_plane",
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


    def test_point_in_time_reports_use_their_own_cutoff(self):
        engine = CaptureEngine()
        cutoff = "2026-11-19T11:59:00+00:00"
        build_central_scenario_payload(
            engine, evaluated_at_utc=NOW, broker_server="Broker-Demo", symbol="EURUSD",
            technical_analysis=None, price_action_lifecycle=None, market_regime_intelligence=None,
            fusion_assessment=None, specialist_reports={}, macro_calendar=None, news_intelligence=None,
            point_in_time_market_regime={"status": "INSUFFICIENT_EVIDENCE", "as_of_utc": cutoff},
        )
        self.assertEqual(engine.kwargs["sources"]["point_in_time_market_regime"]["evaluated_at_utc"], cutoff)

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


    def test_unified_pit_snapshot_builds_all_phase39_to42_reports(self):
        engine = CaptureEngine()
        snapshot = {
            "report_type": "MULTI_DOMAIN_POINT_IN_TIME_DATA_PLANE",
            "status": "PARTIAL",
            "read_mode": "STRICT_SYSTEM_KNOWLEDGE",
            "as_of_utc": NOW.isoformat(),
            "snapshot_sha256": "a" * 64,
            "registry_sha256": "b" * 64,
            "quality_eligible_product_count": 3,
            "analytics_domains": {},
            "spot_market_archive": {"streams": []},
        }
        build_central_scenario_payload(
            engine, evaluated_at_utc=NOW, broker_server="Broker-Demo", symbol="EURUSD",
            technical_analysis=None, price_action_lifecycle=None, market_regime_intelligence=None,
            fusion_assessment=None, specialist_reports={}, macro_calendar=None, news_intelligence=None,
            unified_historical_snapshot=snapshot,
        )
        sources = engine.kwargs["sources"]
        for name in ("point_in_time_market_regime", "point_in_time_quantitative_statistics",
                     "session_time_intelligence", "cross_domain_relationship_intelligence"):
            self.assertIn(sources[name]["status"], {"INSUFFICIENT_EVIDENCE", "PARTIAL", "BLOCKED"})
            self.assertEqual(datetime.fromisoformat(sources[name]["evaluated_at_utc"].replace("Z", "+00:00")), NOW)
        self.assertEqual(sources["unified_historical_data_plane"]["snapshot_sha256"], "a" * 64)

    def test_unified_snapshot_and_explicit_pit_reports_cannot_be_mixed(self):
        with self.assertRaises(ValueError):
            build_central_scenario_payload(
                CaptureEngine(), evaluated_at_utc=NOW, broker_server="Broker-Demo", symbol="EURUSD",
                technical_analysis=None, price_action_lifecycle=None, market_regime_intelligence=None,
                fusion_assessment=None, specialist_reports={}, macro_calendar=None, news_intelligence=None,
                unified_historical_snapshot={"read_mode": "STRICT_SYSTEM_KNOWLEDGE"},
                session_time_intelligence={"status": "AVAILABLE"},
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

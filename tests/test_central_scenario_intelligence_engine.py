from datetime import datetime, timedelta, timezone
import unittest

from eurusd_ai_monitor.engines.central_scenario_intelligence_engine import (
    CentralScenarioIntelligenceEngine,
)


NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def report(status="AVAILABLE", **values):
    return {
        "status": status,
        "evaluated_at_utc": NOW.isoformat(),
        "broker_server": "Broker-Demo",
        "symbol": "EURUSD",
        **values,
    }


def base_sources():
    return {
        "technical_analysis": report(
            "ANALYZED",
            trend={"direction": "UP", "swing_highs": [{"candle_id": "M5|A"}]},
            pivots=[{"evidence": {"candle_id": "M5|B"}}],
        ),
        "price_action_lifecycle": report(
            "PROCESSED",
            lifecycle_snapshot={
                "state": "CONFIRMED",
                "trend_direction": "UP",
                "evidence_candle_ids": ["M5|C", "M5|D"],
            },
        ),
        "market_regime_intelligence": report(
            "AVAILABLE", regime="TRENDING", trend_direction="UP",
            features={"atr_pips": "8.2"},
        ),
        "fusion_assessment": report(
            "READY_FOR_RULES", directional_bias="UP",
            decision="WAIT", trade_authority="NONE",
        ),
        "macro_fundamentals_intelligence": report(
            "AVAILABLE",
            inflation={
                "status": "AVAILABLE",
                "us_minus_euro_area_inflation_pp": "0.8",
                "reference_month": "2026-10",
            },
            unemployment={
                "status": "AVAILABLE",
                "us_minus_euro_area_unemployment_pp": "0.4",
                "reference_month": "2026-10",
            },
        ),
        "policy_rate_differential_intelligence": report(
            "AVAILABLE", usd_minus_eur_spread={"low": "1.0", "high": "1.5"},
            provenance={
                "eur_reference": {"source_record_id": "ECB-1"},
                "usd_reference": {"source_record_id": "FED-1"},
            },
        ),
        "intermarket_intelligence": report(
            "PARTIAL",
            drivers={
                "GOLD_USD_TROY_OUNCE": {
                    "status": "AVAILABLE",
                    "contemporaneous_correlation": "-0.32",
                    "aligned_return_count": 24,
                }
            },
        ),
        "positioning_sentiment_intelligence": report(
            "AVAILABLE",
            groups={
                "LEVERAGED_MONEY": {
                    "status": "AVAILABLE",
                    "interpretation": "NET_LONG",
                    "net_position_pct_open_interest": "12.5",
                    "historical_percentile": "78.0",
                }
            },
        ),
        "quantitative_market_statistics": report(
            "AVAILABLE",
            timeframes={
                "M5": {
                    "directional_efficiency_ratio": "0.62",
                    "return_distribution_pips": {"p95": "2.1"},
                }
            },
        ),
        "liquidity_microstructure_intelligence": report(
            "PARTIAL",
            timeframes={
                "M1": {
                    "status": "PARTIAL",
                    "spread": {"median": None},
                    "tick_activity": {"recent_to_baseline_median_ratio": "1.2"},
                }
            },
        ),
        "macro_calendar": report(
            "AVAILABLE", high_impact_count=2, event_count=5,
        ),
        "news_intelligence": report(
            "AVAILABLE", article_count=3,
        ),
        "setup_assessment": report("AVAILABLE", stage="PATTERN_CONFIRMED"),
        "session_eligibility": report("RESEARCH_ELIGIBLE"),
        "setup_outcome_observation": report("WAITING_FOR_SESSION_ELIGIBILITY", report_type="PRICE_EXCURSION_ONLY"),
        "statistical_outcome_evaluation": report("AVAILABLE", report_type="HISTORICAL_STATS"),
        "regime_conditioned_outcome_evaluation": report("AVAILABLE", report_type="REGIME_STATS"),
    }


class CentralScenarioIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = CentralScenarioIntelligenceEngine()

    def assess(self, sources):
        return self.engine.assess(
            evaluated_at_utc=NOW,
            broker_server="Broker-Demo",
            symbol="EURUSD",
            sources=sources,
        )

    def test_aligned_price_structure_produces_qualitative_up_hypothesis(self):
        result = self.assess(base_sources())
        self.assertEqual(result["directional_assessment"]["state"], "UP")
        self.assertEqual(
            result["scenario_hypotheses"][0]["status"], "LEADING_HYPOTHESIS"
        )
        self.assertEqual(result["scenario_hypotheses"][1]["status"], "ALTERNATIVE")
        self.assertIsNone(result["directional_assessment"]["numeric_probability"])
        self.assertIsNone(result["directional_assessment"]["calibrated_confidence"])
        self.assertEqual(result["decision_authority"], "ASSESSMENT_ONLY")
        self.assertEqual(result["trade_authority"], "NONE")
        self.assertEqual(result["order_execution"], "DISABLED")

    def test_opposing_price_structure_is_reported_as_conflict_not_averaged(self):
        sources = base_sources()
        sources["price_action_lifecycle"]["lifecycle_snapshot"]["trend_direction"] = "DOWN"
        result = self.assess(sources)
        self.assertEqual(result["directional_assessment"]["state"], "CONFLICTED")
        self.assertEqual(
            {item["status"] for item in result["scenario_hypotheses"]},
            {"UNRESOLVED_CONFLICT"},
        )

    def test_context_only_domains_never_create_directional_votes(self):
        sources = base_sources()
        sources["technical_analysis"] = None
        sources["price_action_lifecycle"] = None
        sources["market_regime_intelligence"] = None
        result = self.assess(sources)
        self.assertEqual(result["directional_assessment"]["state"], "UNRESOLVED")
        self.assertFalse(result["directional_assessment"]["supporting_price_structure_evidence"])
        self.assertEqual(
            result["cross_domain_context"]["policy_rates"]["context"],
            "USD_POLICY_RATE_PREMIUM",
        )
        self.assertFalse(result["cross_domain_context"]["policy_rates"]["directional_vote"])
        self.assertEqual(
            result["cross_domain_context"]["positioning"]["groups"]["LEVERAGED_MONEY"]["interpretation"],
            "NET_LONG",
        )

    def test_policy_context_tension_is_not_misreported_as_a_price_conflict(self):
        result = self.assess(base_sources())
        self.assertEqual(len(result["cross_domain_tensions"]), 1)
        self.assertEqual(
            result["cross_domain_tensions"][0]["type"],
            "PRICE_POLICY_CONTEXT_TENSION",
        )
        self.assertEqual(result["directional_assessment"]["state"], "UP")

    def test_future_dated_source_is_rejected_and_degrades_report(self):
        sources = base_sources()
        sources["technical_analysis"]["evaluated_at_utc"] = (
            NOW + timedelta(seconds=1)
        ).isoformat()
        result = self.assess(sources)
        self.assertEqual(result["evidence_coverage"]["domains"]["technical_analysis"]["status"], "INVALID_TIME")
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["directional_assessment"]["state"], "UP")

    def test_explicit_authority_escalation_is_rejected_from_scenario_evidence(self):
        sources = base_sources()
        sources["technical_analysis"]["trade_authority"] = "ENABLED"
        result = self.assess(sources)
        self.assertEqual(
            result["evidence_coverage"]["domains"]["technical_analysis"]["status"],
            "AUTHORITY_VIOLATION",
        )
        self.assertEqual(result["status"], "DEGRADED")
        self.assertNotIn(
            "technical_analysis",
            [item["source"] for item in result["directional_assessment"]["supporting_price_structure_evidence"]],
        )

    def test_stale_source_does_not_vote(self):
        sources = base_sources()
        sources["technical_analysis"]["evaluated_at_utc"] = (
            NOW - timedelta(seconds=301)
        ).isoformat()
        result = self.assess(sources)
        self.assertNotIn(
            "technical_analysis",
            [item["source"] for item in result["directional_assessment"]["supporting_price_structure_evidence"]],
        )

    def test_directional_and_ranging_regime_evidence_remains_mixed(self):
        sources = base_sources()
        sources["market_regime_intelligence"]["regime"] = "RANGING"
        result = self.assess(sources)
        self.assertEqual(result["directional_assessment"]["state"], "MIXED")
        self.assertEqual(
            result["cross_domain_tensions"][0]["type"],
            "PRICE_STRUCTURE_REGIME_TENSION",
        )
        self.assertTrue(all(
            item["status"] == "UNRESOLVED_CONFLICT"
            for item in result["scenario_hypotheses"]
        ))

    def test_historical_outcomes_and_setup_gates_are_not_directional_votes(self):
        result = self.assess(base_sources())
        self.assertFalse(
            result["cross_domain_context"]["operational_gates"]["directional_vote"]
        )
        self.assertFalse(
            result["cross_domain_context"]["operational_gates"]["execution_authority"]
        )
        self.assertEqual(
            result["cross_domain_context"]["operational_gates"]["session_status"],
            "RESEARCH_ELIGIBLE",
        )
        self.assertEqual(
            result["cross_domain_context"]["historical_research"]
            ["setup_outcome_observation"]["status"],
            "WAITING_FOR_SESSION_ELIGIBILITY",
        )
        self.assertFalse(
            result["cross_domain_context"]["historical_research"]
            ["statistical_outcome_evaluation"]["directional_vote"]
        )

    def test_stale_context_is_not_reused_for_tension_or_context_summary(self):
        sources = base_sources()
        sources["policy_rate_differential_intelligence"]["evaluated_at_utc"] = (
            NOW - timedelta(seconds=301)
        ).isoformat()
        result = self.assess(sources)
        self.assertEqual(
            result["cross_domain_context"]["policy_rates"]["context"],
            "UNAVAILABLE",
        )
        self.assertEqual(result["cross_domain_tensions"], [])

    def test_identity_mismatch_is_visible_and_excluded_from_direction(self):
        sources = base_sources()
        sources["price_action_lifecycle"]["symbol"] = "GBPUSD"
        result = self.assess(sources)
        self.assertEqual(
            result["evidence_coverage"]["domains"]["price_action_lifecycle"]["status"],
            "IDENTITY_MISMATCH",
        )
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["directional_assessment"]["state"], "UP")

    def test_missing_source_is_explicit_not_imputed(self):
        result = self.assess({})
        self.assertEqual(result["directional_assessment"]["state"], "UNRESOLVED")
        self.assertEqual(result["evidence_coverage"]["state"], "SPARSE")
        self.assertEqual(
            result["evidence_coverage"]["domains"]["technical_analysis"]["status"],
            "MISSING",
        )

    def test_range_regime_supports_range_hypothesis(self):
        sources = base_sources()
        sources["technical_analysis"]["trend"]["direction"] = "NEUTRAL"
        sources["price_action_lifecycle"]["lifecycle_snapshot"]["state"] = "FORMING"
        sources["market_regime_intelligence"]["regime"] = "RANGING"
        sources["market_regime_intelligence"]["trend_direction"] = "UNKNOWN"
        result = self.assess(sources)
        self.assertEqual(result["directional_assessment"]["state"], "RANGE")
        self.assertEqual(result["scenario_hypotheses"][2]["status"], "LEADING_HYPOTHESIS")

    def test_provenance_refs_are_preserved(self):
        result = self.assess(base_sources())
        refs = result["evidence_coverage"]["domains"]["technical_analysis"]["evidence_refs"]
        self.assertIn("M5|A", refs)
        self.assertIn("M5|B", refs)
        policy_refs = result["evidence_coverage"]["domains"]["policy_rate_differential_intelligence"]["evidence_refs"]
        self.assertIn("ECB-1", policy_refs)
        self.assertIn("FED-1", policy_refs)

    def test_calendar_and_news_are_event_risk_context_not_direction(self):
        result = self.assess(base_sources())
        event = result["cross_domain_context"]["event_risk"]
        self.assertEqual(event["high_impact_event_count"], 2)
        self.assertEqual(event["news_article_count"], 3)
        self.assertFalse(event["directional_vote"])

    def test_no_scenario_contains_execution_parameters(self):
        result = self.assess(base_sources())
        forbidden = {"entry", "stop_loss", "take_profit", "position_size", "order_type"}
        for scenario in result["scenario_hypotheses"]:
            self.assertFalse(forbidden.intersection(scenario))
        self.assertEqual(result["order_execution"], "DISABLED")


    def test_new_pit_domains_are_context_only_and_never_directional_votes(self):
        sources = base_sources()
        sources["point_in_time_market_regime"] = report(
            "INSUFFICIENT_EVIDENCE", market_regime="UNKNOWN", volatility_state="UNKNOWN"
        )
        sources["point_in_time_quantitative_statistics"] = report(
            "INSUFFICIENT_EVIDENCE", timeframes={}, excluded_timeframes={"M1": "NO_QUALITY_ELIGIBLE_STREAM"}
        )
        sources["session_time_intelligence"] = report(
            "PARTIAL", active_reference_sessions=["LONDON"], historical_session_coverage={}
        )
        sources["cross_domain_relationship_intelligence"] = report(
            "INSUFFICIENT_EVIDENCE", relationship_count=0, available_relationship_count=0, relationships=[]
        )
        sources["unified_historical_data_plane"] = report(
            "PARTIAL", read_mode="STRICT_SYSTEM_KNOWLEDGE", snapshot_sha256="a" * 64,
            quality_eligible_product_count=3
        )
        result = self.assess(sources)
        self.assertEqual(result["directional_assessment"]["state"], "UP")
        self.assertFalse(result["cross_domain_context"]["point_in_time_market_regime"]["directional_vote"])
        self.assertFalse(result["cross_domain_context"]["point_in_time_quantitative_statistics"]["directional_vote"])
        self.assertFalse(result["cross_domain_context"]["session_time"]["directional_vote"])
        self.assertFalse(result["cross_domain_context"]["cross_domain_relationships"]["directional_vote"])
        self.assertEqual(result["cross_domain_context"]["cross_domain_relationships"]["relationship_count"], 0)

    def test_shared_price_lineage_is_not_counted_as_independent_confirmation(self):
        sources = base_sources()
        sources["point_in_time_market_regime"] = report("INSUFFICIENT_EVIDENCE")
        sources["point_in_time_quantitative_statistics"] = report("INSUFFICIENT_EVIDENCE")
        sources["session_time_intelligence"] = report("PARTIAL")
        sources["cross_domain_relationship_intelligence"] = report("INSUFFICIENT_EVIDENCE")
        result = self.assess(sources)
        group = result["evidence_dependency_map"]["groups"]["EURUSD_BROKER_PRICE_LINEAGE"]
        self.assertGreaterEqual(group["member_count"], 5)
        self.assertEqual(group["independent_votes"], 0)
        self.assertTrue(group["shared_lineage_warning"])
        self.assertIsNone(result["scenario_assessment_contract"]["numeric_probability"])
        relationship_group = result["evidence_dependency_map"]["groups"]["CROSS_DOMAIN_RELATIONSHIP_DERIVED_LINEAGE"]
        self.assertEqual(relationship_group["independent_votes"], 0)
        self.assertTrue(relationship_group["shared_lineage_warning"])
        self.assertIn("intermarket", relationship_group["derived_from_domains"])

    def test_invalid_engine_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            self.engine.assess(
                evaluated_at_utc=datetime(2026, 11, 19, 12),
                broker_server="Broker-Demo",
                symbol="EURUSD",
                sources={},
            )


if __name__ == "__main__":
    unittest.main()

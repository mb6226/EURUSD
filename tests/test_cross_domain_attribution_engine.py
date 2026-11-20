import unittest
from datetime import datetime, timedelta, timezone
import json

from eurusd_ai_monitor.engines.cross_domain_attribution_engine import CrossDomainAttributionEngine


def replay_fixture(count=90):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    records = []
    for horizon, minutes in (("15M", 15), ("1H", 60), ("4H", 240)):
        for i in range(count):
            cutoff = start + timedelta(minutes=5 * i)
            snapshot = f"{horizon}-snapshot-{i}"
            context = {}
            for domain in ("spot_fx", "macro_fundamentals", "monetary_policy", "intermarket",
                           "positioning_sentiment", "news_event", "market_regime", "session_time",
                           "liquidity_microstructure", "cross_domain_relationship"):
                state = ("STATE_A", "STATE_B", "STATE_C")[i % 3]
                context[domain] = {
                    "status": "AVAILABLE", "state": state,
                    "evaluated_at_utc": cutoff.isoformat().replace("+00:00", "Z"),
                    "available_at_utc": cutoff.isoformat().replace("+00:00", "Z"),
                    "as_of_utc": cutoff.isoformat().replace("+00:00", "Z"),
                    "bound_forecast_snapshot_sha256": snapshot,
                    "context_snapshot_sha256": (f"{i:064x}"),
                    "source_lineage_ids": [f"{domain}-source-{i % 4}"],
                    "evidence_refs": [f"{domain}-evidence-{i}"],
                }
            records.append({
                "forecast_id": f"{horizon}-{i}", "replay_id": "replay-attribution",
                "forecast_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
                "target_close_time_utc": (cutoff + timedelta(minutes=minutes + 5)).isoformat().replace("+00:00", "Z"),
                "horizon": horizon, "forecast_status": "AVAILABLE",
                "expected_move_pips": 0.2, "actual_move_pips": 1.2 if i % 2 else 0.4,
                "forecast_direction": "UP", "outcome_direction": "UP" if i % 2 else "DOWN",
                "snapshot_sha256": snapshot, "anchor_version_id": f"anchor-{i}",
                "target_version_id": f"target-{i}", "domain_context": context,
            })
    return {
        "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY", "status": "COMPLETE",
        "replay_id": "replay-attribution", "source_history_sha256": "history-sha",
        "symbol": "EURUSD", "timeframe": "M5", "records": records,
        "integrity_policy": {
            "forecast_inputs_filtered_by_observed_and_as_of_at_each_cutoff": True,
            "only_closed_candles_used": True,
            "target_outcome_uses_first_closed_version_observed_after_target_close": True,
            "later_revisions_never_rewrite_forecast_or_target_version": True,
            "future_outcomes_excluded_from_forecast_snapshot": True,
            "system_knowledge_replay_only": True,
        },
    }


class CrossDomainAttributionEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = CrossDomainAttributionEngine(minimum_state_samples=10)

    def test_attribution_separate_per_horizon_and_domain(self):
        result = self.engine.analyze(replay_fixture())
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(set(result["by_horizon"]), {"15M", "1H", "4H"})
        self.assertEqual(result["by_horizon"]["1H"]["domains"]["macro_fundamentals"]["observed_state_count"], 3)

    def test_metrics_are_conditional_descriptive_associations(self):
        result = self.engine.analyze(replay_fixture())
        state = result["by_horizon"]["15M"]["domains"]["spot_fx"]["state_results"]["STATE_A"]
        self.assertEqual(state["status"], "DESCRIPTIVE_ASSOCIATION_AVAILABLE")
        self.assertIn("mae_delta_vs_horizon_baseline_pips", state["metrics"])
        self.assertEqual(state["independent_confirmation_count"], 0)
        self.assertEqual(result["interpretation_contract"]["causality"], "NOT_ESTABLISHED")

    def test_context_lookahead_rejected(self):
        replay = replay_fixture()
        row = replay["records"][0]
        future = datetime.fromisoformat(row["forecast_cutoff_utc"].replace("Z", "+00:00")) + timedelta(minutes=1)
        row["domain_context"]["spot_fx"]["available_at_utc"] = future.isoformat().replace("+00:00", "Z")
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["DOMAIN_CONTEXT_LOOKAHEAD_OR_TIME_INVALID"], 1)

    def test_snapshot_mismatch_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["domain_context"]["spot_fx"]["bound_forecast_snapshot_sha256"] = "wrong"
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["DOMAIN_CONTEXT_FORECAST_SNAPSHOT_MISMATCH"], 1)

    def test_missing_lineage_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["domain_context"]["macro_fundamentals"]["source_lineage_ids"] = []
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["DOMAIN_EVIDENCE_LINEAGE_MISSING"], 1)

    def test_unavailable_context_counted_not_imputed(self):
        replay = replay_fixture()
        feature = replay["records"][0]["domain_context"]["news_event"]
        feature["status"] = "UNAVAILABLE"
        feature["state"] = "UNAVAILABLE"
        feature["source_lineage_ids"] = []
        feature["evidence_refs"] = []
        result = self.engine.analyze(replay)
        state = result["by_horizon"]["15M"]["domains"]["news_event"]["state_results"]["UNAVAILABLE"]
        self.assertEqual(state["status"], "UNAVAILABLE")

    def test_small_state_groups_not_ranked_or_scored(self):
        replay = replay_fixture(12)
        result = self.engine.analyze(replay)
        state = result["by_horizon"]["15M"]["domains"]["spot_fx"]["state_results"]["STATE_A"]
        self.assertEqual(state["status"], "INSUFFICIENT_SAMPLE")
        self.assertIsNone(state["metrics"])

    def test_duplicate_forecast_rejected(self):
        replay = replay_fixture()
        replay["records"].append(dict(replay["records"][0]))
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["DUPLICATE_FORECAST_ID"], 1)

    def test_replay_integrity_required(self):
        replay = replay_fixture()
        replay["integrity_policy"]["system_knowledge_replay_only"] = False
        with self.assertRaisesRegex(ValueError, "INTEGRITY"):
            self.engine.analyze(replay)

    def test_incomplete_replay_blocked(self):
        replay = replay_fixture()
        replay["status"] = "BLOCKED"
        self.assertEqual(self.engine.analyze(replay)["status"], "BLOCKED")

    def test_invalid_domain_and_time_ignored(self):
        replay = replay_fixture()
        replay["records"][0]["domain_context"]["made_up"] = replay["records"][0]["domain_context"]["spot_fx"]
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["DOMAIN_UNSUPPORTED"], 1)

    def test_no_causal_or_feature_importance_claim(self):
        result = self.engine.analyze(replay_fixture())
        self.assertEqual(result["interpretation_contract"]["feature_importance"], "NOT_ESTIMATED")
        self.assertEqual(result["interpretation_contract"]["incremental_predictive_contribution"], "NOT_ESTIMATED")
        self.assertNotIn("importance_score", json.dumps(result))

    def test_dependency_groups_not_independent_votes(self):
        result = self.engine.analyze(replay_fixture())
        self.assertEqual(result["dependency_lineage_policy"]["EURUSD_PRICE_DERIVED_LINEAGE"]["independent_confirmation_count"], 0)
        self.assertIn("cross_domain_relationship", result["dependency_lineage_policy"]["DERIVED_CROSS_DOMAIN_LINEAGE"]["domains"])

    def test_invalid_snapshot_hash_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["domain_context"]["spot_fx"]["context_snapshot_sha256"] = "bad"
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["DOMAIN_CONTEXT_HASH_INVALID"], 1)

    def test_nonfinite_outcome_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["actual_move_pips"] = float("nan")
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["COMPLETED_OUTCOME_MISSING_OR_INVALID"], 1)

    def test_constructor_validation(self):
        with self.assertRaises(ValueError):
            CrossDomainAttributionEngine(minimum_state_samples=2)


if __name__ == "__main__":
    unittest.main()

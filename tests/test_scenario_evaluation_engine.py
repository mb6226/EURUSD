from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import unittest
from eurusd_ai_monitor.engines.scenario_evaluation_engine import ScenarioEvaluationEngine

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)

def envelope(*, horizon=60, available_offset=0, spec=True, leaders=1):
    hypotheses = [{"scenario_id": "EURUSD_UP_CONTINUATION", "status": "LEADING_HYPOTHESIS"}] if leaders else [{"scenario_id": "EURUSD_UP_CONTINUATION", "status": "UNRESOLVED"}]
    if leaders > 1:
        hypotheses.append({"scenario_id": "EURUSD_DOWN_CONTINUATION", "status": "LEADING_HYPOTHESIS"})
    report = {
        "report_type": "CENTRAL_MULTI_DOMAIN_SCENARIO_INTELLIGENCE", "engine_version": "1.1.0",
        "status": "ASSESSMENT_ONLY", "evaluated_at_utc": T0.isoformat(),
        "broker_server": "Headway-Real", "symbol": "EURUSD",
        "directional_assessment": {"state": "UP"}, "scenario_hypotheses": hypotheses,
    }
    if spec:
        report["scenario_evaluation_spec"] = {
            "horizon_minutes": horizon, "outcome_classifier": "CLOSED_BAR_CLOSE_TO_CLOSE_CLASSIFICATION",
            "invalidation_rules_version": "test-v1",
        }
    digest = sha256(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()
    return {"report": report, "available_at_utc": (T0 + timedelta(seconds=available_offset)).isoformat(), "report_sha256": digest}

def outcome(label="EURUSD_UP_CONTINUATION", horizon=60):
    end = T0 + timedelta(minutes=horizon)
    return {
        "broker_server": "Headway-Real", "symbol": "EURUSD", "outcome_label": label,
        "horizon_minutes": horizon, "window_start_utc": T0.isoformat(), "window_end_utc": end.isoformat(),
        "observed_at_utc": end.isoformat(), "as_of_utc": end.isoformat(),
        "classification_method": "CLOSED_BAR_CLOSE_TO_CLOSE_CLASSIFICATION",
        "price_basis": "BID", "bar_time_basis": "UTC", "source_version_ids": ["v-100", "v-101"],
        "evidence_sha256": "a" * 64,
    }

class ScenarioEvaluationEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ScenarioEvaluationEngine()
        self.cutoff = T0 + timedelta(hours=2)

    def evaluate(self, scenarios, outcomes):
        return self.engine.evaluate(scenarios, outcomes, broker_server="Headway-Real", evaluation_cutoff_utc=self.cutoff)

    def test_empty_archive_is_explicitly_no_archived_scenarios(self):
        result = self.evaluate([], [])
        self.assertEqual(result["status"], "NO_ARCHIVED_SCENARIOS")
        self.assertEqual(result["scored_scenario_count"], 0)
        self.assertIsNone(result["scenario_match_rate"])

    def test_valid_exact_horizon_scenario_is_scored(self):
        result = self.evaluate([envelope()], [outcome()])
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["scored_scenario_count"], 1)
        self.assertEqual(result["scenario_match_rate"], "1.0")

    def test_mismatch_is_not_a_profit_claim(self):
        result = self.evaluate([envelope()], [outcome("EURUSD_DOWN_CONTINUATION")])
        self.assertEqual(result["scenario_match_rate"], "0.0")
        self.assertIn("not trading profitability", " ".join(result["limitations"]))

    def test_missing_explicit_horizon_is_rejected(self):
        result = self.evaluate([envelope(spec=False)], [outcome()])
        self.assertEqual(result["rejected_counts"]["SCENARIO_EVALUATION_SPEC_MISSING"], 1)

    def test_report_not_archived_at_issue_time_is_rejected(self):
        result = self.evaluate([envelope(available_offset=1)], [outcome()])
        self.assertEqual(result["rejected_counts"]["SCENARIO_NOT_ARCHIVED_AT_ISSUANCE"], 1)

    def test_archive_hash_mismatch_is_rejected(self):
        item = envelope()
        item["report_sha256"] = "b" * 64
        result = self.evaluate([item], [outcome()])
        self.assertEqual(result["rejected_counts"]["SCENARIO_ARCHIVE_HASH_MISMATCH"], 1)

    def test_non_unique_leading_hypothesis_is_rejected(self):
        result = self.evaluate([envelope(leaders=2)], [outcome()])
        self.assertEqual(result["rejected_counts"]["SCENARIO_LEADING_HYPOTHESIS_NOT_UNIQUE"], 1)

    def test_future_outcome_is_excluded(self):
        row = outcome()
        row["observed_at_utc"] = (self.cutoff + timedelta(seconds=1)).isoformat()
        result = self.evaluate([envelope()], [row])
        self.assertEqual(result["rejected_counts"]["OUTCOME_AFTER_EVALUATION_CUTOFF"], 1)

    def test_unverified_outcome_price_basis_is_rejected(self):
        row = outcome()
        row["price_basis"] = "UNKNOWN"
        result = self.evaluate([envelope()], [row])
        self.assertEqual(result["rejected_counts"]["OUTCOME_PRICE_BASIS_UNVERIFIED"], 1)

    def test_horizon_and_window_must_match_exactly(self):
        result = self.evaluate([envelope()], [outcome(horizon=30)])
        self.assertGreater(len(result["rejected_counts"]), 0)
        self.assertEqual(result["scored_scenario_count"], 0)

    def test_identity_mismatch_is_rejected(self):
        row = outcome()
        row["symbol"] = "GBPUSD"
        result = self.evaluate([envelope()], [row])
        self.assertEqual(result["rejected_counts"]["OUTCOME_IDENTITY_MISMATCH"], 1)

if __name__ == "__main__":
    unittest.main()

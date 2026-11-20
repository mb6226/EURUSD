import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eurusd_ai_monitor.engines.continuous_learning_research_engine import ContinuousLearningResearchEngine
from eurusd_ai_monitor.storage.continuous_learning_research_store import ContinuousLearningResearchStore


def fixture_reports():
    replay = {
        "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY", "status": "COMPLETE",
        "replay_id": "replay-1", "source_history_sha256": "a" * 64,
        "integrity_policy": {
            "forecast_inputs_filtered_by_observed_and_as_of_at_each_cutoff": True,
            "only_closed_candles_used": True,
            "target_outcome_uses_first_closed_version_observed_after_target_close": True,
            "later_revisions_never_rewrite_forecast_or_target_version": True,
            "future_outcomes_excluded_from_forecast_snapshot": True,
            "system_knowledge_replay_only": True,
        },
    }
    wf = {"report_type": "EURUSD_WALK_FORWARD_VALIDATION", "status": "AVAILABLE",
          "replay_id": "replay-1", "source_history_sha256": "a" * 64, "by_horizon": {}}
    attr = {"report_type": "EURUSD_CROSS_DOMAIN_ATTRIBUTION", "status": "AVAILABLE",
            "replay_id": "replay-1", "source_history_sha256": "a" * 64, "by_horizon": {}}
    for h in ("15M", "1H", "4H"):
        wf["by_horizon"][h] = {"status": "WALK_FORWARD_EVALUATED", "fold_count": 2,
                               "completed_outcome_count": 120, "folds": [{}, {}]}
        attr["by_horizon"][h] = {"status": "ATTRIBUTION_AVAILABLE", "sample_count": 120}
    return replay, wf, attr


class ContinuousLearningResearchEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ContinuousLearningResearchEngine()

    def test_complete_matching_evidence_ready_for_research_review_only(self):
        reports = fixture_reports()
        result = self.engine.assess(*reports)
        self.assertEqual(result["status"], "READY_FOR_GOVERNED_RESEARCH_REVIEW")
        self.assertEqual(result["learning_policy"]["candidate_state"], "RESEARCH_ONLY")
        self.assertFalse(result["learning_policy"]["automatic_model_promotion"])

    def test_blocked_replay_blocks_learning(self):
        reports = fixture_reports()
        reports[0]["status"] = "BLOCKED"
        result = self.engine.assess(*reports)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("COMPLETE_POINT_IN_TIME_REPLAY_REQUIRED", result["blocker_codes"])

    def test_replay_mismatch_blocks_cross_report_join(self):
        reports = fixture_reports()
        reports[2]["replay_id"] = "other-replay"
        result = self.engine.assess(*reports)
        self.assertIn("ATTRIBUTION_REPLAY_OR_SOURCE_MISMATCH", result["blocker_codes"])

    def test_missing_integrity_policy_blocks(self):
        reports = fixture_reports()
        reports[0]["integrity_policy"]["system_knowledge_replay_only"] = False
        result = self.engine.assess(*reports)
        self.assertIn("REPLAY_INTEGRITY_POLICY_UNVERIFIED", result["blocker_codes"])

    def test_insufficient_fold_count_blocks_horizon(self):
        reports = fixture_reports()
        reports[1]["by_horizon"]["1H"]["fold_count"] = 1
        reports[1]["by_horizon"]["1H"]["folds"] = [{}]
        result = self.engine.assess(*reports)
        self.assertEqual(result["horizon_gates"]["1H"]["status"], "BLOCKED_OR_INSUFFICIENT")

    def test_insufficient_samples_blocks_horizon(self):
        reports = fixture_reports()
        reports[1]["by_horizon"]["4H"]["completed_outcome_count"] = 20
        result = self.engine.assess(*reports)
        self.assertIn("4H_OOS_RESEARCH_GATE_NOT_MET", result["blocker_codes"])

    def test_manifest_hashes_and_identity_deterministic(self):
        kwargs = dict(experiment_name="test", hypothesis="candidate improves baseline",
                      engine_id="forecast", engine_version="v1", code_sha256="b" * 64,
                      parameter_sha256="c" * 64, replay_id="r1",
                      source_history_sha256="a" * 64, created_at_utc="2026-11-20T00:00:00Z")
        one = self.engine.build_experiment_manifest(**kwargs)
        two = self.engine.build_experiment_manifest(**kwargs)
        self.assertEqual(one["experiment_id"], two["experiment_id"])
        self.assertEqual(one["candidate_state"], "RESEARCH_ONLY")

    def test_manifest_rejects_bad_hash(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.engine.build_experiment_manifest(
                experiment_name="x", hypothesis="y", engine_id="e", engine_version="1",
                code_sha256="bad", parameter_sha256="c" * 64, replay_id="r",
                source_history_sha256="a" * 64, created_at_utc="2026-11-20T00:00:00Z")


class ContinuousLearningResearchStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ContinuousLearningResearchStore(Path(self.tmp.name) / "ledger.sqlite")
        self.manifest = ContinuousLearningResearchEngine.build_experiment_manifest(
            experiment_name="test", hypothesis="h", engine_id="engine", engine_version="v1",
            code_sha256="b" * 64, parameter_sha256="c" * 64, replay_id="r1",
            source_history_sha256="a" * 64, created_at_utc="2026-11-20T00:00:00Z")

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_experiment_idempotent(self):
        first = self.store.append_experiment(self.manifest)
        second = self.store.append_experiment(self.manifest)
        self.assertEqual(first, second)

    def test_store_rejects_forged_manifest_identity(self):
        forged = dict(self.manifest)
        forged["hypothesis"] = "changed after hashing"
        with self.assertRaisesRegex(ValueError, "DOES_NOT_MATCH"):
            self.store.append_experiment(forged)

    def test_append_evaluation_requires_matching_replay(self):
        self.store.append_experiment(self.manifest)
        with self.assertRaisesRegex(ValueError, "MISMATCH"):
            self.store.append_evaluation(
                experiment_id=self.manifest["experiment_id"], replay_id="wrong",
                source_history_sha256="a" * 64, evaluated_at_utc="2026-11-20T01:00:00Z",
                report={"status": "COMPLETE", "replay_id": "wrong", "source_history_sha256": "a" * 64})

    def test_evaluation_and_review_event_are_append_only(self):
        self.store.append_experiment(self.manifest)
        evaluation_id = self.store.append_evaluation(
            experiment_id=self.manifest["experiment_id"], replay_id="r1",
            source_history_sha256="a" * 64, evaluated_at_utc="2026-11-20T01:00:00Z",
            report={"status": "COMPLETE", "replay_id": "r1", "source_history_sha256": "a" * 64})
        event_id = self.store.append_review_event(
            experiment_id=self.manifest["experiment_id"], occurred_at_utc="2026-11-20T02:00:00Z",
            review_state="RESEARCH_ONLY", rationale="Await more independent OOS evidence.")
        self.assertTrue(evaluation_id)
        self.assertTrue(event_id)
        con = sqlite3.connect(self.store.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE research_experiments SET manifest_json='{}'")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("DELETE FROM research_evaluations")
        finally:
            con.close()
        self.assertEqual(self.store.integrity_check(), "ok")

    def test_review_state_cannot_auto_promote(self):
        self.store.append_experiment(self.manifest)
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED"):
            self.store.append_review_event(
                experiment_id=self.manifest["experiment_id"], occurred_at_utc="2026-11-20T02:00:00Z",
                review_state="PROMOTED", rationale="not permitted")


if __name__ == "__main__":
    unittest.main()

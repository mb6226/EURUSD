import json
import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.walk_forward_validation_engine import WalkForwardValidationEngine


def replay_fixture(count=360, *, error_fn=None):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    records = []
    for horizon, minutes in (("15M", 15), ("1H", 60), ("4H", 240)):
        for i in range(count):
            cutoff = start + timedelta(minutes=5 * i)
            error = error_fn(i) if error_fn else (0.5 if i % 5 else 2.5)
            expected, actual, dispersion = 0.2, 0.2 + error, 1.0
            records.append({
                "forecast_id": f"{horizon}-{i}", "replay_id": "replay-wf",
                "forecast_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
                "target_close_time_utc": (cutoff + timedelta(minutes=minutes + 5)).isoformat().replace("+00:00", "Z"),
                "horizon": horizon, "forecast_status": "AVAILABLE",
                "expected_move_pips": expected, "actual_move_pips": actual,
                "direction_hit": True, "forecast_direction": "UP", "outcome_direction": "UP",
                "snapshot_sha256": f"snapshot-{horizon}-{i}",
                "anchor_version_id": f"anchor-{horizon}-{i}",
                "target_version_id": f"target-{horizon}-{i}",
                "forecast_json": {
                    "expected_move_pips_baseline": expected,
                    "historical_dispersion_pips": dispersion,
                    "descriptive_band_1_sigma_pips": [expected-dispersion, expected+dispersion],
                    "descriptive_band_2_sigma_pips": [expected-2*dispersion, expected+2*dispersion],
                    "numeric_probability": None, "calibrated_confidence": None,
                },
            })
    return {
        "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY", "status": "COMPLETE",
        "replay_id": "replay-wf", "source_history_sha256": "source-hash",
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


class WalkForwardValidationEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = WalkForwardValidationEngine(
            minimum_training_samples=30, test_window_samples=20,
            maximum_training_samples=100, minimum_folds=2,
        )

    def test_walk_forward_evaluates_each_horizon_separately(self):
        result = self.engine.validate(replay_fixture())
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(set(result["by_horizon"]), {"15M", "1H", "4H"})
        for horizon in result["by_horizon"].values():
            self.assertEqual(horizon["status"], "WALK_FORWARD_EVALUATED")
            self.assertGreaterEqual(horizon["fold_count"], 2)

    def test_training_labels_mature_before_test_start(self):
        result = self.engine.validate(replay_fixture())
        for horizon in result["by_horizon"].values():
            for fold in horizon["folds"]:
                self.assertTrue(fold["training_labels_available_by_test_start"])
                self.assertTrue(fold["strict_temporal_separation"])

    def test_non_overlapping_test_windows(self):
        result = self.engine.validate(replay_fixture())
        for horizon in result["by_horizon"].values():
            folds = horizon["folds"]
            for left, right in zip(folds, folds[1:]):
                self.assertLess(left["test_end_utc"], right["test_start_utc"])

    def test_training_window_is_bounded(self):
        result = self.engine.validate(replay_fixture())
        for horizon in result["by_horizon"].values():
            for fold in horizon["folds"]:
                self.assertLessEqual(fold["training_count"], 100)

    def test_interval_multipliers_are_fit_per_fold(self):
        result = self.engine.validate(replay_fixture())
        fold = result["by_horizon"]["15M"]["folds"][0]
        self.assertEqual(set(fold["training_fitted_interval_results"]), {"0.80", "0.90", "0.95"})
        self.assertIn("training_multiplier", fold["training_fitted_interval_results"]["0.90"])

    def test_aggregate_and_fold_stability_metrics(self):
        result = self.engine.validate(replay_fixture())
        horizon = result["by_horizon"]["1H"]
        self.assertIn("weighted_mean_absolute_error_pips", horizon["aggregate"])
        self.assertIn("fold_mae_population_stddev_pips", horizon["fold_stability"])

    def test_horizons_are_not_pooled(self):
        result = self.engine.validate(replay_fixture())
        self.assertEqual(result["accepted_completed_records"], 1080)
        self.assertEqual(result["by_horizon"]["4H"]["completed_outcome_count"], 360)

    def test_insufficient_history_blocks(self):
        result = self.engine.validate(replay_fixture(45))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(all(v["status"] == "BLOCKED_INSUFFICIENT_WALK_FORWARD_FOLDS" for v in result["by_horizon"].values()))

    def test_incomplete_replay_blocks(self):
        replay = replay_fixture()
        replay["status"] = "BLOCKED"
        self.assertEqual(self.engine.validate(replay)["status"], "BLOCKED")

    def test_integrity_policy_required(self):
        replay = replay_fixture()
        replay["integrity_policy"]["system_knowledge_replay_only"] = False
        with self.assertRaisesRegex(ValueError, "INTEGRITY"):
            self.engine.validate(replay)

    def test_wrong_report_type_rejected(self):
        replay = replay_fixture()
        replay["report_type"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED"):
            self.engine.validate(replay)

    def test_missing_outcomes_are_not_imputed(self):
        replay = replay_fixture()
        replay["records"][0]["actual_move_pips"] = None
        result = self.engine.validate(replay)
        self.assertEqual(result["accepted_completed_records"], 1079)

    def test_duplicate_forecast_ids_rejected(self):
        replay = replay_fixture()
        replay["records"].append(dict(replay["records"][0]))
        result = self.engine.validate(replay)
        self.assertEqual(result["rejected_counts"]["DUPLICATE_FORECAST_ID"], 1)

    def test_bad_dispersion_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["forecast_json"]["historical_dispersion_pips"] = 0
        result = self.engine.validate(replay)
        self.assertEqual(result["rejected_counts"]["BASELINE_DISPERSION_INVALID"], 1)

    def test_bad_band_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["forecast_json"]["descriptive_band_1_sigma_pips"] = [-99, 99]
        result = self.engine.validate(replay)
        self.assertEqual(result["rejected_counts"]["DESCRIPTIVE_BANDS_INCONSISTENT"], 1)

    def test_replay_identity_mismatch_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["replay_id"] = "other"
        result = self.engine.validate(replay)
        self.assertEqual(result["rejected_counts"]["REPLAY_ID_MISMATCH"], 1)

    def test_future_or_invalid_target_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["target_close_time_utc"] = replay["records"][0]["forecast_cutoff_utc"]
        result = self.engine.validate(replay)
        self.assertEqual(result["rejected_counts"]["FORECAST_TARGET_TIME_INVALID"], 1)

    def test_probabilities_are_not_synthesized(self):
        result = self.engine.validate(replay_fixture())
        self.assertNotIn("probability", json.dumps(result).lower())

    def test_constructor_validation(self):
        with self.assertRaises(ValueError):
            WalkForwardValidationEngine(minimum_training_samples=10)
        with self.assertRaises(ValueError):
            WalkForwardValidationEngine(test_window_samples=5)
        with self.assertRaises(ValueError):
            WalkForwardValidationEngine(maximum_training_samples=20, minimum_training_samples=30)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.uncertainty_calibration_engine import UncertaintyCalibrationEngine


def replay_fixture(count=120, *, dispersion=2.0, error_fn=None):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    records = []
    for horizon in ("15M", "1H", "4H"):
        for i in range(count):
            cutoff = start + timedelta(minutes=5 * i)
            error = error_fn(i) if error_fn else (0.5 if i % 4 else 3.0)
            expected, actual = 0.25, 0.25 + error
            records.append({
                "forecast_id": f"{horizon}-{i}", "replay_id": "replay-1",
                "forecast_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
                "target_close_time_utc": (cutoff + timedelta(minutes={"15M": 20, "1H": 65, "4H": 245}[horizon])).isoformat().replace("+00:00", "Z"),
                "horizon": horizon, "forecast_status": "AVAILABLE",
                "expected_move_pips": expected, "actual_move_pips": actual,
                "snapshot_sha256": f"snapshot-{horizon}-{i}",
                "anchor_version_id": f"anchor-{i}", "target_version_id": f"target-{i}",
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
        "replay_id": "replay-1", "source_history_sha256": "history-hash",
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


class UncertaintyCalibrationEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = UncertaintyCalibrationEngine(
            minimum_calibration_samples=30, minimum_evaluation_samples=20,
        )

    def test_chronological_split_and_three_horizons(self):
        result = self.engine.calibrate(replay_fixture())
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(set(result["by_horizon"]), {"15M", "1H", "4H"})
        for report in result["by_horizon"].values():
            self.assertEqual(report["status"], "CALIBRATED_ON_HOLDOUT")
            self.assertTrue(report["fit_evaluation_cutoffs_strictly_separated"])
            self.assertGreaterEqual(report["calibration_sample_count"], 30)
            self.assertGreaterEqual(report["evaluation_sample_count"], 20)

    def test_calibration_uses_only_earlier_partition(self):
        result = self.engine.calibrate(replay_fixture())
        row = result["by_horizon"]["15M"]
        self.assertLess(row["calibration_cutoff_end_utc"], row["evaluation_cutoff_start_utc"])

    def test_holdout_coverage_and_width_are_reported(self):
        row = self.engine.calibrate(replay_fixture())["by_horizon"]["1H"]
        metric = row["target_coverage_results"]["0.90"]
        self.assertEqual(metric["status"], "EVALUATED")
        self.assertGreater(metric["calibration_multiplier"], 0)
        self.assertGreater(metric["mean_interval_width_pips"], 0)
        self.assertGreaterEqual(metric["evaluation_sample_count"], 20)

    def test_horizons_are_never_pooled(self):
        result = self.engine.calibrate(replay_fixture())
        self.assertEqual(result["accepted_completed_records"], 360)
        self.assertEqual(result["by_horizon"]["15M"]["sample_count"], 120)

    def test_insufficient_sample_blocks_per_horizon(self):
        result = self.engine.calibrate(replay_fixture(35))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(all(v["status"] == "BLOCKED_INSUFFICIENT_COMPLETED_SAMPLES" for v in result["by_horizon"].values()))

    def test_incomplete_replay_blocked(self):
        replay = replay_fixture()
        replay["status"] = "BLOCKED"
        result = self.engine.calibrate(replay)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("REPLAY_NOT_COMPLETE", result["reason_codes"])

    def test_missing_integrity_flag_rejected(self):
        replay = replay_fixture()
        replay["integrity_policy"]["system_knowledge_replay_only"] = False
        with self.assertRaisesRegex(ValueError, "INTEGRITY"):
            self.engine.calibrate(replay)

    def test_wrong_report_type_rejected(self):
        replay = replay_fixture()
        replay["report_type"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED"):
            self.engine.calibrate(replay)

    def test_missing_outcome_not_imputed(self):
        replay = replay_fixture()
        replay["records"][0]["actual_move_pips"] = None
        result = self.engine.calibrate(replay)
        self.assertEqual(result["by_horizon"]["15M"]["sample_count"], 119)
        self.assertEqual(result["accepted_completed_records"], 359)

    def test_duplicate_forecast_id_rejected(self):
        replay = replay_fixture()
        replay["records"].append(dict(replay["records"][0]))
        result = self.engine.calibrate(replay)
        self.assertEqual(result["rejected_counts"]["DUPLICATE_FORECAST_ID"], 1)

    def test_bad_dispersion_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["forecast_json"]["historical_dispersion_pips"] = 0
        result = self.engine.calibrate(replay)
        self.assertEqual(result["rejected_counts"]["DISPERSION_OR_EXPECTED_MOVE_INVALID"], 1)

    def test_inconsistent_descriptive_band_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["forecast_json"]["descriptive_band_1_sigma_pips"] = [-99, 99]
        result = self.engine.calibrate(replay)
        self.assertEqual(result["rejected_counts"]["DESCRIPTIVE_BANDS_INCONSISTENT"], 1)

    def test_future_target_time_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["target_close_time_utc"] = replay["records"][0]["forecast_cutoff_utc"]
        result = self.engine.calibrate(replay)
        self.assertEqual(result["rejected_counts"]["FORECAST_TARGET_TIME_INVALID"], 1)

    def test_probability_is_not_synthesized(self):
        result = self.engine.calibrate(replay_fixture())
        self.assertFalse(result["calibration_contract"]["probability_or_directional_confidence_emitted"])
        self.assertNotIn("probability", str(result["by_horizon"]).lower())

    def test_live_forecast_is_not_modified(self):
        result = self.engine.calibrate(replay_fixture())
        self.assertFalse(result["calibration_contract"]["multipliers_applied_to_live_forecasts"])
        self.assertFalse(result["calibration_contract"]["phase44_forecast_engine_modified"])

    def test_replay_id_mismatch_rejected(self):
        replay = replay_fixture()
        replay["records"][0]["replay_id"] = "different"
        result = self.engine.calibrate(replay)
        self.assertEqual(result["rejected_counts"]["REPLAY_ID_MISMATCH"], 1)

    def test_constructor_validation(self):
        with self.assertRaises(ValueError):
            UncertaintyCalibrationEngine(minimum_calibration_samples=5)
        with self.assertRaises(ValueError):
            UncertaintyCalibrationEngine(calibration_fraction=0.9)


if __name__ == "__main__":
    unittest.main()

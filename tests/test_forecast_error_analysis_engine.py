from copy import deepcopy
import unittest
from eurusd_ai_monitor.engines.forecast_error_analysis_engine import ForecastErrorAnalysisEngine

def fixture():
    records = []
    for horizon, count in (("15M", 6), ("1H", 5), ("4H", 4)):
        for i in range(count):
            expected = float(i - 2)
            actual = expected + (0.5 if i % 2 else -0.5)
            direction = "UP" if expected > 0.05 else "DOWN" if expected < -0.05 else "NEUTRAL"
            outcome = "UP" if actual > 0 else "DOWN" if actual < 0 else "NEUTRAL"
            records.append({
                "forecast_id": f"{horizon}-{i}", "horizon": horizon,
                "forecast_status": "AVAILABLE", "forecast_direction": direction,
                "outcome_direction": outcome, "expected_move_pips": expected,
                "actual_move_pips": actual, "snapshot_sha256": "a"*64,
                "anchor_version_id": f"a-{i}", "target_version_id": f"t-{i}",
                "forecast_cutoff_utc": "2026-01-01T00:00:00Z",
                "target_close_time_utc": "2026-01-01T00:15:00Z",
                "forecast_json": {"historical_dispersion_pips": 1.0 + i},
            })
    return {
        "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY",
        "status": "COMPLETE", "engine_version": "pit-forecast-replay-v1",
        "replay_id": "r-1", "source_history_sha256": "b"*64,
        "broker_server": "Headway-Real", "symbol": "EURUSD", "timeframe": "M5",
        "records": records,
        "integrity_policy": {
            "forecast_inputs_filtered_by_observed_and_as_of_at_each_cutoff": True,
            "only_closed_candles_used": True,
            "target_outcome_uses_first_closed_version_observed_after_target_close": True,
            "later_revisions_never_rewrite_forecast_or_target_version": True,
            "future_outcomes_excluded_from_forecast_snapshot": True,
            "system_knowledge_replay_only": True,
        },
    }

class ForecastErrorAnalysisEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ForecastErrorAnalysisEngine()

    def test_reports_metrics_separately_for_all_horizons(self):
        result = self.engine.analyze(fixture(), minimum_samples=4)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(set(result["by_horizon"]), {"15M", "1H", "4H"})
        self.assertEqual(result["by_horizon"]["15M"]["sample_count"], 6)
        self.assertEqual(result["by_horizon"]["4H"]["sample_count"], 4)

    def test_error_sign_convention_and_bias(self):
        replay = fixture()
        replay["records"][0]["expected_move_pips"] = 1.0
        replay["records"][0]["actual_move_pips"] = 3.0
        result = self.engine.analyze(replay)
        self.assertEqual(result["by_horizon"]["15M"]["mean_signed_error_pips_bias_actual_minus_forecast"] > 0, True)

    def test_neutral_forecasts_are_reported_separately(self):
        result = self.engine.analyze(fixture())
        metrics = result["by_horizon"]["15M"]
        self.assertGreater(metrics["by_forecast_direction"]["NEUTRAL"]["sample_count"], 0)
        self.assertLessEqual(metrics["non_neutral_direction_sample_count"], metrics["sample_count"])

    def test_dispersion_terciles_are_not_market_regimes(self):
        result = self.engine.analyze(fixture())
        self.assertEqual(result["by_horizon"]["15M"]["by_forecast_dispersion_tercile"]["status"],
                         "DESCRIPTIVE_TERCILES_NOT_MARKET_REGIMES")
        self.assertEqual(result["regime_attribution"]["status"],
                         "UNAVAILABLE_NO_POINT_IN_TIME_REGIME_LABELS_IN_REPLAY_RECORDS")

    def test_incomplete_replay_is_blocked(self):
        replay = fixture()
        replay["status"] = "BLOCKED"
        result = self.engine.analyze(replay)
        self.assertEqual(result["status"], "BLOCKED")

    def test_missing_integrity_flag_fails_closed(self):
        replay = fixture()
        replay["integrity_policy"]["system_knowledge_replay_only"] = False
        with self.assertRaisesRegex(ValueError, "INTEGRITY_POLICY"):
            self.engine.analyze(replay)

    def test_missing_outcomes_are_not_imputed(self):
        replay = fixture()
        replay["records"][0]["actual_move_pips"] = None
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["OUTCOME_NOT_YET_AVAILABLE"], 1)
        self.assertEqual(result["accepted_completed_forecasts"], len(replay["records"]) - 1)

    def test_duplicate_forecast_ids_are_rejected(self):
        replay = fixture()
        replay["records"][1]["forecast_id"] = replay["records"][0]["forecast_id"]
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["DUPLICATE_FORECAST_ID"], 1)

    def test_invalid_horizon_is_rejected(self):
        replay = fixture()
        replay["records"][0]["horizon"] = "2H"
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["HORIZON_UNSUPPORTED"], 1)

    def test_sample_size_is_flagged(self):
        result = self.engine.analyze(fixture(), minimum_samples=100)
        self.assertEqual(result["by_horizon"]["15M"]["sample_sufficiency"], "BELOW_CONFIGURED_MINIMUM")

    def test_wrong_replay_type_is_rejected(self):
        replay = fixture()
        replay["report_type"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "REPORT_TYPE"):
            self.engine.analyze(replay)

    def test_rejects_non_finite_metrics_input(self):
        replay = fixture()
        replay["records"][0]["expected_move_pips"] = float("nan")
        result = self.engine.analyze(replay)
        self.assertEqual(result["rejected_counts"]["NONFINITE_FORECAST_OR_OUTCOME"], 1)

if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone
from eurusd_ai_monitor.engines.multi_horizon_forecasting_engine import MultiHorizonForecastingEngine
from eurusd_ai_monitor.engines.multi_horizon_forecasting_runtime import build_multi_horizon_forecast

AS_OF = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def snapshot_for(*, count=120, mode="up", read_mode="STRICT_SYSTEM_KNOWLEDGE"):
    rows, price = [], 1.1000
    start = AS_OF - timedelta(minutes=5 * count)
    for i in range(count):
        opened = start + timedelta(minutes=5 * i)
        close = price + (0.0001 if mode == "up" else -0.0001 if mode == "down" else 0.0)
        rows.append({
            "candle_open_time_utc": opened.isoformat().replace("+00:00", "Z"),
            "observed_at_utc": AS_OF.isoformat().replace("+00:00", "Z"),
            "as_of_utc": AS_OF.isoformat().replace("+00:00", "Z"), "is_closed": True,
            "version_id": f"M5-{i}", "source_id": "MT5_COPY_RATES_RANGE",
            "provenance": {"price_basis": {"price_basis": "BID"}, "bar_time_basis": "UTC"},
            "values": {"open": price, "high": max(price, close)+0.00005,
                       "low": min(price, close)-0.00005, "close": close},
        })
        price = close
    return {"read_mode": read_mode, "as_of_utc": AS_OF.isoformat().replace("+00:00", "Z"),
        "snapshot_sha256": "snapshot-test", "registry_sha256": "registry-test",
        "spot_market_archive": {"status": "AVAILABLE", "streams": [{
            "symbol": "EURUSD", "timeframe": "M5", "status": "PASS",
            "eligible_for_analytics": True, "source_id": "MT5_COPY_RATES_RANGE",
            "broker_server": "Headway-Real", "price_basis": "BID", "candles": rows,
        }]}}


def scenario_for(state="UP"):
    return {"report_type": "CENTRAL_MULTI_DOMAIN_SCENARIO_INTELLIGENCE",
        "status": "PARTIAL", "evaluated_at_utc": AS_OF.isoformat(),
        "directional_assessment": {"state": state, "numeric_probability": None},
        "scenario_hypotheses": [], "cross_domain_context": {"macro": {"status": "INCOMPLETE"}},
        "evidence_dependency_map": {"groups": {}}}


class MultiHorizonForecastingEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = MultiHorizonForecastingEngine()

    def test_three_horizons_are_reported_separately(self):
        r = self.engine.assess(snapshot_for(), scenario_for())
        self.assertEqual(r["status"], "AVAILABLE")
        self.assertEqual(set(r["forecasts"]), {"15M", "1H", "4H"})
        self.assertEqual(r["forecasts"]["15M"]["direction"], "UP")
        self.assertEqual(r["forecasts"]["4H"]["horizon_bars"], 48)
        self.assertIsNone(r["forecasts"]["1H"]["numeric_probability"])

    def test_scenario_does_not_override_price_baseline(self):
        r = self.engine.assess(snapshot_for(), scenario_for("DOWN"))
        self.assertEqual(r["forecasts"]["15M"]["direction"], "UP")
        self.assertEqual(r["forecasts"]["15M"]["scenario_alignment"], "DIVERGENT")
        self.assertFalse(r["scenario_context"]["directional_authority_used_to_modify_forecast"])

    def test_missing_spot_history_fails_closed(self):
        s = snapshot_for()
        s["spot_market_archive"]["streams"][0].update(status="PROVENANCE_UNAVAILABLE", eligible_for_analytics=False)
        r = self.engine.assess(s)
        self.assertEqual(r["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["forecasts"]["4H"]["direction"], "UNRESOLVED")

    def test_non_strict_replay_mode_is_rejected(self):
        r = self.engine.assess(snapshot_for(read_mode="RECONSTRUCTED_PUBLIC_AVAILABILITY"))
        self.assertEqual(r["reason_codes"], ["NON_STRICT_READ_MODE_BLOCKED"])

    def test_forming_bar_is_rejected(self):
        s = snapshot_for()
        s["spot_market_archive"]["streams"][0]["candles"][-1]["is_closed"] = False
        self.assertEqual(self.engine.assess(s)["reason_codes"], ["FUTURE_OR_FORMING_CANDLE"])

    def test_gaps_are_rejected(self):
        s = snapshot_for()
        rows = s["spot_market_archive"]["streams"][0]["candles"]
        t = datetime.fromisoformat(rows[-10]["candle_open_time_utc"].replace("Z", "+00:00"))
        rows[-9]["candle_open_time_utc"] = (t + timedelta(minutes=10)).isoformat()
        self.assertEqual(self.engine.assess(s)["reason_codes"], ["CANDLE_HISTORY_GAP"])

    def test_unknown_price_basis_is_rejected(self):
        s = snapshot_for()
        s["spot_market_archive"]["streams"][0]["candles"][-1]["provenance"]["price_basis"]["price_basis"] = "UNKNOWN"
        self.assertEqual(self.engine.assess(s)["reason_codes"], ["PRICE_OR_TIME_BASIS_UNVERIFIED"])

    def test_stale_last_closed_bar_is_rejected(self):
        s = snapshot_for()
        rows = s["spot_market_archive"]["streams"][0]["candles"]
        for row in rows:
            opened = datetime.fromisoformat(row["candle_open_time_utc"].replace("Z", "+00:00"))
            row["candle_open_time_utc"] = (opened - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
        self.assertEqual(self.engine.assess(s)["reason_codes"], ["SPOT_STREAM_STALE_FOR_FORECAST"])

    def test_duplicate_eligible_streams_are_rejected(self):
        s = snapshot_for()
        s["spot_market_archive"]["streams"].append(dict(s["spot_market_archive"]["streams"][0]))
        self.assertEqual(self.engine.assess(s)["reason_codes"], ["AMBIGUOUS_MULTIPLE_ELIGIBLE_M5_STREAMS"])

    def test_scenario_cutoff_must_match_snapshot(self):
        scenario = scenario_for()
        scenario["evaluated_at_utc"] = (AS_OF - timedelta(minutes=1)).isoformat()
        r = self.engine.assess(snapshot_for(), scenario)
        self.assertEqual(r["scenario_context_warning"], "CENTRAL_SCENARIO_CUTOFF_MISMATCH")
        self.assertEqual(r["forecasts"]["15M"]["direction"], "UP")

    def test_runtime_wrapper(self):
        self.assertEqual(build_multi_horizon_forecast(snapshot_for(), scenario_for())["status"], "AVAILABLE")

    def test_invalid_configuration_and_input(self):
        with self.assertRaises(ValueError):
            MultiHorizonForecastingEngine(minimum_bars=130, lookback_bars=120)
        with self.assertRaises(ValueError):
            MultiHorizonForecastingEngine(pip_size=0)
        with self.assertRaises(TypeError):
            self.engine.assess([])


if __name__ == "__main__":
    unittest.main()

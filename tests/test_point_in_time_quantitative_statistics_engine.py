import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.point_in_time_quantitative_statistics_engine import (
    PointInTimeQuantitativeStatisticsEngine,
)

AS_OF = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def snapshot_for(*, m1=90, m5=90, mode="trend", read_mode="STRICT_SYSTEM_KNOWLEDGE"):
    streams = []
    for timeframe, count, minutes in (("M1", m1, 1), ("M5", m5, 5)):
        if count <= 0:
            continue
        rows = []
        price = 1.1000
        start = AS_OF - timedelta(minutes=minutes * count)
        for index in range(count):
            opened = start + timedelta(minutes=minutes * index)
            if mode == "trend":
                close = price + 0.0001
            elif mode == "alternating":
                close = price + (0.0001 if index % 2 == 0 else -0.0001)
            else:
                close = price
            rows.append({
                "candle_open_time_utc": opened.isoformat().replace("+00:00", "Z"),
                "observed_at_utc": AS_OF.isoformat().replace("+00:00", "Z"),
                "as_of_utc": AS_OF.isoformat().replace("+00:00", "Z"),
                "version_id": f"{timeframe}-{index}",
                "source_id": "MT5_COPY_RATES_RANGE",
                "broker_server": "Headway-Real",
                "symbol": "EURUSD",
                "timeframe": timeframe,
                "provenance": {
                    "price_basis": {"price_basis": "BID"},
                    "bar_time_basis": "UTC",
                },
                "values": {
                    "open": price,
                    "high": max(price, close) + 0.00005,
                    "low": min(price, close) - 0.00005,
                    "close": close,
                },
            })
            price = close
        streams.append({
            "symbol": "EURUSD",
            "timeframe": timeframe,
            "status": "PASS",
            "eligible_for_analytics": True,
            "candles": rows,
        })
    return {
        "read_mode": read_mode,
        "as_of_utc": AS_OF.isoformat().replace("+00:00", "Z"),
        "snapshot_sha256": "snapshot-test",
        "registry_sha256": "registry-test",
        "spot_market_archive": {"status": "AVAILABLE", "streams": streams},
    }


class PointInTimeQuantitativeStatisticsEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = PointInTimeQuantitativeStatisticsEngine(
            lookback_bars=80, minimum_bars=60
        )

    def test_reports_m1_and_m5_descriptive_quantitative_statistics(self):
        report = self.engine.assess(snapshot_for())
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(report["timeframes"]["M1"]["sample_size"]["candles"], 80)
        self.assertEqual(report["timeframes"]["M5"]["sample_size"]["close_to_close_returns"], 79)
        self.assertEqual(report["timeframes"]["M1"]["returns_pips"]["mean"], 1.0)
        self.assertEqual(report["timeframes"]["M1"]["returns_pips"]["positive_pct"], 100.0)
        self.assertEqual(report["timeframes"]["M1"]["dependence"]["lag1_return_autocorrelation"], None)
        self.assertEqual(report["trade_authority"], "NONE")

    def test_empirical_tail_risk_and_drawdown_are_descriptive(self):
        report = self.engine.assess(snapshot_for(mode="alternating"))
        stats = report["timeframes"]["M5"]
        self.assertGreaterEqual(stats["realized_risk"]["historical_var_95_loss_pips"], 0)
        self.assertGreaterEqual(stats["realized_risk"]["historical_expected_shortfall_95_pips"], 0)
        self.assertGreaterEqual(stats["realized_risk"]["maximum_close_to_close_drawdown_pips"], 0)

    def test_one_missing_timeframe_returns_partial_not_fabricated_data(self):
        report = self.engine.assess(snapshot_for(m1=0, m5=90))
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["excluded_timeframes"]["M1"], "STREAM_NOT_REGISTERED")
        self.assertIn("M5", report["timeframes"])

    def test_no_eligible_spot_data_returns_insufficient_evidence(self):
        snapshot = snapshot_for()
        for stream in snapshot["spot_market_archive"]["streams"]:
            stream["status"] = "PROVENANCE_UNAVAILABLE"
            stream["eligible_for_analytics"] = False
            stream["candles"] = []
        report = self.engine.assess(snapshot)
        self.assertEqual(report["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report["timeframes"], {})
        self.assertIn("NO_QUALITY_ELIGIBLE_STREAM", report["reason_codes"])

    def test_public_availability_replay_is_not_implicitly_accepted(self):
        report = self.engine.assess(snapshot_for(read_mode="RECONSTRUCTED_PUBLIC_AVAILABILITY"))
        self.assertEqual(report["reason_codes"], ["NON_STRICT_READ_MODE_BLOCKED"])

    def test_future_observed_candle_is_rejected(self):
        snapshot = snapshot_for()
        snapshot["spot_market_archive"]["streams"][0]["candles"][-1]["observed_at_utc"] = (
            AS_OF + timedelta(minutes=1)
        ).isoformat()
        report = self.engine.assess(snapshot)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["excluded_timeframes"]["M1"], "FUTURE_OR_FORMING_CANDLE")

    def test_gap_in_history_is_rejected(self):
        snapshot = snapshot_for()
        candles = snapshot["spot_market_archive"]["streams"][0]["candles"]
        opened = datetime.fromisoformat(candles[-12]["candle_open_time_utc"].replace("Z", "+00:00"))
        candles[-11]["candle_open_time_utc"] = (opened + timedelta(minutes=2)).isoformat()
        report = self.engine.assess(snapshot)
        self.assertEqual(report["excluded_timeframes"]["M1"], "CANDLE_HISTORY_GAP")

    def test_unverified_price_basis_is_rejected(self):
        snapshot = snapshot_for()
        snapshot["spot_market_archive"]["streams"][0]["candles"][-1]["provenance"]["price_basis"]["price_basis"] = "UNKNOWN"
        report = self.engine.assess(snapshot)
        self.assertEqual(report["excluded_timeframes"]["M1"], "PRICE_OR_TIME_BASIS_UNVERIFIED")

    def test_invalid_thresholds_are_rejected(self):
        with self.assertRaises(ValueError):
            PointInTimeQuantitativeStatisticsEngine(minimum_bars=100, lookback_bars=50)
        with self.assertRaises(ValueError):
            PointInTimeQuantitativeStatisticsEngine(pip_size=0)

    def test_non_mapping_input_is_rejected(self):
        with self.assertRaises(TypeError):
            self.engine.assess([])


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.multidomain_market_regime_engine import (
    MultiDomainMarketRegimeEngine,
)

AS_OF = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def make_snapshot(*, eligible=True, mode="trend", count=80, positioning=3):
    candles = []
    price = 1.1000
    start = AS_OF - timedelta(minutes=5 * count)
    for index in range(count):
        opened = start + timedelta(minutes=5 * index)
        if mode == "trend":
            close = price + 0.0001
        elif mode == "range":
            close = price + (0.0001 if index % 2 == 0 else -0.0001)
        else:
            close = price + (0.0001 if index % 3 else -0.0001)
        width = 0.00005 if index < count - 14 else 0.0005
        candles.append({
            "candle_open_time_utc": opened.isoformat().replace("+00:00", "Z"),
            "candle_close_time_utc": (opened + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "observed_at_utc": AS_OF.isoformat().replace("+00:00", "Z"),
            "as_of_utc": AS_OF.isoformat().replace("+00:00", "Z"),
            "version_id": index + 1,
            "values": {
                "open": price, "high": max(price, close) + width,
                "low": min(price, close) - width, "close": close,
            },
        })
        price = close
    stream = {
        "symbol": "EURUSD", "timeframe": "M5",
        "status": "PASS" if eligible else "BLOCKED",
        "eligible_for_analytics": eligible,
        "candles": candles,
    }
    return {
        "read_mode": "STRICT_SYSTEM_KNOWLEDGE",
        "as_of_utc": AS_OF.isoformat().replace("+00:00", "Z"),
        "snapshot_sha256": "snapshot-test",
        "registry_sha256": "registry-test",
        "spot_market_archive": {"status": "AVAILABLE" if eligible else "BLOCKED", "streams": [stream]},
        "analytics_domains": {
            "spot_fx": {"status": "ELIGIBLE" if eligible else "BLOCKED", "eligible_products": 0},
            "positioning_sentiment": {"status": "PARTIAL", "eligible_products": positioning, "observation_count": 153},
        },
    }


class MultiDomainMarketRegimeEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = MultiDomainMarketRegimeEngine()

    def test_positioning_only_never_invents_market_regime(self):
        snapshot = make_snapshot(eligible=False, positioning=3)
        snapshot["spot_market_archive"] = {"status": "PROVENANCE_UNAVAILABLE", "streams": []}
        report = self.engine.assess(snapshot)
        self.assertEqual(report["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report["market_regime"], "UNKNOWN")
        self.assertIn("positioning_sentiment", report["available_context_domains"])
        self.assertEqual(report["trade_authority"], "NONE")

    def test_quality_eligible_m5_supports_descriptive_trend_regime(self):
        report = self.engine.assess(make_snapshot(mode="trend"))
        self.assertEqual(report["regime_status"], "AVAILABLE")
        self.assertEqual(report["market_regime"], "TRENDING")
        self.assertEqual(report["trend_direction"], "UP")
        self.assertEqual(report["provenance"]["m5_candle_count"], 65)
        self.assertEqual(report["provenance"]["m5_version_ids"][0], 16)

    def test_low_efficiency_m5_is_range(self):
        report = self.engine.assess(make_snapshot(mode="range"))
        self.assertEqual(report["market_regime"], "RANGING")

    def test_missing_macro_and_intermarket_keep_overall_partial(self):
        report = self.engine.assess(make_snapshot())
        self.assertEqual(report["status"], "PARTIAL")
        self.assertIn("macro_fundamentals", report["missing_or_blocked_domains"])
        self.assertIn("intermarket", report["missing_or_blocked_domains"])

    def test_short_history_is_insufficient(self):
        report = self.engine.assess(make_snapshot(count=40))
        self.assertEqual(report["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("INSUFFICIENT_QUALITY_ELIGIBLE_M5_HISTORY", report["reason_codes"])

    def test_future_or_invalid_candle_blocks_entire_stream(self):
        snapshot = make_snapshot()
        snapshot["spot_market_archive"]["streams"][0]["candles"][10]["as_of_utc"] = (
            AS_OF + timedelta(minutes=1)
        ).isoformat()
        report = self.engine.assess(snapshot)
        self.assertEqual(report["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report["market_regime"], "UNKNOWN")

    def test_naive_as_of_fails_closed(self):
        snapshot = make_snapshot()
        snapshot["as_of_utc"] = "2026-11-20T12:00:00"
        report = self.engine.assess(snapshot)
        self.assertEqual(report["reason_codes"], ["INVALID_OR_MISSING_AS_OF_TIMESTAMP"])

    def test_non_strict_replay_mode_is_rejected(self):
        snapshot = make_snapshot()
        snapshot["read_mode"] = "RECONSTRUCTED_PUBLIC_AVAILABILITY"
        report = self.engine.assess(snapshot)
        self.assertEqual(report["reason_codes"], ["NON_STRICT_READ_MODE_BLOCKED"])

    def test_ambiguous_multiple_broker_streams_are_rejected(self):
        snapshot = make_snapshot()
        second = dict(snapshot["spot_market_archive"]["streams"][0])
        second["broker_server"] = "OtherBroker"
        snapshot["spot_market_archive"]["streams"].append(second)
        report = self.engine.assess(snapshot)
        self.assertEqual(report["reason_codes"], ["AMBIGUOUS_MULTIPLE_ELIGIBLE_EURUSD_M5_STREAMS"])

    def test_gapped_recent_m5_history_is_rejected(self):
        snapshot = make_snapshot()
        candles = snapshot["spot_market_archive"]["streams"][0]["candles"]
        opened = datetime.fromisoformat(candles[-20]["candle_open_time_utc"].replace("Z", "+00:00"))
        for row in candles[-19:]:
            row_open = datetime.fromisoformat(row["candle_open_time_utc"].replace("Z", "+00:00"))
            row_close = datetime.fromisoformat(row["candle_close_time_utc"].replace("Z", "+00:00"))
            shift = timedelta(minutes=5)
            row["candle_open_time_utc"] = (row_open + shift).isoformat().replace("+00:00", "Z")
            row["candle_close_time_utc"] = (row_close + shift).isoformat().replace("+00:00", "Z")
        snapshot["as_of_utc"] = (AS_OF + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        report = self.engine.assess(snapshot)
        self.assertEqual(report["reason_codes"], ["M5_HISTORY_CONTAINS_GAPS"])


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.session_time_intelligence_engine import (
    SessionTimeIntelligenceEngine,
)


def snapshot(at="2026-11-19T13:00:00Z", read_mode="STRICT_SYSTEM_KNOWLEDGE",
             streams=None):
    return {
        "as_of_utc": at,
        "snapshot_sha256": "snapshot-hash",
        "registry_sha256": "registry-hash",
        "read_mode": read_mode,
        "spot_market_archive": {"streams": streams or []},
    }


def stream(tf="M1", start="2026-11-19T11:55:00Z", count=65):
    opened = datetime.fromisoformat(start.replace("Z", "+00:00"))
    step = timedelta(minutes=1 if tf == "M1" else 5)
    rows = []
    for i in range(count):
        at = opened + i * step
        close = at + step
        rows.append({
            "candle_open_time_utc": at.isoformat(),
            "candle_close_time_utc": close.isoformat(),
            "observed_at_utc": close.isoformat(),
            "as_of_utc": close.isoformat(),
            "version_id": f"{tf}-{i}",
            "values": {"open": 1.1, "high": 1.1002, "low": 1.0998, "close": 1.1001},
        })
    return {
        "symbol": "EURUSD", "timeframe": tf, "source_id": "MT5_COPY_RATES",
        "broker_server": "Broker-Demo", "status": "PASS",
        "eligible_for_analytics": True, "candles": rows,
    }


class SessionTimeIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = SessionTimeIntelligenceEngine()

    def test_london_new_york_overlap_in_standard_time(self):
        r = self.engine.assess(snapshot())
        self.assertTrue(r["london_new_york_overlap_active"])
        self.assertEqual(r["overlap_label"], "LONDON_NEW_YORK_OVERLAP")
        self.assertEqual(r["session_clock_context"]["NEW_YORK"]["utc_offset"], "-0500")

    def test_dst_offsets_are_zone_specific(self):
        r = self.engine.assess(snapshot("2026-07-15T12:00:00Z"))
        self.assertEqual(r["session_clock_context"]["LONDON"]["utc_offset"], "+0100")
        self.assertEqual(r["session_clock_context"]["NEW_YORK"]["utc_offset"], "-0400")
        self.assertTrue(r["session_clock_context"]["LONDON"]["dst_active"])
        self.assertTrue(r["session_clock_context"]["NEW_YORK"]["dst_active"])

    def test_tokyo_and_sydney_are_annotated(self):
        r = self.engine.assess(snapshot("2026-11-19T00:30:00Z"))
        self.assertIn("TOKYO", r["active_reference_sessions"])
        self.assertIn("SYDNEY", r["active_reference_sessions"])
        self.assertIn("SYDNEY_TOKYO", r["active_session_overlaps"])

    def test_saturday_is_only_a_calendar_flag_not_broker_market_claim(self):
        r = self.engine.assess(snapshot("2026-11-21T12:00:00Z"))
        self.assertTrue(r["saturday_calendar_flag"])
        self.assertIn("UNKNOWN", r["policy"]["broker_weekly_open_close"])

    def test_no_spot_history_is_insufficient_and_does_not_invent_session_edge(self):
        r = self.engine.assess(snapshot())
        self.assertEqual(r["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("NO_QUALITY_ELIGIBLE_SPOT_HISTORY", r["reason_codes"])
        self.assertEqual(r["historical_session_coverage"], {})

    def test_quality_eligible_m1_coverage_is_descriptive(self):
        s = snapshot(streams=[stream()])
        r = self.engine.assess(s)
        self.assertEqual(r["status"], "PARTIAL")
        self.assertEqual(r["historical_session_coverage"]["M1"]["sample_count"], 65)
        self.assertEqual(r["historical_session_coverage"]["M1"]["interpretation"],
                         "DESCRIPTIVE_COVERAGE_ONLY")

    def test_future_or_invalid_candle_blocks_timeframe(self):
        bad = stream()
        bad["candles"][2]["observed_at_utc"] = "2026-11-20T00:00:00Z"
        r = self.engine.assess(snapshot(streams=[bad]))
        self.assertEqual(r["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["excluded_timeframes"]["M1"],
                         "INVALID_OR_NON_POINT_IN_TIME_CANDLES")

    def test_non_strict_replay_is_blocked(self):
        r = self.engine.assess(snapshot(read_mode="RECONSTRUCTED_PUBLIC_AVAILABILITY"))
        self.assertEqual(r["status"], "BLOCKED")

    def test_calendar_requires_publication_and_retrieval_before_cutoff(self):
        event = {
            "event_id": "cpi-1", "source_id": "BLS", "title": "CPI",
            "currency_codes": ["USD"], "impact": "HIGH", "status": "SCHEDULED",
            "scheduled_at_utc": "2026-11-19T14:30:00Z",
            "published_at_utc": "2026-11-18T12:00:00Z",
            "retrieved_at_utc": "2026-11-18T12:01:00Z",
        }
        future_retrieval = dict(event, retrieved_at_utc="2026-11-20T00:00:00Z")
        r = self.engine.assess(snapshot(), calendar_events=[event, future_retrieval])
        self.assertEqual(len(r["calendar_event_context"]["timed_events"]), 1)
        self.assertEqual(r["calendar_event_context"]["excluded_unverified_or_cancelled_events"], 1)

    def test_date_only_event_is_not_given_a_fake_intraday_time(self):
        event = {
            "event_id": "fomc-date", "source_id": "FED", "title": "FOMC",
            "published_at_utc": "2026-11-01T12:00:00Z",
            "retrieved_at_utc": "2026-11-01T12:01:00Z",
            "scheduled_at_utc": None,
        }
        r = self.engine.assess(snapshot(), calendar_events=[event])
        self.assertEqual(r["calendar_event_context"]["date_only_events"], 1)
        self.assertEqual(r["calendar_event_context"]["timed_events"], [])

    def test_cancelled_event_excluded(self):
        event = {
            "event_id": "cancelled", "published_at_utc": "2026-11-01T12:00:00Z",
            "retrieved_at_utc": "2026-11-01T12:01:00Z",
            "scheduled_at_utc": "2026-11-19T14:30:00Z", "status": "CANCELLED",
        }
        r = self.engine.assess(snapshot(), calendar_events=[event])
        self.assertEqual(r["calendar_event_context"]["timed_events"], [])

    def test_invalid_calendar_container_is_blocked(self):
        r = self.engine.assess(snapshot(), calendar_events={"not": "a sequence"})
        self.assertEqual(r["calendar_event_context"]["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()

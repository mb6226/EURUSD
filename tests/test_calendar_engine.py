import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from eurusd_ai_monitor.engines.calendar_engine import (
    CalendarSourceError,
    MacroCalendarEngine,
    parse_bea_release_dates,
    parse_ecb_meeting_calendar_html,
    parse_fomc_calendar_html,
    parse_ics_events,
)
from eurusd_ai_monitor.storage.macro_calendar_store import MacroCalendarStore


ICS_FIXTURE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:cpi-2026-11
DTSTART;TZID=America/New_York:20261120T083000
SUMMARY:Consumer Price Index for October 2026
DESCRIPTION:Monthly CPI release\\nOfficial schedule
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
UID:holiday-2026-11
DTSTART;VALUE=DATE:20261126
SUMMARY:Thanksgiving Day
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""

BEA_FIXTURE = json.dumps({
    "Gross Domestic Product": {
        "release_dates": [
            "2026-11-25T13:30:00+00:00",
            "2026-11-25T13:30:00+00:00",
        ]
    },
    "Personal Income and Outlays": {
        "release_dates": ["2026-11-25T13:30:00+00:00"]
    },
    "file_last_updated": "2026-11-18T10:00:00"
})


class CalendarParserTests(unittest.TestCase):
    def test_ics_parser_handles_timezone_all_day_status_and_folded_lines(self):
        records = parse_ics_events(ICS_FIXTURE, "UTC")
        self.assertEqual(len(records), 2)
        cpi = records[0]
        self.assertEqual(cpi["scheduled_at_utc"], datetime(2026, 11, 20, 13, 30, tzinfo=timezone.utc))
        self.assertEqual(cpi["scheduled_date"].isoformat(), "2026-11-20")
        self.assertIn("Official schedule", cpi["description"])
        self.assertIsNone(records[1]["scheduled_at_utc"])
        self.assertEqual(records[1]["status"], "CANCELLED")

    def test_ics_parser_rejects_empty_and_unterminated_feeds(self):
        with self.assertRaises(CalendarSourceError):
            parse_ics_events("", "UTC")
        with self.assertRaisesRegex(CalendarSourceError, "unterminated"):
            parse_ics_events("BEGIN:VCALENDAR\\nBEGIN:VEVENT\\nSUMMARY:X\\n", "UTC")

    def test_ics_parser_rejects_unknown_timezone(self):
        ics = "BEGIN:VCALENDAR\\nBEGIN:VEVENT\\nUID:x\\nDTSTART;TZID=Not/AZone:20261120T083000\\nSUMMARY:X\\nEND:VEVENT\\nEND:VCALENDAR"
        with self.assertRaisesRegex(CalendarSourceError, "unknown iCalendar timezone"):
            parse_ics_events(ics, "UTC")

    def test_bea_json_parser_deduplicates_identical_title_and_timestamp(self):
        records = parse_bea_release_dates(BEA_FIXTURE)
        self.assertEqual(len(records), 2)
        self.assertEqual(
            records[0]["scheduled_at_utc"],
            datetime(2026, 11, 25, 13, 30, tzinfo=timezone.utc),
        )

    def test_bea_json_rejects_naive_timestamps(self):
        with self.assertRaisesRegex(CalendarSourceError, "include an offset"):
            parse_bea_release_dates(json.dumps({
                "GDP": {"release_dates": ["2026-11-25T13:30:00"]}
            }))

    def test_fomc_parser_uses_second_meeting_day_and_marks_future_dates_tentative(self):
        html = """
        <html><body>
          <h2>2026 FOMC Meetings</h2>
          January 27-28 Statement Press Conference
          December 8-9* Statement Press Conference
          <h2>2027 FOMC Meetings</h2>
          January 26-27 Statement Press Conference
          October 26-27 Monetary Policy Strategy Meeting
        </body></html>
        """
        records = parse_fomc_calendar_html(
            html, as_of_date=datetime(2026, 11, 19, tzinfo=timezone.utc).date()
        )
        by_date = {item["scheduled_date"].isoformat(): item for item in records}
        self.assertEqual(by_date["2026-01-28"]["status"], "CONFIRMED")
        self.assertEqual(by_date["2026-12-09"]["status"], "TENTATIVE")
        self.assertEqual(by_date["2027-01-27"]["status"], "TENTATIVE")
        self.assertIn("strategy meeting", by_date["2027-10-27"]["title"])
        self.assertIsNone(by_date["2027-10-27"]["scheduled_at_utc"])

    def test_ecb_html_parser_extracts_meeting_dates_without_inventing_times(self):
        html = """
        <html><body>
          <div>25/11/2026</div><p>Governing Council of the ECB: non-monetary policy meeting in Frankfurt</p>
          <div>16/12/2026</div><p>Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 1)</p>
          <div>17/12/2026</div><p>Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 2), followed by press conference</p>
        </body></html>
        """
        records = parse_ecb_meeting_calendar_html(html)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(item["scheduled_at_utc"] is None for item in records))
        self.assertIn("monetary policy meeting", records[1]["title"])


class MacroCalendarEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MacroCalendarStore(Path(self.temp.name) / "calendar.sqlite")
        self.now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
        self.source = {
            "source_id": "BLS_US_RELEASES",
            "name": "BLS Official Calendar",
            "url": "https://example.test/bls.ics",
            "format": "ICS",
            "currency_codes": ["USD"],
            "category": "ECONOMIC_RELEASE",
            "timezone": "America/New_York",
            "enabled": True,
            "refresh_interval_seconds": 3600,
            "stale_after_seconds": 86400,
            "impact_rules": {"HIGH": ["consumer price index"], "MEDIUM": [], "LOW": []},
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_refresh_persists_events_and_context_provenance(self):
        engine = MacroCalendarEngine(
            self.store, [self.source], fetcher=lambda url: ICS_FIXTURE,
            clock=lambda: self.now,
        )
        result = engine.refresh_due()
        self.assertEqual(result["BLS_US_RELEASES"]["status"], "ACTIVE")
        context = engine.build_context(self.now, horizon_hours=72)
        self.assertEqual(context["event_count"], 1)
        self.assertEqual(context["high_impact_count"], 1)
        event = context["upcoming_events"][0]
        self.assertEqual(event["impact"], "HIGH")
        self.assertEqual(event["source_id"], "BLS_US_RELEASES")
        self.assertEqual(event["actual"], None)
        self.assertEqual(context["trade_authority"], "NONE")
        self.assertEqual(context["decision_authority"], "CONTEXT_ONLY")

    def test_refresh_interval_prevents_repeated_network_calls(self):
        calls = []
        engine = MacroCalendarEngine(
            self.store, [self.source],
            fetcher=lambda url: calls.append(url) or ICS_FIXTURE,
            clock=lambda: self.now,
        )
        engine.refresh_due()
        engine.refresh_due()
        self.assertEqual(len(calls), 1)

    def test_fetch_failure_keeps_previous_events_and_marks_source_failed(self):
        engine = MacroCalendarEngine(
            self.store, [self.source], fetcher=lambda url: ICS_FIXTURE,
            clock=lambda: self.now,
        )
        engine.refresh_due()
        failing = MacroCalendarEngine(
            self.store, [self.source],
            fetcher=lambda url: (_ for _ in ()).throw(OSError("offline")),
            clock=lambda: self.now.replace(hour=14),
        )
        result = failing.refresh_due()
        self.assertEqual(result["BLS_US_RELEASES"]["status"], "FAILED")
        self.assertEqual(self.store.get_source_states()["BLS_US_RELEASES"]["status"], "FAILED")
        context = failing.build_context(self.now.replace(hour=14), horizon_hours=72)
        self.assertEqual(context["event_count"], 1)
        self.assertIn("BLS_US_RELEASES", context["stale_sources"])

    def test_unknown_impact_is_not_promoted_to_low(self):
        source = dict(self.source)
        source["impact_rules"] = {"HIGH": [], "MEDIUM": [], "LOW": []}
        engine = MacroCalendarEngine(
            self.store, [source], fetcher=lambda url: ICS_FIXTURE,
            clock=lambda: self.now,
        )
        engine.refresh_due()
        context = engine.build_context(self.now, horizon_hours=72)
        self.assertEqual(context["upcoming_events"][0]["impact"], "UNKNOWN")

    def test_rejects_invalid_source_timezone(self):
        source = dict(self.source)
        source["timezone"] = "Not/AZone"
        with self.assertRaises(CalendarSourceError):
            MacroCalendarEngine(self.store, [source])


if __name__ == "__main__":
    unittest.main()

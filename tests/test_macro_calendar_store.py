import sqlite3
from contextlib import closing
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from eurusd_ai_monitor.models.macro_event import MacroEvent, MacroEventStatus, MacroImpact
from eurusd_ai_monitor.storage.macro_calendar_store import MacroCalendarStore


NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def event(**overrides):
    values = {
        "event_id": "BLS:stable-id",
        "source_id": "BLS_US_RELEASES",
        "source_name": "BLS Official Calendar",
        "source_url": "https://www.bls.gov/schedule/news_release/bls.ics",
        "source_event_id": "stable-id",
        "title": "Consumer Price Index",
        "description": "",
        "currency_codes": ("USD",),
        "category": "ECONOMIC_RELEASE",
        "impact": MacroImpact.HIGH,
        "impact_reason": "configured title rule",
        "scheduled_date": date(2026, 11, 20),
        "scheduled_at_utc": datetime(2026, 11, 20, 13, 30, tzinfo=timezone.utc),
        "source_timezone": "America/New_York",
        "status": MacroEventStatus.SCHEDULED,
        "retrieved_at_utc": NOW,
    }
    values.update(overrides)
    return MacroEvent(**values)


class MacroCalendarStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MacroCalendarStore(Path(self.temp.name) / "calendar.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def test_inserts_and_queries_by_currency_and_utc_instant(self):
        self.store.upsert_events([event()], NOW)
        rows = self.store.list_events(
            datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            datetime(2026, 11, 20, 14, tzinfo=timezone.utc),
            currencies=("EUR", "USD"),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].title, "Consumer Price Index")
        self.assertEqual(
            self.store.list_events(
                datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
                datetime(2026, 11, 20, 14, tzinfo=timezone.utc),
                currencies=("EUR",),
            ),
            (),
        )

    def test_unchanged_refresh_does_not_create_revision(self):
        self.store.upsert_events([event()], NOW)
        self.store.upsert_events(
            [event(retrieved_at_utc=datetime(2026, 11, 19, 13, tzinfo=timezone.utc))],
            datetime(2026, 11, 19, 13, tzinfo=timezone.utc),
        )
        self.assertEqual(self.store.revision_count(), 0)

    def test_changed_event_appends_revision_and_updates_current_record(self):
        self.store.upsert_events([event()], NOW)
        revised = event(title="Consumer Price Index — revised schedule")
        count = self.store.upsert_events([revised], NOW)
        self.assertEqual(count, 1)
        self.assertEqual(self.store.revision_count(), 1)
        rows = self.store.list_events(
            datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            datetime(2026, 11, 20, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(rows[0].title, "Consumer Price Index — revised schedule")

    def test_revision_table_is_append_only(self):
        self.store.upsert_events([event()], NOW)
        self.store.upsert_events([event(title="Changed title")], NOW)
        with closing(self.store._connect()) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM macro_event_revisions")

    def test_conflicting_duplicate_event_ids_are_rejected_before_write(self):
        first = event()
        second = event(title="Different title")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            self.store.upsert_events([first, second], NOW)
        self.assertEqual(
            self.store.list_events(
                datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
                datetime(2026, 11, 20, 14, tzinfo=timezone.utc),
            ),
            (),
        )

    def test_date_only_event_uses_local_calendar_date(self):
        date_only = event(scheduled_at_utc=None)
        self.store.upsert_events([date_only], NOW)
        rows = self.store.list_events(
            datetime(2026, 11, 20, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 21, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].scheduled_at_utc)

    def test_failed_fetch_keeps_last_success_and_event_count(self):
        self.store.record_source_state("BLS_US_RELEASES", "ACTIVE", NOW, NOW, 12)
        self.store.record_source_state(
            "BLS_US_RELEASES", "FAILED",
            datetime(2026, 11, 19, 13, tzinfo=timezone.utc),
            None, 0, "NETWORK_ERROR", "offline",
        )
        state = self.store.get_source_states()["BLS_US_RELEASES"]
        self.assertEqual(state["status"], "FAILED")
        self.assertEqual(state["event_count"], 12)
        self.assertEqual(state["last_success_at_utc"], NOW)


if __name__ == "__main__":
    unittest.main()

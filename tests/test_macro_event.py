import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from eurusd_ai_monitor.models.macro_event import (
    MacroEvent, MacroEventStatus, MacroImpact,
)


def make_event(**overrides):
    values = {
        "event_id": "BLS:abc123",
        "source_id": "BLS_US_RELEASES",
        "source_name": "BLS Official Calendar",
        "source_url": "https://www.bls.gov/schedule/news_release/bls.ics",
        "source_event_id": "uid-1",
        "title": "Consumer Price Index",
        "description": "Monthly CPI release",
        "currency_codes": ("USD",),
        "category": "ECONOMIC_RELEASE",
        "impact": MacroImpact.HIGH,
        "impact_reason": "title matched configured HIGH rule: consumer price index",
        "scheduled_date": date(2026, 11, 20),
        "scheduled_at_utc": datetime(2026, 11, 20, 13, 30, tzinfo=timezone.utc),
        "source_timezone": "America/New_York",
        "status": MacroEventStatus.SCHEDULED,
        "actual": None,
        "forecast": None,
        "previous": None,
        "retrieved_at_utc": datetime(2026, 11, 19, 12, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return MacroEvent(**values)


class MacroEventTests(unittest.TestCase):
    def test_round_trip_preserves_schedule_provenance_and_missing_results(self):
        event = make_event()
        restored = MacroEvent.from_dict(event.to_dict())
        self.assertEqual(restored, event)
        self.assertIsNone(restored.actual)
        self.assertIsNone(restored.forecast)
        self.assertIsNone(restored.previous)

    def test_semantic_payload_excludes_retrieval_timestamp(self):
        first = make_event()
        second = make_event(
            retrieved_at_utc=datetime(2026, 11, 19, 13, tzinfo=timezone.utc)
        )
        self.assertEqual(
            first.to_dict(include_retrieved_at=False),
            second.to_dict(include_retrieved_at=False),
        )

    def test_rejects_naive_schedule_timestamp(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            make_event(scheduled_at_utc=datetime(2026, 11, 20, 13, 30))

    def test_rejects_non_decimal_result(self):
        with self.assertRaisesRegex(ValueError, "finite Decimal"):
            make_event(actual=1.5)

    def test_rejects_unknown_currency_code(self):
        with self.assertRaisesRegex(ValueError, "unsupported ISO currency"):
            make_event(currency_codes=("XYZ",))

    def test_date_only_events_are_supported_without_inventing_time(self):
        event = make_event(scheduled_at_utc=None)
        self.assertIsNone(event.scheduled_at_utc)
        self.assertEqual(event.scheduled_date, date(2026, 11, 20))


if __name__ == "__main__":
    unittest.main()

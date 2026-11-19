import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.engines.session_eligibility_engine import (
    SessionEligibilityRiskGate, SessionRiskStore,
)

class SessionEligibilityRiskGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SessionRiskStore(Path(self.temp.name) / "risk.sqlite3")
        self.gate = SessionEligibilityRiskGate(
            self.store, stop_loss_pips=Decimal("5"),
            take_profit_pips=Decimal("50"), max_daily_risk_pips=Decimal("10"))
        self.setup = {"stage": "PATTERN_CONFIRMED",
                      "pullback": {"retest_candle_id": "m1-retest-001"}}

    def tearDown(self):
        self.temp.cleanup()

    def assess(self, at, setup=None, lifecycle="lifecycle-1", gate=None):
        return (gate or self.gate).assess(
            evaluated_at_utc=at, broker_server="Broker-Demo", symbol="EURUSD",
            setup_assessment=self.setup if setup is None else setup, lifecycle_id=lifecycle)

    def test_london_window_local_time(self):
        r = self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))
        self.assertEqual((r["status"], r["session"]), ("RESEARCH_ELIGIBLE", "LONDON"))

    def test_new_york_window_standard_time(self):
        r = self.assess(datetime(2026, 11, 19, 13, 0, tzinfo=timezone.utc))
        self.assertEqual((r["status"], r["session"]), ("RESEARCH_ELIGIBLE", "NEW_YORK"))

    def test_new_york_window_daylight_time(self):
        r = self.assess(datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc))
        self.assertEqual((r["status"], r["session"]), ("RESEARCH_ELIGIBLE", "NEW_YORK"))

    def test_session_end_is_exclusive(self):
        r = self.assess(datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(r["status"], "OUTSIDE_SESSION")

    def test_outside_window_does_not_consume_slot(self):
        self.assertEqual(self.assess(datetime(2026, 11, 19, 7, 59, tzinfo=timezone.utc))["status"],
                         "OUTSIDE_SESSION")
        self.assertEqual(self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))["status"],
                         "RESEARCH_ELIGIBLE")

    def test_unconfirmed_setup_does_not_consume_slot(self):
        r = self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc),
                        {"stage": "WAIT_BREAKOUT"})
        self.assertEqual(r["status"], "WAIT_SETUP")
        self.assertEqual(self.assess(datetime(2026, 11, 19, 8, 1, tzinfo=timezone.utc))["status"],
                         "RESEARCH_ELIGIBLE")

    def test_same_setup_is_idempotent(self):
        a = self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))
        b = self.assess(datetime(2026, 11, 19, 8, 1, tzinfo=timezone.utc))
        self.assertEqual(a["status"], "RESEARCH_ELIGIBLE")
        self.assertEqual(b["status"], "RESEARCH_ELIGIBLE")
        self.assertEqual(a["setup_key"], b["setup_key"])
        self.assertEqual(b["daily_risk_used_pips"], "5")

    def test_distinct_second_setup_same_session_blocked(self):
        self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))
        r = self.assess(datetime(2026, 11, 19, 8, 2, tzinfo=timezone.utc), lifecycle="lifecycle-2")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("ONE_SETUP_PER_SESSION_LIMIT_REACHED", r["reason_codes"])

    def test_same_setup_cannot_be_reused_in_another_session(self):
        first = self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))
        second = self.assess(datetime(2026, 11, 19, 13, 0, tzinfo=timezone.utc))
        self.assertEqual(first["status"], "RESEARCH_ELIGIBLE")
        self.assertEqual(second["status"], "BLOCKED")
        self.assertIn("SETUP_ALREADY_RESERVED_FOR_ANOTHER_SESSION_DATE",
                      second["reason_codes"])

    def test_daily_budget_shared_between_london_and_new_york(self):
        a = self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))
        b = self.assess(datetime(2026, 11, 19, 13, 0, tzinfo=timezone.utc), lifecycle="lifecycle-2")
        self.assertEqual(a["status"], "RESEARCH_ELIGIBLE")
        self.assertEqual(b["status"], "RESEARCH_ELIGIBLE")
        self.assertEqual(b["daily_risk_used_pips"], "10")
        c = self.assess(datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc), lifecycle="lifecycle-3")
        self.assertEqual(c["status"], "RESEARCH_ELIGIBLE")

    def test_daily_budget_blocks_extra_reservation_same_risk_day(self):
        self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))
        self.assess(datetime(2026, 11, 19, 13, 0, tzinfo=timezone.utc), lifecycle="lifecycle-2")
        # Use a different session date while keeping the London risk date equal
        # is not possible for the configured windows; verify store-level guard
        # with a directly supplied third reservation on the same risk date.
        status, _, total = self.store.reserve(
            broker_server="Broker-Demo", symbol="EURUSD", session_name="LONDON",
            session_date="2026-11-20", risk_date="2026-11-19", setup_key="third",
            risk_pips=Decimal("5"), stop_loss_pips=Decimal("5"),
            take_profit_pips=Decimal("50"), max_daily_risk_pips=Decimal("10"),
            created_at_utc=datetime(2026, 11, 19, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(status, "DAILY_RISK_LIMIT")
        self.assertEqual(total, Decimal("10"))

    def test_restart_preserves_session_slot(self):
        self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))
        restarted = SessionEligibilityRiskGate(
            SessionRiskStore(Path(self.temp.name) / "risk.sqlite3"),
            stop_loss_pips=Decimal("5"), take_profit_pips=Decimal("50"),
            max_daily_risk_pips=Decimal("10"))
        r = self.assess(datetime(2026, 11, 19, 8, 5, tzinfo=timezone.utc),
                        gate=restarted, lifecycle="lifecycle-2")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(r["daily_risk_used_pips"], "5")

    def test_never_grants_order_authority(self):
        r = self.assess(datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(r["trade_authority"], "NONE")
        self.assertEqual(r["order_execution"], "DISABLED")
        self.assertFalse(r["trailing_stop_enabled"])

    def test_naive_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.assess(datetime(2026, 11, 19, 8, 0))

if __name__ == "__main__":
    unittest.main()

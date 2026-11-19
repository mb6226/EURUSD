import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.engines.setup_outcome_tracker import (
    ObservationStore, SetupOutcomeTracker,
)
from eurusd_ai_monitor.storage.market_data_store import Candle

BASE = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)


def candle(minute, high, low, close, *, broker="Broker", symbol="EURUSD"):
    opened = BASE + timedelta(minutes=minute)
    price = Decimal("1.10000")
    return Candle(broker, symbol, "M1", opened, price, Decimal(high),
                  Decimal(low), Decimal(close), 10, 1, 0)


def setup():
    retest = candle(1, "1.10020", "1.09990", "1.10000")
    retest_id = f"Broker|EURUSD|M1|{retest.candle_open_time_utc.isoformat().replace('+00:00', 'Z')}"
    return retest, {
        "stage": "PATTERN_CONFIRMED", "trend_direction": "UP",
        "pullback": {"retest_candle_id": retest_id,
                     "confirmed_at_utc": (BASE + timedelta(minutes=2)).isoformat()},
    }


class SetupOutcomeTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ObservationStore(Path(self.temp.name) / "outcomes.sqlite3")
        self.tracker = SetupOutcomeTracker(self.store, pip_size=Decimal("0.0001"))
        self.retest, self.assessment = setup()
        self.eligible = {"status": "RESEARCH_ELIGIBLE", "session": "LONDON",
                         "session_date": "2026-11-19"}

    def tearDown(self):
        self.temp.cleanup()

    def assess(self, now, candles, session=None):
        return self.tracker.assess(
            evaluated_at_utc=now, broker_server="Broker", symbol="EURUSD",
            lifecycle_id="life-1", setup_assessment=self.assessment,
            session_eligibility=session or self.eligible, m1_candles=tuple(candles),
        )

    def test_reference_is_retest_close_and_mfe_mae_are_directional(self):
        bars = (self.retest, candle(2, "1.10040", "1.09980", "1.10020"))
        result = self.assess(BASE + timedelta(minutes=3), bars)
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["reference_price"], "1.10000")
        self.assertEqual(result["mfe_pips"], "4")
        self.assertEqual(result["mae_pips"], "2")
        self.assertEqual(result["candles_processed"], 1)

    def test_reference_candle_itself_is_not_counted(self):
        result = self.assess(BASE + timedelta(minutes=2), (self.retest,))
        self.assertEqual(result["candles_processed"], 0)
        self.assertEqual(result["mfe_pips"], "0")
        self.assertEqual(result["mae_pips"], "0")

    def test_idempotent_repoll_does_not_double_count(self):
        bars = (self.retest, candle(2, "1.10040", "1.09980", "1.10020"))
        first = self.assess(BASE + timedelta(minutes=3), bars)
        second = self.assess(BASE + timedelta(minutes=3), bars)
        self.assertEqual(first["candles_processed"], second["candles_processed"])
        self.assertEqual(second["mfe_pips"], "4")

    def test_only_closed_candles_are_processed(self):
        bars = (self.retest, candle(2, "1.10040", "1.09980", "1.10020"))
        result = self.assess(BASE + timedelta(minutes=2, seconds=30), bars)
        self.assertEqual(result["candles_processed"], 0)

    def test_observation_completes_at_london_session_end(self):
        bars = (self.retest, candle(2, "1.10040", "1.09980", "1.10020"))
        result = self.assess(datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc), bars,
                             session={"status": "OUTSIDE_SESSION"})
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["completed_at_utc"], "2026-11-19T12:00:00+00:00")

    def test_does_not_start_without_session_eligibility(self):
        result = self.assess(BASE + timedelta(minutes=3),
                             (self.retest, candle(2, "1.10040", "1.09980", "1.10020")),
                             session={"status": "BLOCKED"})
        self.assertEqual(result["status"], "WAITING_FOR_SESSION_ELIGIBILITY")

    def test_revised_processed_candle_quarantines_observation(self):
        original = candle(2, "1.10040", "1.09980", "1.10020")
        self.assess(BASE + timedelta(minutes=3), (self.retest, original))
        revised = candle(2, "1.10060", "1.09980", "1.10020")
        result = self.assess(BASE + timedelta(minutes=3), (self.retest, revised))
        self.assertEqual(result["status"], "DATA_CONFLICT")
        self.assertEqual(result["conflict_reason"], "PROCESSED_CANDLE_OHLC_REVISED")

    def test_new_york_session_end_uses_dst_aware_zone(self):
        retest = candle(1, "1.10020", "1.09990", "1.10000")
        retest_id = f"Broker|EURUSD|M1|{retest.candle_open_time_utc.isoformat().replace('+00:00', 'Z')}"
        assessment = {
            "stage": "PATTERN_CONFIRMED", "trend_direction": "UP",
            "pullback": {"retest_candle_id": retest_id,
                         "confirmed_at_utc": (BASE + timedelta(minutes=2)).isoformat()},
        }
        # 12:00 New York on 19 Nov 2026 is 17:00 UTC.
        tracker = self.tracker
        eligible = {"status": "RESEARCH_ELIGIBLE", "session": "NEW_YORK",
                    "session_date": "2026-11-19"}
        tracker.assess(evaluated_at_utc=datetime(2026, 11, 19, 13, 0, tzinfo=timezone.utc),
                       broker_server="Broker", symbol="EURUSD", lifecycle_id="life-ny",
                       setup_assessment=assessment, session_eligibility=eligible,
                       m1_candles=(retest,))
        result = tracker.assess(
            evaluated_at_utc=datetime(2026, 11, 19, 17, 0, tzinfo=timezone.utc),
            broker_server="Broker", symbol="EURUSD", lifecycle_id="life-ny",
            setup_assessment=assessment, session_eligibility={"status": "OUTSIDE_SESSION"},
            m1_candles=(retest,),
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["session_end_utc"], "2026-11-19T17:00:00+00:00")

    def test_completed_observation_still_detects_late_candle_revision(self):
        original = candle(2, "1.10040", "1.09980", "1.10020")
        self.assess(datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc),
                    (self.retest, original))
        revised = candle(2, "1.10070", "1.09980", "1.10020")
        result = self.assess(datetime(2026, 11, 19, 12, 1, tzinfo=timezone.utc),
                             (self.retest, revised),
                             session={"status": "OUTSIDE_SESSION"})
        self.assertEqual(result["status"], "DATA_CONFLICT")

    def test_bearish_excursions_are_mirrored(self):
        retest = candle(1, "1.10020", "1.09990", "1.10000")
        retest_id = f"Broker|EURUSD|M1|{retest.candle_open_time_utc.isoformat().replace('+00:00', 'Z')}"
        assessment = {
            "stage": "PATTERN_CONFIRMED", "trend_direction": "DOWN",
            "pullback": {"retest_candle_id": retest_id,
                         "confirmed_at_utc": (BASE + timedelta(minutes=2)).isoformat()},
        }
        result = self.tracker.assess(
            evaluated_at_utc=BASE + timedelta(minutes=3), broker_server="Broker",
            symbol="EURUSD", lifecycle_id="life-short", setup_assessment=assessment,
            session_eligibility=self.eligible,
            m1_candles=(retest, candle(2, "1.10030", "1.09960", "1.09980")),
        )
        self.assertEqual(result["mfe_pips"], "4")
        self.assertEqual(result["mae_pips"], "3")

    def test_never_emits_trade_or_order_authority(self):
        result = self.assess(BASE + timedelta(minutes=3),
                             (self.retest, candle(2, "1.10040", "1.09980", "1.10020")))
        self.assertEqual(result["trade_authority"], "NONE")
        self.assertEqual(result["order_execution"], "DISABLED")
        self.assertEqual(result["observation_type"], "PRICE_EXCURSION_ONLY")


if __name__ == "__main__":
    unittest.main()

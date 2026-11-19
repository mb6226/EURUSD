import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.engines.setup_outcome_tracker import ObservationStore, SetupOutcomeTracker
from eurusd_ai_monitor.engines.statistical_outcome_evaluator import StatisticalOutcomeEvaluator
from eurusd_ai_monitor.storage.market_data_store import Candle


BASE = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)


def candle(minute, high, low, close):
    return Candle(
        "Broker", "EURUSD", "M1", BASE + timedelta(minutes=minute),
        Decimal("1.10000"), Decimal(high), Decimal(low), Decimal(close), 10, 1, 0,
    )


class StatisticalOutcomeEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "observations.sqlite3"
        self.store = ObservationStore(self.db_path)
        self.tracker = SetupOutcomeTracker(self.store, pip_size=Decimal("0.0001"))

    def tearDown(self):
        self.temp.cleanup()

    def add_observation(self, *, lifecycle, session="LONDON", direction="UP",
                        status_time=None, mfe_high="1.10040", mae_low="1.09980"):
        retest = candle(1, "1.10020", "1.09990", "1.10000")
        retest_id = (
            f"Broker|EURUSD|M1|"
            f"{retest.candle_open_time_utc.isoformat().replace('+00:00', 'Z')}"
        )
        assessment = {
            "stage": "PATTERN_CONFIRMED",
            "trend_direction": direction,
            "pullback": {
                "retest_candle_id": retest_id,
                "confirmed_at_utc": (BASE + timedelta(minutes=2)).isoformat(),
            },
        }
        end = status_time or datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        eligibility = {
            "status": "RESEARCH_ELIGIBLE",
            "session": session,
            "session_date": "2026-11-19",
        }
        self.tracker.assess(
            evaluated_at_utc=BASE + timedelta(minutes=3),
            broker_server="Broker", symbol="EURUSD", lifecycle_id=lifecycle,
            setup_assessment=assessment, session_eligibility=eligibility,
            m1_candles=(retest, candle(2, mfe_high, mae_low, "1.10020")),
        )
        if end > BASE + timedelta(minutes=3):
            self.tracker.assess(
                evaluated_at_utc=end,
                broker_server="Broker", symbol="EURUSD", lifecycle_id=lifecycle,
                setup_assessment=assessment,
                session_eligibility={"status": "OUTSIDE_SESSION"},
                m1_candles=(retest, candle(2, mfe_high, mae_low, "1.10020")),
            )

    def test_missing_database_is_not_created_or_modified(self):
        missing = Path(self.temp.name) / "missing.sqlite3"
        report = StatisticalOutcomeEvaluator(missing).build_report(evaluated_at_utc=BASE)
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertFalse(missing.exists())

    def test_completed_observations_are_summarized(self):
        self.add_observation(lifecycle="one")
        self.add_observation(lifecycle="two", mfe_high="1.10060", mae_low="1.09970")
        report = StatisticalOutcomeEvaluator(
            self.db_path, minimum_group_samples=2
        ).build_report(evaluated_at_utc=BASE)
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(report["total_observations"], 2)
        self.assertEqual(report["usable_completed_observations"], 2)
        overall = report["groups"][0]
        self.assertEqual(overall["sample_quality"], "MINIMUM_SAMPLE_REACHED")
        self.assertEqual(overall["mfe_pips"]["mean"], "5")
        self.assertEqual(overall["mae_pips"]["mean"], "2.5")

    def test_groups_are_split_by_session_and_direction(self):
        self.add_observation(lifecycle="london-up", session="LONDON", direction="UP")
        # A New York observation ends at 17:00 UTC on this date.
        retest = candle(301, "1.10020", "1.09990", "1.10000")
        retest_id = (
            f"Broker|EURUSD|M1|"
            f"{retest.candle_open_time_utc.isoformat().replace('+00:00', 'Z')}"
        )
        assessment = {
            "stage": "PATTERN_CONFIRMED", "trend_direction": "DOWN",
            "pullback": {
                "retest_candle_id": retest_id,
                "confirmed_at_utc": (BASE + timedelta(minutes=302)).isoformat(),
            },
        }
        eligibility = {
            "status": "RESEARCH_ELIGIBLE", "session": "NEW_YORK",
            "session_date": "2026-11-19",
        }
        bars = (retest, candle(302, "1.10030", "1.09960", "1.09980"))
        self.tracker.assess(
            evaluated_at_utc=datetime(2026, 11, 19, 13, 3, tzinfo=timezone.utc),
            broker_server="Broker", symbol="EURUSD", lifecycle_id="ny-down",
            setup_assessment=assessment, session_eligibility=eligibility,
            m1_candles=bars,
        )
        self.tracker.assess(
            evaluated_at_utc=datetime(2026, 11, 19, 17, 0, tzinfo=timezone.utc),
            broker_server="Broker", symbol="EURUSD", lifecycle_id="ny-down",
            setup_assessment=assessment,
            session_eligibility={"status": "OUTSIDE_SESSION"}, m1_candles=bars,
        )
        report = StatisticalOutcomeEvaluator(self.db_path).build_report(evaluated_at_utc=BASE)
        keys = {(g["session"], g["direction"]) for g in report["groups"]}
        self.assertIn(("LONDON", "UP"), keys)
        self.assertIn(("NEW_YORK", "DOWN"), keys)

    def test_active_observations_are_excluded(self):
        retest = candle(1, "1.10020", "1.09990", "1.10000")
        retest_id = (
            f"Broker|EURUSD|M1|"
            f"{retest.candle_open_time_utc.isoformat().replace('+00:00', 'Z')}"
        )
        assessment = {
            "stage": "PATTERN_CONFIRMED", "trend_direction": "UP",
            "pullback": {
                "retest_candle_id": retest_id,
                "confirmed_at_utc": (BASE + timedelta(minutes=2)).isoformat(),
            },
        }
        self.tracker.assess(
            evaluated_at_utc=BASE + timedelta(minutes=3),
            broker_server="Broker", symbol="EURUSD", lifecycle_id="active",
            setup_assessment=assessment,
            session_eligibility={"status": "RESEARCH_ELIGIBLE",
                                 "session": "LONDON", "session_date": "2026-11-19"},
            m1_candles=(retest, candle(2, "1.10040", "1.09980", "1.10020")),
        )
        report = StatisticalOutcomeEvaluator(self.db_path).build_report(evaluated_at_utc=BASE)
        self.assertEqual(report["status"], "INSUFFICIENT_DATA")
        self.assertEqual(report["excluded_active"], 1)
        self.assertEqual(report["groups"], [])

    def test_data_conflicts_are_excluded(self):
        self.add_observation(lifecycle="conflict")
        # The Phase 9 store quarantines a revised processed candle.
        retest = candle(1, "1.10020", "1.09990", "1.10000")
        retest_id = (
            f"Broker|EURUSD|M1|"
            f"{retest.candle_open_time_utc.isoformat().replace('+00:00', 'Z')}"
        )
        assessment = {
            "stage": "PATTERN_CONFIRMED", "trend_direction": "UP",
            "pullback": {
                "retest_candle_id": retest_id,
                "confirmed_at_utc": (BASE + timedelta(minutes=2)).isoformat(),
            },
        }
        revised = candle(2, "1.10090", "1.09980", "1.10020")
        result = self.tracker.assess(
            evaluated_at_utc=datetime(2026, 11, 19, 12, 1, tzinfo=timezone.utc),
            broker_server="Broker", symbol="EURUSD", lifecycle_id="conflict",
            setup_assessment=assessment,
            session_eligibility={"status": "OUTSIDE_SESSION"},
            m1_candles=(retest, revised),
        )
        self.assertEqual(result["status"], "DATA_CONFLICT")
        report = StatisticalOutcomeEvaluator(self.db_path).build_report(evaluated_at_utc=BASE)
        self.assertEqual(report["excluded_data_conflict"], 1)
        self.assertEqual(report["usable_completed_observations"], 0)

    def test_inconsistent_candle_count_is_degraded_and_excluded(self):
        self.add_observation(lifecycle="integrity")
        import sqlite3
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "UPDATE setup_observations SET candles_processed=99 WHERE lifecycle_id='integrity'"
            )
            db.commit()
        report = StatisticalOutcomeEvaluator(self.db_path).build_report(evaluated_at_utc=BASE)
        self.assertEqual(report["status"], "DEGRADED")
        self.assertEqual(report["excluded_integrity_errors"], 1)
        self.assertEqual(report["usable_completed_observations"], 0)

    def test_report_has_no_trade_performance_claims(self):
        self.add_observation(lifecycle="one")
        report = StatisticalOutcomeEvaluator(self.db_path).build_report(evaluated_at_utc=BASE)
        self.assertEqual(report["trade_authority"], "NONE")
        self.assertEqual(report["order_execution"], "DISABLED")
        self.assertFalse(any("win_rate" in group or "expectancy" in group
                             for group in report["groups"]))

    def test_read_only_evaluator_does_not_change_observation_rows(self):
        self.add_observation(lifecycle="one")
        import sqlite3
        with closing(sqlite3.connect(self.db_path)) as db:
            before = db.execute("SELECT COUNT(*) FROM setup_observations").fetchone()[0]
        StatisticalOutcomeEvaluator(self.db_path).build_report(evaluated_at_utc=BASE)
        with closing(sqlite3.connect(self.db_path)) as db:
            after = db.execute("SELECT COUNT(*) FROM setup_observations").fetchone()[0]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()

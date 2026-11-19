import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.engines.setup_outcome_tracker import ObservationStore, SetupOutcomeTracker
from eurusd_ai_monitor.engines.regime_conditioned_outcome_evaluator import (
    RegimeConditionedOutcomeEvaluator,
)
from eurusd_ai_monitor.storage.market_data_store import Candle

BASE = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)


def candle(minute, high="1.10040", low="1.09980", close="1.10020"):
    return Candle("Broker", "EURUSD", "M1", BASE + timedelta(minutes=minute),
                  Decimal("1.10000"), Decimal(high), Decimal(low), Decimal(close), 10, 1, 0)


def context(regime="TRENDING", volatility="NORMAL", direction="UP",
            alignment="ALIGNED", window_end=None, m1_window_end=None):
    return {
        "status": "AVAILABLE",
        "algorithm_version": "market-regime-m5-m1-v1",
        "evaluated_at_utc": (BASE + timedelta(minutes=3)).isoformat(),
        "regime": regime,
        "volatility_state": volatility,
        "trend_direction": direction,
        "lower_timeframe_alignment": alignment,
        "features": {"atr_expansion_ratio": "1.1"},
        "provenance": {
            "m5_window_end_utc": (window_end or BASE + timedelta(minutes=1)).isoformat(),
            "m5_candle_ids": ["m5-a", "m5-b"],
            "m1_window_end_utc": (m1_window_end or BASE + timedelta(minutes=2)).isoformat(),
            "m1_confirmation_candle_ids": ["m1-a", "m1-b"],
        },
    }


class RegimeConditionedOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "observations.sqlite3"
        self.store = ObservationStore(self.path)
        self.tracker = SetupOutcomeTracker(self.store, pip_size=Decimal("0.0001"))
        self.retest = candle(1)
        retest_id = (
            "Broker|EURUSD|M1|"
            + self.retest.candle_open_time_utc.isoformat().replace("+00:00", "Z")
        )
        self.assessment = {
            "stage": "PATTERN_CONFIRMED", "trend_direction": "UP",
            "pullback": {
                "retest_candle_id": retest_id,
                "confirmed_at_utc": (BASE + timedelta(minutes=2)).isoformat(),
            },
        }

    def tearDown(self):
        self.temp.cleanup()

    def add(self, lifecycle, *, session="LONDON", direction="UP", regime="TRENDING",
            volatility="NORMAL", alignment="ALIGNED", supplied=True, context_value=None):
        assessment = dict(self.assessment)
        assessment["trend_direction"] = direction
        eligible = {"status": "RESEARCH_ELIGIBLE", "session": session,
                    "session_date": "2026-11-19"}
        bars = (self.retest, candle(2))
        self.tracker.assess(
            evaluated_at_utc=BASE + timedelta(minutes=3), broker_server="Broker",
            symbol="EURUSD", lifecycle_id=lifecycle, setup_assessment=assessment,
            session_eligibility=eligible, m1_candles=bars,
            regime_context=(context_value or context(regime, volatility, direction, alignment))
                if supplied else None,
        )
        self.tracker.assess(
            evaluated_at_utc=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc),
            broker_server="Broker", symbol="EURUSD", lifecycle_id=lifecycle,
            setup_assessment=assessment,
            session_eligibility={"status": "OUTSIDE_SESSION"}, m1_candles=bars,
        )

    def report(self, minimum=1):
        return RegimeConditionedOutcomeEvaluator(
            self.path, minimum_group_samples=minimum
        ).build_report(evaluated_at_utc=datetime(2026, 11, 19, 12, 1, tzinfo=timezone.utc))

    def test_completed_observations_are_segmented_by_setup_time_regime_and_volatility(self):
        self.add("trend-normal-1")
        self.add("trend-normal-2")
        self.add("range-high", regime="RANGING", volatility="HIGH", alignment="OPPOSED")
        report = self.report(minimum=2)
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(report["usable_regime_conditioned_observations"], 3)
        keys = {(g["dimension"], tuple(g["segments"])) for g in report["groups"]}
        self.assertIn(("REGIME", ("TRENDING",)), keys)
        self.assertIn(("ALGORITHM_VERSION_REGIME", ("market-regime-m5-m1-v1", "TRENDING")), keys)
        self.assertIn(("VOLATILITY", ("HIGH",)), keys)
        self.assertIn(("REGIME_VOLATILITY", ("RANGING", "HIGH")), keys)
        self.assertIn(("SESSION_DIRECTION_REGIME", ("LONDON", "UP", "TRENDING")), keys)
        trend = next(g for g in report["groups"]
                     if g["dimension"] == "REGIME" and g["segments"] == ["TRENDING"])
        self.assertEqual(trend["sample_size"], 2)
        self.assertEqual(trend["sample_quality"], "MINIMUM_SAMPLE_REACHED")

    def test_context_is_immutable(self):
        self.add("immutable")
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE observation_regime_context SET regime='RANGING' WHERE setup_key LIKE 'immutable:%'"
                )

    def test_future_m5_window_is_rejected_at_capture(self):
        future = context(window_end=BASE + timedelta(minutes=3))
        self.add("future-context", context_value=future)
        report = self.report()
        self.assertEqual(report["usable_regime_conditioned_observations"], 0)
        self.assertEqual(report["excluded_without_valid_setup_time_regime"], 1)
        self.assertEqual(report["context_status_counts"]["TEMPORAL_ALIGNMENT_FAILED"], 1)

    def test_future_m1_alignment_window_is_rejected_at_capture(self):
        future = context(m1_window_end=BASE + timedelta(minutes=3))
        self.add("future-m1-context", context_value=future)
        report = self.report()
        self.assertEqual(report["usable_regime_conditioned_observations"], 0)
        self.assertEqual(report["excluded_without_valid_setup_time_regime"], 1)
        self.assertEqual(report["context_status_counts"]["M1_TEMPORAL_ALIGNMENT_FAILED"], 1)

    def test_old_observation_without_context_is_never_backfilled(self):
        self.add("legacy", supplied=False)
        # A later poll has valid current regime data, but cannot rewrite the setup-time context.
        bars = (self.retest, candle(2))
        self.tracker.assess(
            evaluated_at_utc=BASE + timedelta(minutes=4), broker_server="Broker",
            symbol="EURUSD", lifecycle_id="legacy", setup_assessment=self.assessment,
            session_eligibility={"status": "OUTSIDE_SESSION"}, m1_candles=bars,
            regime_context=context("TRENDING", "HIGH"),
        )
        report = self.report()
        self.assertEqual(report["usable_regime_conditioned_observations"], 0)
        self.assertEqual(report["context_status_counts"]["NOT_SUPPLIED"], 1)

    def test_active_observation_is_excluded(self):
        self.tracker.assess(
            evaluated_at_utc=BASE + timedelta(minutes=3), broker_server="Broker",
            symbol="EURUSD", lifecycle_id="active", setup_assessment=self.assessment,
            session_eligibility={"status": "RESEARCH_ELIGIBLE", "session": "LONDON",
                                 "session_date": "2026-11-19"},
            m1_candles=(self.retest, candle(2)), regime_context=context(),
        )
        report = self.report()
        self.assertEqual(report["excluded_active"], 1)
        self.assertEqual(report["usable_regime_conditioned_observations"], 0)

    def test_read_only_evaluator_does_not_mutate_context_or_observations(self):
        self.add("readonly")
        with closing(sqlite3.connect(self.path)) as db:
            before = db.execute(
                "SELECT COUNT(*) FROM observation_regime_context"
            ).fetchone()[0]
        self.report()
        with closing(sqlite3.connect(self.path)) as db:
            after = db.execute(
                "SELECT COUNT(*) FROM observation_regime_context"
            ).fetchone()[0]
        self.assertEqual(before, after)

    def test_existing_regime_context_schema_is_upgraded_with_m1_provenance(self):
        legacy_path = Path(self.temp.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy_path)) as db:
            db.execute("""
                CREATE TABLE observation_regime_context (
                    setup_key TEXT PRIMARY KEY,
                    context_status TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    volatility_state TEXT NOT NULL,
                    trend_direction TEXT NOT NULL,
                    lower_timeframe_alignment TEXT NOT NULL,
                    algorithm_version TEXT,
                    evaluated_at_utc TEXT,
                    m5_window_end_utc TEXT,
                    m5_candle_ids_json TEXT NOT NULL DEFAULT '[]',
                    features_json TEXT NOT NULL DEFAULT '{}',
                    reason_codes_json TEXT NOT NULL DEFAULT '[]'
                )
            """)
            db.commit()
        ObservationStore(legacy_path)
        with closing(sqlite3.connect(legacy_path)) as db:
            columns = {row[1] for row in db.execute(
                "PRAGMA table_info(observation_regime_context)"
            ).fetchall()}
        self.assertIn("m1_candle_ids_json", columns)
        self.assertIn("m1_window_end_utc", columns)

    def test_missing_database_is_not_created(self):
        missing = Path(self.temp.name) / "missing.sqlite3"
        report = RegimeConditionedOutcomeEvaluator(missing).build_report(
            evaluated_at_utc=BASE
        )
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertFalse(missing.exists())

    def test_report_has_no_trade_authority_or_profitability_claim(self):
        self.add("safe")
        report = self.report()
        self.assertEqual(report["trade_authority"], "NONE")
        self.assertEqual(report["order_execution"], "DISABLED")
        self.assertFalse(any("win_rate" in group or "expectancy" in group
                             for group in report["groups"]))


if __name__ == "__main__":
    unittest.main()

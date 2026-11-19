from datetime import datetime, timedelta, timezone
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from eurusd_ai_monitor.engines.historical_scenario_replay_engine import (
    HistoricalScenarioReplayEngine,
)
from eurusd_ai_monitor.storage.market_data_store import Candle, MarketDataStore


UTC = timezone.utc
BASE = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)


def candle(minute, close):
    price = Decimal(close)
    return Candle(
        broker_server="Broker-Demo",
        symbol="EURUSD",
        timeframe="M1",
        candle_open_time_utc=BASE + timedelta(minutes=minute),
        open=price - Decimal("0.0001"),
        high=price + Decimal("0.0001"),
        low=price - Decimal("0.0002"),
        close=price,
        tick_volume=10,
        spread=2,
        real_volume=0,
    )


def report(*, state="UP", evaluated_at=None, symbol="EURUSD"):
    evaluated_at = evaluated_at or (BASE + timedelta(minutes=5))
    return {
        "report_type": "CENTRAL_MULTI_DOMAIN_SCENARIO_INTELLIGENCE",
        "status": "ASSESSMENT_ONLY",
        "evaluated_at_utc": evaluated_at.isoformat(),
        "broker_server": "Broker-Demo",
        "symbol": symbol,
        "directional_assessment": {"state": state},
        "scenario_hypotheses": [],
    }


class HistoricalScenarioReplayEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketDataStore(Path(self.temp.name) / "market.sqlite")
        self.store.upsert_candles(
            [candle(i, str(Decimal("1.1000") + Decimal(i) * Decimal("0.0002"))) for i in range(12)],
            as_of_utc=BASE + timedelta(minutes=20),
            observed_at_utc=BASE + timedelta(minutes=20),
        )
        self.engine = HistoricalScenarioReplayEngine(
            self.store, pip_size="0.0001", timeframe="M1",
            horizons_bars=(2,), neutral_band_pips="2",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_replay_scores_a_resolved_scenario_against_future_closed_bars(self):
        result = self.engine.replay(
            [report()], broker_server="Broker-Demo", symbol="EURUSD"
        )
        horizon = result["horizons"]["2"]
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(horizon["sample_size"], 1)
        self.assertEqual(horizon["scenario_accuracy"], "1")
        self.assertEqual(horizon["directional_accuracy"], "1")
        self.assertEqual(
            horizon["confusion_matrix_forecast_rows_realized_columns"]["UP"]["UP"], 1
        )
        self.assertEqual(result["trade_authority"], "NONE")
        self.assertEqual(result["order_execution"], "DISABLED")

    def test_down_forecast_is_not_given_credit_for_upward_outcome(self):
        result = self.engine.replay(
            [report(state="DOWN")], broker_server="Broker-Demo", symbol="EURUSD"
        )
        self.assertEqual(result["horizons"]["2"]["scenario_accuracy"], "0")

    def test_unresolved_conflicted_and_wrong_identity_reports_are_excluded(self):
        result = self.engine.replay(
            [
                report(state="CONFLICTED"),
                report(symbol="OTHER"),
            ],
            broker_server="Broker-Demo", symbol="EURUSD",
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["valid_resolved_scenario_reports"], 0)
        self.assertEqual(result["rejected_counts"]["UNRESOLVED_OR_CONFLICTED_FORECAST"], 1)
        self.assertEqual(result["rejected_counts"]["REPORT_IDENTITY_MISMATCH"], 1)

    def test_report_timestamp_after_available_market_data_has_no_anchor(self):
        result = self.engine.replay(
            [report(evaluated_at=BASE + timedelta(hours=1))],
            broker_server="Broker-Demo", symbol="EURUSD",
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["rejected_counts"]["NO_CLOSED_ANCHOR_CANDLE"], 1)

    def test_future_revision_of_horizon_candle_excludes_sample(self):
        revised = candle(5, "1.1015")
        self.store.upsert_candles(
            [revised],
            as_of_utc=BASE + timedelta(minutes=20),
            observed_at_utc=BASE + timedelta(minutes=10),
        )
        result = self.engine.replay(
            [report()], broker_server="Broker-Demo", symbol="EURUSD"
        )
        self.assertEqual(result["horizons"]["2"]["sample_size"], 0)
        self.assertEqual(result["rejected_counts"]["POST_FORECAST_CANDLE_REVISION_H2"], 1)

    def test_invalid_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            HistoricalScenarioReplayEngine(self.store, pip_size="0")
        with self.assertRaises(ValueError):
            HistoricalScenarioReplayEngine(self.store, pip_size="0.0001", horizons_bars=(0,))


if __name__ == "__main__":
    unittest.main()

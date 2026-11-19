from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import tempfile
import unittest
from pathlib import Path

from eurusd_ai_monitor.engines.historical_scenario_replay_engine import (
    HistoricalScenarioReplayEngine,
)
from eurusd_ai_monitor.engines.historical_scenario_replay_runtime import replay_monitor_logs
from eurusd_ai_monitor.storage.market_data_store import Candle, MarketDataStore


UTC = timezone.utc
BASE = datetime(2026, 11, 1, tzinfo=UTC)


class HistoricalScenarioReplayRuntimeTests(unittest.TestCase):
    def test_reads_archived_central_scenario_reports_and_ignores_bad_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = MarketDataStore(root / "market.sqlite")
            candles = []
            for minute in range(10):
                close = Decimal("1.1000") + Decimal(minute) * Decimal("0.0002")
                candles.append(Candle(
                    broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
                    candle_open_time_utc=BASE + timedelta(minutes=minute),
                    open=close, high=close + Decimal("0.0001"),
                    low=close - Decimal("0.0001"), close=close,
                    tick_volume=10, spread=2, real_volume=0,
                ))
            store.upsert_candles(
                candles,
                as_of_utc=BASE + timedelta(minutes=20),
                observed_at_utc=BASE + timedelta(minutes=20),
            )
            scenario = {
                "report_type": "CENTRAL_MULTI_DOMAIN_SCENARIO_INTELLIGENCE",
                "status": "ASSESSMENT_ONLY",
                "evaluated_at_utc": (BASE + timedelta(minutes=5)).isoformat(),
                "broker_server": "Broker-Demo", "symbol": "EURUSD",
                "directional_assessment": {"state": "UP"},
            }
            log = root / "monitor.jsonl"
            log.write_text(
                json.dumps({"central_scenario_intelligence": scenario}) + "\n"
                + "{bad json\n"
                + json.dumps({"decision": "WAIT"}) + "\n",
                encoding="utf-8",
            )
            engine = HistoricalScenarioReplayEngine(
                store, pip_size="0.0001", horizons_bars=(2,)
            )
            result = replay_monitor_logs(
                engine, [log], broker_server="Broker-Demo", symbol="EURUSD"
            )
            self.assertEqual(result["horizons"]["2"]["sample_size"], 1)
            self.assertEqual(result["archive_ingestion"]["records_seen"], 3)
            self.assertEqual(result["archive_ingestion"]["malformed_lines"], 1)
            self.assertFalse(result["archive_ingestion"]["source_files_modified"])


if __name__ == "__main__":
    unittest.main()

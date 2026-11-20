import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eurusd_ai_monitor.engines.point_in_time_reconstruction_engine import (
    PointInTimeReconstructionEngine,
)
from eurusd_ai_monitor.engines.point_in_time_reconstruction_runtime import (
    replay_point_in_time_jsonl,
    replay_deterministic_specialist_jsonl,
)
from eurusd_ai_monitor.storage.market_data_store import MarketDataStore


UTC = timezone.utc
BASE = datetime(2026, 11, 1, tzinfo=UTC)


class PointInTimeReconstructionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MarketDataStore(self.root / "market.sqlite")
        self.engine = PointInTimeReconstructionEngine(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_archived_specialist_reports_without_mutating_jsonl(self):
        log = self.root / "monitor.jsonl"
        record = {
            "evaluated_at_utc": (BASE + timedelta(minutes=10)).isoformat(),
            "specialist_reports": {
                "technical_analysis": {
                    "evaluated_at_utc": (BASE + timedelta(minutes=10)).isoformat(),
                    "broker_server": "Broker-Demo", "symbol": "EURUSD",
                    "status": "AVAILABLE",
                }
            },
        }
        log.write_text(json.dumps(record) + "\n", encoding="utf-8")
        before = log.read_bytes()
        result = replay_point_in_time_jsonl(
            self.engine, [log], broker_server="Broker-Demo",
            symbol="EURUSD", timeframe="M1", start_utc=BASE,
            end_utc=BASE + timedelta(minutes=20),
        )
        self.assertEqual(result["archive_ingestion"]["replay_points_found"], 1)
        self.assertFalse(result["archive_ingestion"]["source_files_modified"])
        self.assertEqual(log.read_bytes(), before)

    def test_malformed_and_unarchived_records_degrade_coverage(self):
        log = self.root / "monitor.jsonl"
        log.write_text(
            "not-json\n" + json.dumps({"evaluated_at_utc": BASE.isoformat()}) + "\n",
            encoding="utf-8",
        )
        result = replay_point_in_time_jsonl(
            self.engine, [log], broker_server="Broker-Demo",
            symbol="EURUSD", timeframe="M1", start_utc=BASE,
            end_utc=BASE + timedelta(minutes=20),
        )
        self.assertEqual(result["archive_ingestion"]["malformed_lines"], 1)
        self.assertEqual(result["archive_ingestion"]["records_without_archived_specialist_reports"], 1)
        self.assertEqual(result["status"], "PARTIAL")

    def test_extracts_existing_monitor_payload_report_fields(self):
        log = self.root / "monitor-fields.jsonl"
        record = {
            "market_context": {
                "timestamp_utc": (BASE + timedelta(minutes=10)).isoformat(),
                "broker_server": "Broker-Demo",
            },
            "technical_analysis": {
                "evaluated_at_utc": (BASE + timedelta(minutes=10)).isoformat(),
                "broker_server": "Broker-Demo", "symbol": "EURUSD",
                "status": "AVAILABLE",
            },
        }
        log.write_text(json.dumps(record) + "\n", encoding="utf-8")
        result = replay_point_in_time_jsonl(
            self.engine, [log], broker_server="Broker-Demo",
            symbol="EURUSD", timeframe="M1", start_utc=BASE,
            end_utc=BASE + timedelta(minutes=20),
        )
        self.assertEqual(result["archive_ingestion"]["replay_points_found"], 1)
        self.assertEqual(result["points"][0]["archived_specialist_report_count"], 1)


    def test_registry_driven_data_plane_is_wired_into_replay(self):
        class RegistryDataPlane:
            def build_observation_requests(self):
                return {
                    "macro_fundamentals": (("US_BLS_MACRO", "US_CPI"),),
                    "intermarket": (("FRED_INTERMARKET", "US_10Y"),),
                }

        class CapturingEngine(PointInTimeReconstructionEngine):
            def replay(self, points, **kwargs):
                self.captured_requests = kwargs["observation_requests"]
                return {
                    "status": "AVAILABLE",
                    "replay_points_processed": len(points),
                }

        log = self.root / "registry-replay.jsonl"
        record = {
            "evaluated_at_utc": (BASE + timedelta(minutes=10)).isoformat(),
            "specialist_reports": {
                "technical_analysis": {
                    "evaluated_at_utc": (BASE + timedelta(minutes=10)).isoformat(),
                    "broker_server": "Broker-Demo", "symbol": "EURUSD",
                    "status": "AVAILABLE",
                }
            },
        }
        log.write_text(json.dumps(record) + "\n", encoding="utf-8")
        engine = CapturingEngine(self.store)
        result = replay_point_in_time_jsonl(
            engine, [log], broker_server="Broker-Demo", symbol="EURUSD",
            timeframe="M1", start_utc=BASE, end_utc=BASE + timedelta(minutes=20),
            data_plane=RegistryDataPlane(),
        )
        self.assertEqual(engine.captured_requests, {
            "macro_fundamentals": (("US_BLS_MACRO", "US_CPI"),),
            "intermarket": (("FRED_INTERMARKET", "US_10Y"),),
        })
        self.assertEqual(
            result["archive_ingestion"]["observation_request_source"],
            "REGISTRY_DRIVEN_DATA_PLANE",
        )
        self.assertEqual(result["archive_ingestion"]["observation_product_requests"], 2)

    def test_data_plane_and_explicit_requests_cannot_be_supplied_together(self):
        class RegistryDataPlane:
            def build_observation_requests(self):
                return {}

        log = self.root / "both-requests.jsonl"
        log.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            replay_point_in_time_jsonl(
                self.engine, [log], broker_server="Broker-Demo",
                symbol="EURUSD", timeframe="M1", start_utc=BASE,
                end_utc=BASE + timedelta(minutes=20),
                observation_requests={}, data_plane=RegistryDataPlane(),
            )


    def test_registry_driven_data_plane_is_wired_into_deterministic_replay(self):
        class RegistryDataPlane:
            def build_observation_requests(self):
                return {
                    "monetary_policy": (("ECB_POLICY_RATES", "ECB_DEPOSIT"),),
                }

        class CapturingEngine:
            def replay(self, points, **kwargs):
                self.captured_requests = kwargs["observation_requests"]
                return {
                    "status": "AVAILABLE",
                    "replay_points_processed": len(points),
                }

        log = self.root / "deterministic-registry-replay.jsonl"
        log.write_text(json.dumps({
            "market_context": {"timestamp_utc": (BASE + timedelta(minutes=5)).isoformat()}
        }) + "\n", encoding="utf-8")
        engine = CapturingEngine()
        result = replay_deterministic_specialist_jsonl(
            engine, [log], broker_server="Broker-Demo", symbol="EURUSD",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=20),
            data_plane=RegistryDataPlane(),
        )
        self.assertEqual(engine.captured_requests, {
            "monetary_policy": (("ECB_POLICY_RATES", "ECB_DEPOSIT"),),
        })
        self.assertEqual(
            result["archive_ingestion"]["observation_request_source"],
            "REGISTRY_DRIVEN_DATA_PLANE",
        )
        self.assertEqual(result["archive_ingestion"]["observation_product_requests"], 1)

    def test_invalid_log_paths_type_is_rejected(self):
        with self.assertRaises(TypeError):
            replay_point_in_time_jsonl(
                self.engine, self.root / "monitor.jsonl",
                broker_server="Broker-Demo", symbol="EURUSD",
                timeframe="M1", start_utc=BASE, end_utc=BASE + timedelta(minutes=10),
            )


if __name__ == "__main__":
    unittest.main()

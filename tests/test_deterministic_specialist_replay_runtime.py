import json
from datetime import datetime, timezone

from eurusd_ai_monitor.engines.point_in_time_reconstruction_runtime import (
    replay_deterministic_specialist_jsonl,
)


class StubReplay:
    def __init__(self):
        self.points = []

    def replay(self, points, **kwargs):
        self.points = list(points)
        return {
            "status": "PARTIAL",
            "replay_points_received": len(self.points),
            "replay_points_processed": len(self.points),
            "broker_server": kwargs["broker_server"],
            "symbol": kwargs["symbol"],
        }


def test_deterministic_jsonl_adapter_needs_only_cycle_timestamps(tmp_path):
    path = tmp_path / "monitor.jsonl"
    records = [
        {"market_context": {"timestamp_utc": "2024-01-02T12:00:00+00:00"},
         "technical_analysis": {"evaluated_at_utc": "future report ignored"}},
        {"evaluated_at_utc": "2024-01-02T12:05:00+00:00"},
    ]
    original = "\n".join(json.dumps(row) for row in records) + "\n"
    path.write_text(original, encoding="utf-8")
    engine = StubReplay()

    result = replay_deterministic_specialist_jsonl(
        engine, [path], broker_server="Broker-Demo", symbol="EURUSD",
        start_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
        end_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
    )

    assert engine.points == [
        {"evaluated_at_utc": "2024-01-02T12:00:00+00:00"},
        {"evaluated_at_utc": "2024-01-02T12:05:00+00:00"},
    ]
    assert result["archive_ingestion"]["archived_specialist_reports_required"] is False
    assert result["archive_ingestion"]["source_files_modified"] is False
    assert path.read_text(encoding="utf-8") == original


def test_deterministic_jsonl_adapter_reports_malformed_and_missing_times(tmp_path):
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        "{bad json}\n" + json.dumps({"other": "payload"}) + "\n"
        + json.dumps({"evaluated_at_utc": "2024-01-02T12:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    engine = StubReplay()
    result = replay_deterministic_specialist_jsonl(
        engine, [path], broker_server="Broker-Demo", symbol="EURUSD",
        start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
    )
    assert len(engine.points) == 1
    assert result["archive_ingestion"]["malformed_lines"] == 1
    assert result["archive_ingestion"]["records_missing_evaluation_timestamp"] == 1
    assert result["archive_ingestion"]["coverage_warning"] == "ARCHIVE_COVERAGE_INCOMPLETE"

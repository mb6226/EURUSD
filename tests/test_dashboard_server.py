from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dashboard_server


class DashboardTailTests(unittest.TestCase):
    def test_tail_records_returns_newest_records_in_chronological_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for index in range(5):
                    handle.write(json.dumps({"created_at_utc": str(index), "decision": "WAIT"}) + "\n")
            records = dashboard_server.tail_records(path, max_records=3)
        self.assertEqual([item["created_at_utc"] for item in records], ["2", "3", "4"])

    def test_tail_records_skips_partial_leading_line_when_window_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.jsonl"
            rows = [json.dumps({"index": index, "payload": "x" * 24}) for index in range(4)]
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            records = dashboard_server.tail_records(path, max_records=2, max_bytes=100)
        self.assertEqual([item["index"] for item in records], [3])

    def test_dashboard_check_snapshot_exposes_live_history_and_reports(self) -> None:
        snapshot = dashboard_server.collect()
        self.assertIn("history", snapshot)
        self.assertIn("reports", snapshot)
        self.assertIn("archive", snapshot)
        self.assertIn("data_archives", snapshot)
        self.assertEqual(set(snapshot["data_archives"]), {"raw_snapshots", "observations", "calendar"})
        self.assertIn("price_series", snapshot)
        self.assertLessEqual(len(snapshot["history"]), 10)

    def test_inspect_store_reports_read_only_integrity_and_group_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE raw_snapshots (source_id TEXT, payload_bytes INTEGER)")
            connection.execute("INSERT INTO raw_snapshots VALUES ('FRED_INTERMARKET', 123)")
            connection.commit()
            connection.close()
            result = dashboard_server.inspect_store(path, {
                "summary": ("raw_snapshots", "SELECT COUNT(*) AS snapshots, SUM(payload_bytes) AS payload_bytes FROM raw_snapshots"),
                "by_source": ("raw_snapshots", "SELECT source_id, COUNT(*) AS snapshots FROM raw_snapshots GROUP BY source_id"),
            })
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(result["status"], "HEALTHY")
        self.assertEqual(result["snapshots"], 1)
        self.assertEqual(result["payload_bytes"], 123)
        self.assertEqual(result["by_source"][0]["source_id"], "FRED_INTERMARKET")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from eurusd_ai_monitor.engines.historical_scenario_replay_engine import (
    HistoricalScenarioReplayEngine,
)


def replay_monitor_logs(
    engine: HistoricalScenarioReplayEngine,
    log_paths: Iterable[str | Path],
    *,
    broker_server: str,
    symbol: str,
) -> dict:
    """Replay archived monitoring JSONL outputs without modifying any source file."""
    if not isinstance(engine, HistoricalScenarioReplayEngine):
        raise TypeError("engine must be a HistoricalScenarioReplayEngine")
    if isinstance(log_paths, (str, bytes, Path)):
        raise TypeError("log_paths must be an iterable of paths")
    paths = tuple(Path(path) for path in log_paths)
    reports = []
    malformed_lines = 0
    unreadable_files = 0
    records_seen = 0
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    records_seen += 1
                    try:
                        payload = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        malformed_lines += 1
                        continue
                    if not isinstance(payload, dict):
                        malformed_lines += 1
                        continue
                    scenario = payload.get("central_scenario_intelligence")
                    if isinstance(scenario, dict):
                        reports.append(scenario)
        except OSError:
            unreadable_files += 1

    result = engine.replay(
        reports, broker_server=broker_server, symbol=symbol
    )
    result["archive_ingestion"] = {
        "files_requested": len(paths),
        "records_seen": records_seen,
        "scenario_reports_found": len(reports),
        "malformed_lines": malformed_lines,
        "unreadable_files": unreadable_files,
        "source_files_modified": False,
    }
    if unreadable_files and result["status"] == "AVAILABLE":
        result["archive_ingestion"]["coverage_warning"] = "ONE_OR_MORE_ARCHIVE_FILES_UNREADABLE"
    return result

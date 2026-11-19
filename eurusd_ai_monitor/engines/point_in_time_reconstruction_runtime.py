from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from eurusd_ai_monitor.engines.point_in_time_reconstruction_engine import (
    PointInTimeReconstructionEngine,
)


def replay_point_in_time_jsonl(
    engine: PointInTimeReconstructionEngine,
    log_paths: Iterable[str | Path],
    *,
    broker_server: str,
    symbol: str,
    timeframe: str,
    start_utc,
    end_utc,
    observation_requests=None,
) -> dict:
    """Read archived point-in-time specialist reports without changing source logs.

    Each JSONL record must contain evaluated_at_utc and specialist_reports.
    Current live reports are never substituted for absent historical reports.
    """
    if not isinstance(engine, PointInTimeReconstructionEngine):
        raise TypeError("engine must be a PointInTimeReconstructionEngine")
    if isinstance(log_paths, (str, bytes, Path)):
        raise TypeError("log_paths must be an iterable of paths")
    paths = tuple(Path(path) for path in log_paths)
    points = []
    malformed = 0
    unreadable = 0
    records_seen = 0
    records_without_archived_reports = 0
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    records_seen += 1
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        malformed += 1
                        continue
                    if not isinstance(record, dict):
                        malformed += 1
                        continue
                    reports = record.get("specialist_reports")
                    if not isinstance(reports, dict):
                        report_names = (
                            "technical_analysis", "price_action_lifecycle",
                            "market_regime_intelligence", "fusion_assessment",
                            "macro_fundamentals_intelligence",
                            "policy_rate_differential_intelligence",
                            "intermarket_intelligence",
                            "positioning_sentiment_intelligence",
                            "quantitative_market_statistics",
                            "liquidity_microstructure_intelligence",
                            "macro_calendar", "news_intelligence",
                            "setup_assessment", "session_eligibility",
                            "setup_outcome_observation",
                            "statistical_outcome_evaluation",
                            "regime_conditioned_outcome_evaluation",
                        )
                        reports = {
                            name: record[name] for name in report_names
                            if isinstance(record.get(name), dict)
                        }
                    if not reports:
                        records_without_archived_reports += 1
                        continue
                    market_context = record.get("market_context")
                    market_context = market_context if isinstance(market_context, dict) else {}
                    points.append({
                        "evaluated_at_utc": (
                            record.get("evaluated_at_utc")
                            or market_context.get("timestamp_utc")
                        ),
                        "specialist_reports": reports,
                    })
        except OSError:
            unreadable += 1

    result = engine.replay(
        points,
        broker_server=broker_server,
        symbol=symbol,
        timeframe=timeframe,
        start_utc=start_utc,
        end_utc=end_utc,
        observation_requests=observation_requests,
    )
    result["archive_ingestion"] = {
        "files_requested": len(paths),
        "records_seen": records_seen,
        "replay_points_found": len(points),
        "records_without_archived_specialist_reports": records_without_archived_reports,
        "malformed_lines": malformed,
        "unreadable_files": unreadable,
        "source_files_modified": False,
    }
    if unreadable or malformed or records_without_archived_reports:
        result["archive_ingestion"]["coverage_warning"] = "ARCHIVE_COVERAGE_INCOMPLETE"
        if result["status"] in {"AVAILABLE", "INSUFFICIENT_DATA"}:
            result["status"] = "PARTIAL"
    return result



def replay_deterministic_specialist_jsonl(
    engine,
    log_paths: Iterable[str | Path],
    *,
    broker_server: str,
    symbol: str,
    start_utc,
    end_utc,
    observation_requests=None,
) -> dict:
    """Replay cycle timestamps from immutable monitor JSONL with no archived-report dependency."""
    if not callable(getattr(engine, "replay", None)):
        raise TypeError("engine must expose replay")
    if isinstance(log_paths, (str, bytes, Path)):
        raise TypeError("log_paths must be an iterable of paths")
    paths = tuple(Path(path) for path in log_paths)
    points = []
    malformed = unreadable = records_seen = missing_timestamp = 0
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    records_seen += 1
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        malformed += 1
                        continue
                    if not isinstance(record, dict):
                        malformed += 1
                        continue
                    market = record.get("market_context")
                    market = market if isinstance(market, dict) else {}
                    evaluated = record.get("evaluated_at_utc") or market.get("timestamp_utc")
                    if not isinstance(evaluated, str) or not evaluated.strip():
                        missing_timestamp += 1
                        continue
                    points.append({"evaluated_at_utc": evaluated})
        except OSError:
            unreadable += 1

    result = engine.replay(
        points, broker_server=broker_server, symbol=symbol,
        start_utc=start_utc, end_utc=end_utc,
        observation_requests=observation_requests,
    )
    result["archive_ingestion"] = {
        "files_requested": len(paths),
        "records_seen": records_seen,
        "replay_points_found": len(points),
        "records_missing_evaluation_timestamp": missing_timestamp,
        "malformed_lines": malformed,
        "unreadable_files": unreadable,
        "source_files_modified": False,
        "archived_specialist_reports_required": False,
    }
    if unreadable or malformed or missing_timestamp:
        result["archive_ingestion"]["coverage_warning"] = "ARCHIVE_COVERAGE_INCOMPLETE"
        result["status"] = "PARTIAL" if result.get("replay_points_processed") else "INSUFFICIENT_DATA"
    return result

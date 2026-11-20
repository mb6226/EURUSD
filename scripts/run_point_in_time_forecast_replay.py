from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eurusd_ai_monitor.storage.market_data_store import (
    DEFAULT_MARKET_DATA_DB_PATH, MarketDataStore,
)
from eurusd_ai_monitor.storage.forecast_replay_store import (
    DEFAULT_FORECAST_REPLAY_DB_PATH, ForecastReplayLedger,
)
from eurusd_ai_monitor.engines.point_in_time_forecast_replay_engine import (
    PointInTimeForecastReplayEngine,
)


def parse_time(value: str | None):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run strict system-knowledge EURUSD forecast replay from a read-only market archive."
    )
    parser.add_argument("--start", type=parse_time)
    parser.add_argument("--end", type=parse_time)
    parser.add_argument("--evaluation-cutoff", type=parse_time)
    parser.add_argument("--broker-server", default="Headway-Real")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DATA_DB_PATH)
    parser.add_argument("--ledger-db", type=Path, default=DEFAULT_FORECAST_REPLAY_DB_PATH)
    parser.add_argument(
        "--report", type=Path,
        default=Path(__file__).resolve().parents[1] / "reports" / "phase45_point_in_time_forecast_replay_report.json",
    )
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    market = MarketDataStore.open_read_only(args.market_db)
    metadata = market.get_history_metadata()
    if not metadata.get("version_ledger_available"):
        result = {
            "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY",
            "engine_version": PointInTimeForecastReplayEngine.VERSION,
            "phase": 45, "status": "BLOCKED",
            "reason_codes": ["CANDLE_VERSION_LEDGER_UNAVAILABLE"],
            "market_archive_metadata": metadata,
            "production_database_mutated": False,
            "automatic_fetch": False,
        }
    elif args.start is None or args.end is None:
        result = {
            "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY",
            "engine_version": PointInTimeForecastReplayEngine.VERSION,
            "phase": 45, "status": "REPLAY_WINDOW_REQUIRED",
            "market_archive_metadata": metadata,
            "production_database_mutated": False,
            "automatic_fetch": False,
        }
    else:
        result = PointInTimeForecastReplayEngine().run(
            market, broker_server=args.broker_server, start_utc=args.start,
            end_utc=args.end, evaluation_cutoff_utc=args.evaluation_cutoff,
        )
        result["production_database_mutated"] = False
        result["automatic_fetch"] = False
        if result.get("status") == "COMPLETE" and not args.no_persist:
            ledger = ForecastReplayLedger(args.ledger_db)
            result["persistence"] = ledger.append_run(result)
            result["ledger_summary"] = ledger.get_summary()

    report = {k: v for k, v in result.items() if k != "records"}
    report["persisted_record_preview"] = result.get("records", [])[:5]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"), "reason_codes": result.get("reason_codes"),
        "forecast_cutoff_count": result.get("forecast_cutoff_count"),
        "forecast_record_count": result.get("forecast_record_count"),
        "outcome_available_count": result.get("outcome_available_count"),
        "report_path": str(args.report),
    }, indent=2))
    return 0 if result.get("status") in {"COMPLETE", "BLOCKED", "REPLAY_WINDOW_REQUIRED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

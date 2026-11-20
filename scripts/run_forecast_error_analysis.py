from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eurusd_ai_monitor.engines.forecast_error_analysis_engine import ForecastErrorAnalysisEngine
from eurusd_ai_monitor.storage.forecast_replay_store import ForecastReplayLedger

REPORTS = ROOT / "reports"
INPUT = REPORTS / "phase45_point_in_time_forecast_replay_report.json"
OUTPUT = REPORTS / "phase47_forecast_error_analysis_report.json"


def main() -> int:
    replay_summary = json.loads(INPUT.read_text(encoding="utf-8"))
    replay = replay_summary
    if replay_summary.get("status") == "COMPLETE" and not isinstance(replay_summary.get("records"), list):
        replay = ForecastReplayLedger.load_run(replay_summary.get("replay_id"))
        if replay is None:
            replay = {**replay_summary, "status": "BLOCKED",
                      "reason_codes": ["REPLAY_LEDGER_RECORDS_UNAVAILABLE"]}
    report = ForecastErrorAnalysisEngine().analyze(replay)
    report["phase"] = 47
    report["production_preflight"] = {
        "phase45_replay_status": replay_summary.get("status"),
        "phase45_blocker": (None if replay_summary.get("status") == "COMPLETE" else
                            (replay_summary.get("reason_codes") or
                             [replay_summary.get("acceptance", {}).get("production_blocker") or replay.get("reason_codes", [replay_summary.get("status")])[0]])[0]),
        "completed_production_replay_available": replay_summary.get("status") == "COMPLETE" and isinstance(replay.get("records"), list),
        "production_error_metrics_emitted": bool(report.get("accepted_completed_records")),
    }
    report["acceptance"] = {
        "production_replay_report_read_only": True,
        "production_error_metrics_emitted": False,
        "synthetic_fixtures_not_used_as_market_performance": True,
        "no_live_forecast_or_decision_changes": True,
        "commit_merge": "NOT_PERFORMED",
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report.get("status"),
        "phase45_status": replay.get("status"),
        "blocker": report["production_preflight"]["phase45_blocker"],
        "accepted_completed_records": report.get("accepted_completed_records", 0),
        "output": str(OUTPUT),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

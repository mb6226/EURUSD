from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from source_registry.data_plane import PointInTimeDataPlane
from eurusd_ai_monitor.engines.session_time_intelligence_engine import SessionTimeIntelligenceEngine
cutoff = datetime.now(timezone.utc)
plane = PointInTimeDataPlane.from_paths()
snapshot = plane.read_unified_as_of(cutoff)
report = SessionTimeIntelligenceEngine().assess(snapshot)
report["production_data_plane_status"] = snapshot.get("status")
report["production_coverage"] = {
    "registered_source_count": snapshot.get("registered_source_count"),
    "enabled_product_count": snapshot.get("enabled_product_count"),
    "quality_eligible_product_count": snapshot.get("quality_eligible_product_count"),
    "spot_archive_status": (snapshot.get("spot_market_archive") or {}).get("status"),
    "spot_archive_schema_version": (snapshot.get("spot_market_archive") or {}).get("schema_version"),
    "legacy_candle_count": (snapshot.get("spot_market_archive") or {}).get("legacy_candle_count"),
    "versioned_candle_count": (snapshot.get("spot_market_archive") or {}).get("versioned_candle_count"),
    "stream_count": len((snapshot.get("spot_market_archive") or {}).get("streams", [])),
    "eligible_stream_count": sum(s.get("eligible_for_analytics") is True for s in (snapshot.get("spot_market_archive") or {}).get("streams", [])),
}
report["calendar_event_input"] = "NOT_CONNECTED_TO_STRICT_UNIFIED_SNAPSHOT"
report["safety"] = {
    "network_requests": False,
    "database_mutated": False,
    "registry_mutated": False,
    "monitor_restarted": False,
    "risk_settings_changed": False,
    "orders_sent": False,
    "fusion_wiring_changed": False,
}
out = ROOT / "reports" / "phase41_session_time_intelligence_report.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({
    "report_path": str(out),
    "status": report["status"],
    "reason_codes": report.get("reason_codes"),
    "production_data_plane_status": report["production_data_plane_status"],
    "production_coverage": report["production_coverage"],
    "snapshot_sha256": report.get("snapshot_sha256"),
}, indent=2))

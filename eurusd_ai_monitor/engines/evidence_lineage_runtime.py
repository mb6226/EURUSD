from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from eurusd_ai_monitor.engines.evidence_lineage_engine import EvidenceLineageEngine


def build_evidence_lineage_payload(
    engine: EvidenceLineageEngine,
    *,
    evaluated_at_utc: datetime,
    broker_server: str,
    symbol: str,
    candle_inventory,
    sources,
) -> dict:
    """Publish a deterministic lineage report; failures degrade closed."""
    try:
        if not isinstance(engine, EvidenceLineageEngine):
            raise TypeError("engine must be EvidenceLineageEngine")
        report = engine.audit(
            evaluated_at_utc=evaluated_at_utc,
            broker_server=broker_server,
            symbol=symbol,
            candle_inventory=candle_inventory,
            sources=sources,
        )
        if not isinstance(report, Mapping):
            raise TypeError("lineage engine returned a non-mapping report")
        return dict(report)
    except Exception as exc:
        return {
            "status": "DEGRADED",
            "evaluated_at_utc": (
                evaluated_at_utc.isoformat()
                if isinstance(evaluated_at_utc, datetime)
                else None
            ),
            "broker_server": broker_server if isinstance(broker_server, str) else "",
            "symbol": symbol if isinstance(symbol, str) else "",
            "inventory": {"total_candles": 0, "m1_candles": 0, "m5_candles": 0},
            "reference_coverage": {
                "unique_references": 0, "resolved_references": 0,
                "missing_references": 0, "coverage_ratio": "0.000000",
            },
            "source_manifest": [],
            "reason_codes": [f"EVIDENCE_LINEAGE_ERROR:{type(exc).__name__}"],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

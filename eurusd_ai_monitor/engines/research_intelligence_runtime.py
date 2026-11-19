from __future__ import annotations

from datetime import datetime
from typing import Mapping


def build_research_intelligence_payload(
    engine,
    *,
    evaluated_at_utc: datetime,
    broker_server: str,
    symbol: str,
    sources: Mapping,
) -> dict:
    """Build the research report without allowing synthesis errors to escape runtime."""
    try:
        report = engine.build_report(
            evaluated_at_utc=evaluated_at_utc,
            broker_server=broker_server,
            symbol=symbol,
            sources=sources,
        )
        if not isinstance(report, dict):
            raise TypeError("Research intelligence engine returned a non-dict report")
        return report
    except Exception as exc:
        return {
            "status": "DEGRADED",
            "evaluated_at_utc": evaluated_at_utc.isoformat(),
            "broker_server": broker_server,
            "symbol": symbol,
            "reason_codes": [f"RESEARCH_INTELLIGENCE_ERROR:{type(exc).__name__}"],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

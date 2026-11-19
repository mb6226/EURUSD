from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


_CURRENT = (
    "fusion_assessment",
    "market_regime_intelligence",
    "price_action_lifecycle",
    "setup_assessment",
    "session_eligibility",
)
_HISTORICAL = (
    "setup_outcome_observation",
    "statistical_outcome_evaluation",
    "regime_conditioned_outcome_evaluation",
)


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utc(parsed, field)


class ResearchIntelligenceEngine:
    """Pure, deterministic synthesis of current-cycle and historical research outputs."""

    def __init__(self, *, max_current_age_seconds: int = 300) -> None:
        if isinstance(max_current_age_seconds, bool) or not isinstance(max_current_age_seconds, int):
            raise TypeError("max_current_age_seconds must be an integer")
        if max_current_age_seconds <= 0:
            raise ValueError("max_current_age_seconds must be positive")
        self._max_age = max_current_age_seconds

    def build_report(
        self,
        *,
        evaluated_at_utc: datetime,
        broker_server: str,
        symbol: str,
        sources: Mapping[str, Mapping],
    ) -> dict:
        evaluated = _utc(evaluated_at_utc, "evaluated_at_utc")
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be a non-empty string")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        if not isinstance(sources, Mapping):
            raise TypeError("sources must be a mapping")

        manifest = []
        reasons = []
        current_states = {}
        historical_states = {}
        missing_current = []
        blocked_current = []
        degraded = False
        partial = False

        for name in (*_CURRENT, *_HISTORICAL):
            entry = sources.get(name)
            if not isinstance(entry, Mapping):
                manifest.append({
                    "source": name, "class": "CURRENT" if name in _CURRENT else "HISTORICAL",
                    "status": "MISSING", "source_status": "MISSING",
                    "evaluated_at_utc": None, "reason_codes": [f"{name.upper()}_MISSING"],
                })
                reasons.append(f"{name.upper()}_MISSING")
                if name in _CURRENT:
                    missing_current.append(name)
                else:
                    partial = True
                continue

            payload = entry.get("payload")
            if not isinstance(payload, Mapping):
                payload = {}
                source_status = "MALFORMED"
                reason_codes = [f"{name.upper()}_PAYLOAD_INVALID"]
                degraded = True
            else:
                reason_codes = list(payload.get("reason_codes", ()))
                source_status = self._source_status(name, payload)
                source_broker = entry.get("broker_server")
                source_symbol = entry.get("symbol")
                if ((source_broker is not None and source_broker != broker_server)
                        or (source_symbol is not None and source_symbol != symbol)):
                    source_status = "IDENTITY_MISMATCH"
                    reason_codes.append(f"{name.upper()}_IDENTITY_MISMATCH")
                    degraded = True

            raw_time = entry.get("evaluated_at_utc")
            try:
                source_time = _parse_timestamp(raw_time, f"{name}.evaluated_at_utc")
                age = (evaluated - source_time).total_seconds()
                if age < 0:
                    raise ValueError("FUTURE_TIMESTAMP")
                if name in _CURRENT and age > self._max_age:
                    source_status = "STALE"
                    reason_codes.append(f"{name.upper()}_STALE")
                elif name in _HISTORICAL and age > self._max_age:
                    # Historical data may be old; only the report-generation time is freshness-gated.
                    source_status = "STALE_REPORT"
                    reason_codes.append(f"{name.upper()}_REPORT_STALE")
            except ValueError as exc:
                source_time = None
                source_status = "INVALID_TIME"
                reason_codes.append(
                    f"{name.upper()}_{'FUTURE_TIMESTAMP' if str(exc) == 'FUTURE_TIMESTAMP' else 'TIMESTAMP_INVALID'}"
                )
                degraded = True

            if source_status in {"DEGRADED", "MALFORMED", "IDENTITY_MISMATCH", "INVALID_TIME"}:
                degraded = True

            if name in _CURRENT:
                current_states[name] = self._compact_state(name, payload, source_status)
                if source_status in {"BLOCKED", "STALE", "INVALID_TIME", "MALFORMED", "DEGRADED", "UNAVAILABLE"}:
                    blocked_current.append(name)
                elif source_status in {"MISSING", "INCOMPLETE"}:
                    partial = True
            else:
                historical_states[name] = self._compact_state(name, payload, source_status)
                if source_status in {"MISSING", "BLOCKED", "UNAVAILABLE", "DEGRADED", "STALE_REPORT"}:
                    partial = True

            reasons.extend(str(code) for code in reason_codes if code)
            manifest.append({
                "source": name,
                "class": "CURRENT" if name in _CURRENT else "HISTORICAL",
                "status": source_status,
                "source_status": self._source_status(name, payload),
                "evaluated_at_utc": source_time.isoformat() if source_time else None,
                "reason_codes": sorted(set(str(code) for code in reason_codes if code)),
            })

        # Explicit gates are reported, never translated into directional evidence.
        fusion = current_states.get("fusion_assessment", {})
        if fusion.get("state") in {"BLOCKED", "CONFLICT"}:
            blocked_current.append("fusion_assessment")
        session = current_states.get("session_eligibility", {})
        if session.get("state") == "BLOCKED":
            blocked_current.append("session_eligibility")
        setup = current_states.get("setup_assessment", {})
        if setup.get("state") == "BLOCKED":
            blocked_current.append("setup_assessment")

        if degraded:
            status = "DEGRADED"
        elif blocked_current:
            status = "BLOCKED"
        elif missing_current:
            status = "PARTIAL"
        elif partial:
            status = "PARTIAL"
        else:
            status = "COHERENT"

        return {
            "status": status,
            "evaluated_at_utc": evaluated.isoformat(),
            "broker_server": broker_server,
            "symbol": symbol,
            "current_context": current_states,
            "historical_outcome_context": {
                "classification": "HISTORICAL_DESCRIPTIVE_ONLY",
                "sources": historical_states,
            },
            "source_manifest": manifest,
            "reason_codes": sorted(set(reasons)),
            "interpretation_limits": [
                "This report synthesizes specialist assessments; it does not create a directional signal.",
                "Historical MFE/MAE are descriptive price excursions, not realized trade returns.",
                "Historical outcome statistics cannot vote on direction or upgrade setup/session states.",
                "A coherent research cycle is not a trade-ready or execution-authorized state.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _source_status(name: str, payload: Mapping) -> str:
        raw = str(payload.get("status", "AVAILABLE")).upper()
        if name == "fusion_assessment":
            if raw in {"BLOCKED", "CONFLICT"}:
                return raw
            if raw == "INCOMPLETE":
                return "INCOMPLETE"
            return "AVAILABLE" if raw == "READY_FOR_RULES" else raw
        if name == "price_action_lifecycle":
            return "AVAILABLE" if raw in {"PROCESSED", "NO_LIFECYCLE"} else raw
        if name == "setup_assessment":
            stage = str(payload.get("stage", "UNKNOWN")).upper()
            return "BLOCKED" if stage == "BLOCKED" else "AVAILABLE"
        if name == "session_eligibility":
            if raw in {"BLOCKED", "OUTSIDE_SESSION"}:
                return "BLOCKED"
            if raw in {"WAIT_SETUP", "WAITING_FOR_SETUP"}:
                return "INCOMPLETE"
            return "AVAILABLE"
        if raw in {"DEGRADED", "UNAVAILABLE"}:
            return raw
        if name == "market_regime_intelligence" and str(payload.get("regime", "")).upper() == "UNKNOWN":
            return "INCOMPLETE"
        if name == "setup_outcome_observation":
            return "AVAILABLE" if raw in {
                "ACTIVE", "COMPLETED", "WAITING_FOR_SESSION_ELIGIBILITY", "RESEARCH_ELIGIBLE"
            } else raw
        if raw in {"DEGRADED", "UNAVAILABLE", "INSUFFICIENT_DATA"}:
            return raw
        return "AVAILABLE"

    @staticmethod
    def _compact_state(name: str, payload: Mapping, source_status: str) -> dict:
        if name == "fusion_assessment":
            state = payload.get("status", source_status)
        elif name == "setup_assessment":
            state = payload.get("stage", source_status)
        elif name == "price_action_lifecycle":
            state = payload.get("status", source_status)
        elif name == "market_regime_intelligence":
            state = payload.get("regime", "UNKNOWN")
        elif name == "session_eligibility":
            state = payload.get("status", source_status)
        else:
            state = payload.get("status", source_status)
        compact = {"state": str(state), "source_status": source_status}
        for field in ("directional_agreement", "directional_bias", "regime",
                      "volatility_state", "trend_direction", "lower_timeframe_alignment",
                      "lifecycle_state", "reason_code"):
            if field in payload:
                compact[field] = payload[field]
        if "reason_codes" in payload:
            compact["reason_codes"] = list(payload.get("reason_codes") or ())
        return compact

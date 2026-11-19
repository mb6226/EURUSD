from __future__ import annotations

from collections.abc import Mapping


RESEARCH_SOURCE_NAMES = (
    "fusion_assessment",
    "market_regime_intelligence",
    "price_action_lifecycle",
    "setup_assessment",
    "session_eligibility",
    "setup_outcome_observation",
    "statistical_outcome_evaluation",
    "regime_conditioned_outcome_evaluation",
)


def build_research_intelligence_sources(
    payloads: Mapping,
    *,
    broker_server: str,
    symbol: str,
) -> dict:
    """Attach cycle identity without inventing specialist timestamps.

    A specialist's explicit broker/symbol identity is preserved so the synthesis
    engine can detect cross-stream contamination. Components that do not publish
    their own identity inherit the identity of the runtime cycle that invoked them.
    Missing evaluation timestamps remain missing and are rejected by the engine.
    """
    if not isinstance(payloads, Mapping):
        raise TypeError("payloads must be a mapping")
    if not isinstance(broker_server, str) or not broker_server.strip():
        raise ValueError("broker_server must be a non-empty string")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol must be a non-empty string")

    sources = {}
    for name in RESEARCH_SOURCE_NAMES:
        payload = payloads.get(name)
        identity = payload if isinstance(payload, Mapping) else {}
        sources[name] = {
            "payload": payload,
            "broker_server": identity.get("broker_server", broker_server),
            "symbol": identity.get("symbol", symbol),
            # Do not substitute the cycle timestamp here. Missing source time is
            # a provenance defect and must fail closed in ResearchIntelligenceEngine.
            "evaluated_at_utc": identity.get("evaluated_at_utc"),
        }
    return sources

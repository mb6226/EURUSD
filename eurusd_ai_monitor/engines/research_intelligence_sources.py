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
    "quantitative_market_statistics",
    "macro_fundamentals_intelligence",
    "policy_rate_differential_intelligence",
    "intermarket_intelligence",
    "positioning_sentiment_intelligence",
    "liquidity_microstructure_intelligence",
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
        provenance = identity.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        source_broker = identity.get(
            "broker_server", provenance.get("broker_server", broker_server)
        )
        source_symbol = identity.get(
            "symbol", provenance.get("symbol", symbol)
        )
        # An explicitly published null identity is malformed, not an omission.
        if (("broker_server" in identity and source_broker is None)
                or ("broker_server" not in identity
                    and "broker_server" in provenance and source_broker is None)):
            source_broker = ""
        if (("symbol" in identity and source_symbol is None)
                or ("symbol" not in identity
                    and "symbol" in provenance and source_symbol is None)):
            source_symbol = ""
        sources[name] = {
            "payload": payload,
            "broker_server": source_broker,
            "symbol": source_symbol,
            # Do not substitute the cycle timestamp here. Missing source time is
            # a provenance defect and must fail closed in ResearchIntelligenceEngine.
            "evaluated_at_utc": identity.get("evaluated_at_utc"),
        }
    return sources

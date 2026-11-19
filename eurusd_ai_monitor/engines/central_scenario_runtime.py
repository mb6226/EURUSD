from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_central_scenario_payload(
    engine,
    *,
    evaluated_at_utc,
    broker_server: str,
    symbol: str,
    technical_analysis,
    price_action_lifecycle,
    market_regime_intelligence,
    fusion_assessment,
    specialist_reports: Mapping[str, Any],
    macro_calendar,
    news_intelligence,
    setup_assessment=None,
    session_eligibility=None,
    setup_outcome_observation=None,
    statistical_outcome_evaluation=None,
    regime_conditioned_outcome_evaluation=None,
) -> dict:
    """Bind one completed monitoring cycle to the central scenario engine."""
    if not isinstance(specialist_reports, Mapping):
        raise TypeError("specialist_reports must be a mapping")
    sources = {
        "technical_analysis": technical_analysis,
        "price_action_lifecycle": price_action_lifecycle,
        "market_regime_intelligence": market_regime_intelligence,
        "fusion_assessment": fusion_assessment,
        "macro_fundamentals_intelligence": specialist_reports.get(
            "macro_fundamentals_intelligence"
        ),
        "policy_rate_differential_intelligence": specialist_reports.get(
            "policy_rate_differential_intelligence"
        ),
        "intermarket_intelligence": specialist_reports.get("intermarket_intelligence"),
        "positioning_sentiment_intelligence": specialist_reports.get(
            "positioning_sentiment_intelligence"
        ),
        "quantitative_market_statistics": specialist_reports.get(
            "quantitative_market_statistics"
        ),
        "liquidity_microstructure_intelligence": specialist_reports.get(
            "liquidity_microstructure_intelligence"
        ),
        "macro_calendar": macro_calendar,
        "news_intelligence": news_intelligence,
        "setup_assessment": setup_assessment,
        "session_eligibility": session_eligibility,
        "setup_outcome_observation": setup_outcome_observation,
        "statistical_outcome_evaluation": statistical_outcome_evaluation,
        "regime_conditioned_outcome_evaluation": regime_conditioned_outcome_evaluation,
    }
    return engine.assess(
        evaluated_at_utc=evaluated_at_utc,
        broker_server=broker_server,
        symbol=symbol,
        sources=sources,
    )

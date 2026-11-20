from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _bind_pit_report(report, evaluated_at_utc):
    """Copy a PIT report and bind its own cutoff as its evidence timestamp."""
    if not isinstance(report, Mapping):
        return report
    bound = dict(report)
    cutoff = bound.get("as_of_utc")
    if isinstance(cutoff, str) and cutoff.strip():
        bound["evaluated_at_utc"] = cutoff
    elif "evaluated_at_utc" not in bound:
        bound["evaluated_at_utc"] = evaluated_at_utc.isoformat()
    return bound


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
    point_in_time_market_regime=None,
    point_in_time_quantitative_statistics=None,
    session_time_intelligence=None,
    cross_domain_relationship_intelligence=None,
    unified_historical_data_plane=None,
    unified_historical_snapshot=None,
) -> dict:
    """Bind one completed monitoring cycle to the central scenario engine."""
    if not isinstance(specialist_reports, Mapping):
        raise TypeError("specialist_reports must be a mapping")
    if unified_historical_snapshot is not None:
        explicit = (
            point_in_time_market_regime, point_in_time_quantitative_statistics,
            session_time_intelligence, cross_domain_relationship_intelligence,
            unified_historical_data_plane,
        )
        if any(item is not None for item in explicit):
            raise ValueError("provide unified_historical_snapshot or explicit PIT reports, not both")
        from eurusd_ai_monitor.engines.multidomain_market_regime_engine import MultiDomainMarketRegimeEngine
        from eurusd_ai_monitor.engines.point_in_time_quantitative_statistics_engine import PointInTimeQuantitativeStatisticsEngine
        from eurusd_ai_monitor.engines.session_time_intelligence_engine import SessionTimeIntelligenceEngine
        from eurusd_ai_monitor.engines.cross_domain_relationship_engine import CrossDomainRelationshipEngine
        point_in_time_market_regime = MultiDomainMarketRegimeEngine().assess(unified_historical_snapshot)
        point_in_time_quantitative_statistics = PointInTimeQuantitativeStatisticsEngine().assess(unified_historical_snapshot)
        session_time_intelligence = SessionTimeIntelligenceEngine().assess(unified_historical_snapshot)
        cross_domain_relationship_intelligence = CrossDomainRelationshipEngine().assess(unified_historical_snapshot)
        unified_historical_data_plane = {
            "report_type": unified_historical_snapshot.get("report_type", "MULTI_DOMAIN_POINT_IN_TIME_DATA_PLANE"),
            "status": unified_historical_snapshot.get("status", "UNKNOWN"),
            "as_of_utc": unified_historical_snapshot.get("as_of_utc"),
            "snapshot_sha256": unified_historical_snapshot.get("snapshot_sha256"),
            "registry_sha256": unified_historical_snapshot.get("registry_sha256"),
            "read_mode": unified_historical_snapshot.get("read_mode"),
            "quality_eligible_product_count": unified_historical_snapshot.get("quality_eligible_product_count"),
            "analytics_domain_count": len(unified_historical_snapshot.get("analytics_domains", {}))
                if isinstance(unified_historical_snapshot.get("analytics_domains"), Mapping) else 0,
        }
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
        "point_in_time_market_regime": _bind_pit_report(point_in_time_market_regime, evaluated_at_utc),
        "point_in_time_quantitative_statistics": _bind_pit_report(point_in_time_quantitative_statistics, evaluated_at_utc),
        "session_time_intelligence": _bind_pit_report(session_time_intelligence, evaluated_at_utc),
        "cross_domain_relationship_intelligence": _bind_pit_report(cross_domain_relationship_intelligence, evaluated_at_utc),
        "unified_historical_data_plane": _bind_pit_report(unified_historical_data_plane, evaluated_at_utc),
    }
    return engine.assess(
        evaluated_at_utc=evaluated_at_utc,
        broker_server=broker_server,
        symbol=symbol,
        sources=sources,
    )

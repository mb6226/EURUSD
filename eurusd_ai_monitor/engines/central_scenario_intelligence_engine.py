from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping


SCENARIO_ENGINE_VERSION = "1.1.0"

_DIRECTIONAL_SOURCES = (
    "technical_analysis",
    "price_action_lifecycle",
    "market_regime_intelligence",
)
_CONTEXT_SOURCES = (
    "fusion_assessment",
    "macro_fundamentals_intelligence",
    "policy_rate_differential_intelligence",
    "intermarket_intelligence",
    "positioning_sentiment_intelligence",
    "quantitative_market_statistics",
    "liquidity_microstructure_intelligence",
    "macro_calendar",
    "news_intelligence",
    "setup_assessment",
    "session_eligibility",
    "setup_outcome_observation",
    "statistical_outcome_evaluation",
    "regime_conditioned_outcome_evaluation",
    "point_in_time_market_regime",
    "point_in_time_quantitative_statistics",
    "session_time_intelligence",
    "cross_domain_relationship_intelligence",
    "unified_historical_data_plane",
)
_ALL_SOURCES = (*_DIRECTIONAL_SOURCES, *_CONTEXT_SOURCES)


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _timestamp(payload: Mapping) -> datetime | None:
    raw = payload.get("evaluated_at_utc")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _text(value: Any) -> str:
    return value.strip().upper() if isinstance(value, str) else ""


def _direction(value: Any) -> str:
    normalized = _text(value)
    return normalized if normalized in {"UP", "DOWN"} else "NEUTRAL"


def _refs(value: Any, *, limit: int = 40) -> list[str]:
    found: list[str] = []

    def visit(item: Any, key: str = "") -> None:
        if len(found) >= limit:
            return
        if isinstance(item, Mapping):
            for child_key, child in item.items():
                if child_key in {
                    "source_record_id", "payload_sha256", "candle_ids",
                    "candle_id", "evidence_candle_ids", "evidence_ids",
                }:
                    visit(child, child_key)
                else:
                    visit(child, child_key)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child, key)
        elif isinstance(item, str) and item.strip():
            found.append(item.strip())

    visit(value)
    return list(dict.fromkeys(found))[:limit]


class CentralScenarioIntelligenceEngine:
    """Point-in-time, explainable scenario synthesis; never a signal or probability model.

    Only technical structure, confirmed Price Action lifecycle and market-regime
    direction may describe EURUSD direction. Macro, policy, intermarket,
    positioning, quantitative, liquidity, calendar and news remain contextual.
    The price-derived inputs share underlying market data and are not independent
    votes; no numeric probability or calibrated confidence is emitted.
    """

    VERSION = SCENARIO_ENGINE_VERSION

    def __init__(self, *, max_report_age_seconds: int = 300) -> None:
        if isinstance(max_report_age_seconds, bool) or not isinstance(max_report_age_seconds, int):
            raise TypeError("max_report_age_seconds must be an integer")
        if max_report_age_seconds <= 0:
            raise ValueError("max_report_age_seconds must be positive")
        self.max_report_age_seconds = max_report_age_seconds

    def assess(
        self,
        *,
        evaluated_at_utc: datetime,
        broker_server: str,
        symbol: str,
        sources: Mapping[str, Mapping[str, Any] | None],
    ) -> dict[str, Any]:
        evaluated = _utc(evaluated_at_utc, "evaluated_at_utc")
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if not isinstance(sources, Mapping):
            raise TypeError("sources must be a mapping")

        ledger: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        directional: list[dict[str, Any]] = []
        for name in _ALL_SOURCES:
            payload = sources.get(name)
            if not isinstance(payload, Mapping):
                ledger[name] = {
                    "status": "MISSING", "evaluated_at_utc": None,
                    "reason_codes": [f"{name.upper()}_MISSING"],
                    "evidence_refs": [],
                }
                reasons.append(f"{name.upper()}_MISSING")
                continue
            source_time = _timestamp(payload)
            status = _text(payload.get("status", "AVAILABLE")) or "UNKNOWN"
            source_broker = payload.get("broker_server")
            source_symbol = payload.get("symbol")
            raw_reasons = payload.get("reason_codes") or ()
            if isinstance(raw_reasons, str):
                raw_reasons = (raw_reasons,)
            source_reasons = [
                str(item) for item in raw_reasons
                if isinstance(item, (str, int))
            ]
            authority_contracts = {
                "decision_authority": {"ASSESSMENT_ONLY", "CONTEXT_ONLY"},
                "trade_authority": {"NONE"},
                "order_execution": {"DISABLED"},
                "trade_execution": {"DISABLED"},
                "entry_eligibility": {"BLOCKED"},
                "decision": {"WAIT"},
            }
            authority_violations = [
                field for field, allowed in authority_contracts.items()
                if field in payload and _text(payload.get(field)) not in allowed
            ]
            if authority_violations:
                status = "AUTHORITY_VIOLATION"
                source_reasons.extend(
                    f"{name.upper()}_AUTHORITY_CONTRACT_VIOLATION:{field}"
                    for field in authority_violations
                )
            if (source_broker is not None and source_broker != broker_server) or (
                source_symbol is not None and source_symbol != symbol
            ):
                status = "IDENTITY_MISMATCH"
                source_reasons.append("SOURCE_IDENTITY_MISMATCH")
            elif source_time is None:
                status = "INVALID_TIME"
                source_reasons.append("SOURCE_EVALUATION_TIME_MISSING_OR_INVALID")
            else:
                age = (evaluated - source_time).total_seconds()
                if age < 0:
                    status = "INVALID_TIME"
                    source_reasons.append("SOURCE_EVALUATION_TIME_FROM_FUTURE")
                elif age > self.max_report_age_seconds:
                    status = "STALE"
                    source_reasons.append("SOURCE_REPORT_STALE")
            if name == "session_eligibility" and status in {
                "RESEARCH_ELIGIBLE", "OUTSIDE_SESSION", "WAIT_SETUP", "BLOCKED"
            }:
                normalized_status = "AVAILABLE"
            elif name == "setup_outcome_observation" and status in {
                "ACTIVE", "COMPLETED", "WAIT_SETUP",
                "WAITING_FOR_SESSION_ELIGIBILITY", "RESEARCH_ELIGIBLE", "BLOCKED"
            }:
                normalized_status = "AVAILABLE"
            elif status in {"NOT_CONFIGURED", "UNAVAILABLE", "INSUFFICIENT_DATA", "INSUFFICIENT_EVIDENCE", "BLOCKED", "SKIPPED"}:
                normalized_status = "INCOMPLETE"
            elif status in {"AVAILABLE", "ANALYZED", "PROCESSED", "NO_LIFECYCLE", "READY_FOR_RULES"}:
                normalized_status = "AVAILABLE"
            elif status in {"PARTIAL", "INCOMPLETE", "WAIT_SETUP", "WAITING_FOR_SETUP"}:
                normalized_status = "PARTIAL"
            else:
                normalized_status = status
            entry = {
                "status": normalized_status,
                "reported_status": status,
                "evaluated_at_utc": source_time.isoformat() if source_time else None,
                "reason_codes": sorted(set(source_reasons)),
                "evidence_refs": _refs(payload),
            }
            ledger[name] = entry
            reasons.extend(source_reasons)

            if name not in _DIRECTIONAL_SOURCES or normalized_status != "AVAILABLE":
                continue
            direction = "NEUTRAL"
            evidence_field = None
            if name == "technical_analysis":
                trend = payload.get("trend")
                if isinstance(trend, Mapping):
                    direction = _direction(trend.get("direction"))
                    evidence_field = "trend.direction"
                else:
                    direction = _direction(payload.get("trend_direction"))
                    evidence_field = "trend_direction"
            elif name == "price_action_lifecycle":
                lifecycle = payload.get("lifecycle_snapshot")
                if isinstance(lifecycle, Mapping):
                    lifecycle_state = _text(lifecycle.get("state"))
                    if lifecycle_state in {"CONFIRMED", "DEEPENING"}:
                        direction = _direction(lifecycle.get("trend_direction"))
                        evidence_field = "lifecycle_snapshot.trend_direction"
                elif _text(payload.get("lifecycle_state")) in {"CONFIRMED", "DEEPENING"}:
                    direction = _direction(payload.get("trend_direction"))
                    evidence_field = "trend_direction"
            elif name == "market_regime_intelligence":
                regime = _text(payload.get("regime"))
                if regime == "TRENDING":
                    direction = _direction(payload.get("trend_direction"))
                    evidence_field = "trend_direction"
                elif regime == "RANGING":
                    direction = "RANGE"
                    evidence_field = "regime"
            if direction != "NEUTRAL":
                directional.append({
                    "source": name,
                    "direction": direction,
                    "field": evidence_field,
                    "evaluated_at_utc": source_time.isoformat(),
                    "evidence_refs": entry["evidence_refs"],
                })

        up_sources = [item for item in directional if item["direction"] == "UP"]
        down_sources = [item for item in directional if item["direction"] == "DOWN"]
        range_sources = [item for item in directional if item["direction"] == "RANGE"]
        if up_sources and down_sources:
            direction_state = "CONFLICTED"
        elif (up_sources or down_sources) and range_sources:
            direction_state = "MIXED"
        elif up_sources:
            direction_state = "UP"
        elif down_sources:
            direction_state = "DOWN"
        elif range_sources:
            direction_state = "RANGE"
        else:
            direction_state = "UNRESOLVED"

        available_domains = sum(
            item["status"] == "AVAILABLE" for item in ledger.values()
        )
        partial_domains = sum(
            item["status"] == "PARTIAL" for item in ledger.values()
        )
        unavailable_domains = len(ledger) - available_domains - partial_domains
        coverage = (
            "BROAD" if available_domains >= 7
            else "MODERATE" if available_domains >= 4
            else "LIMITED" if available_domains or partial_domains
            else "SPARSE"
        )

        usable_sources = {
            name: (
                sources.get(name)
                if ledger[name]["status"] in {"AVAILABLE", "PARTIAL", "INCOMPLETE"}
                else None
            )
            for name in _ALL_SOURCES
        }
        context = self._context_summary(usable_sources)
        tensions = self._tensions(direction_state, context, directional)
        scenarios = self._scenarios(direction_state, directional, tensions)
        dependency_map = self._evidence_dependency_map(usable_sources)
        status = (
            "DEGRADED" if any(
                item["status"] in {
                    "INVALID_TIME", "IDENTITY_MISMATCH", "DEGRADED",
                    "AUTHORITY_VIOLATION",
                }
                for item in ledger.values()
            )
            else "CONFLICTED" if direction_state in {"CONFLICTED", "MIXED"}
            else "PARTIAL" if coverage in {"LIMITED", "SPARSE"} or partial_domains or unavailable_domains
            else "ASSESSMENT_ONLY"
        )
        return {
            "report_type": "CENTRAL_MULTI_DOMAIN_SCENARIO_INTELLIGENCE",
            "engine_version": self.VERSION,
            "status": status,
            "evaluated_at_utc": evaluated.isoformat(),
            "broker_server": broker_server,
            "symbol": symbol,
            "directional_assessment": {
                "state": direction_state,
                "supporting_price_structure_evidence": directional,
                "independence_warning": (
                    "Technical, Price Action and market-regime evidence share underlying broker price data; "
                    "they are consistency checks, not independent votes."
                ),
                "numeric_probability": None,
                "calibrated_confidence": None,
            },
            "scenario_hypotheses": scenarios,
            "cross_domain_context": context,
            "cross_domain_tensions": tensions,
            "evidence_dependency_map": dependency_map,
            "scenario_assessment_contract": {
                "scenario_type": "QUALITATIVE_CONDITIONAL_HYPOTHESES",
                "numeric_probability": None,
                "calibrated_confidence": None,
                "out_of_sample_validation": "NOT_ESTABLISHED",
                "context_only_sources_cast_directional_votes": False,
                "correlated_specialists_counted_as_independent": False,
                "scenario_invalidation_required": True,
            },
            "evidence_coverage": {
                "state": coverage,
                "available_domain_count": available_domains,
                "partial_domain_count": partial_domains,
                "missing_or_unavailable_domain_count": unavailable_domains,
                "domains": ledger,
            },
            "reason_codes": sorted(set(reasons)),
            "interpretation_limits": [
                "Scenario labels are qualitative hypotheses, not calibrated probabilities or forecasts.",
                "Only technical structure, confirmed Price Action lifecycle and market-regime state describe EURUSD direction.",
                "Macro, policy, intermarket, positioning, quantitative, liquidity, calendar and news are contextual and do not cast directional votes.",
                "Intermarket correlations are descriptive, not causal or predictive.",
                "CFTC EURO FX futures positioning is a proxy, not total EUR spot positioning.",
                "Historical MFE/MAE and outcome statistics are not realized returns and cannot vote on direction.",
                "No entry, exit, target, stop, position size, risk instruction or trade eligibility is produced.",
                "Missing, stale, future-dated, identity-mismatched and partial evidence remains visible and is not imputed.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _context_summary(sources: Mapping[str, Any]) -> dict[str, Any]:
        def payload(name: str) -> Mapping:
            value = sources.get(name)
            return value if isinstance(value, Mapping) else {}

        macro = payload("macro_fundamentals_intelligence")
        inflation = macro.get("inflation") if isinstance(macro.get("inflation"), Mapping) else {}
        unemployment = macro.get("unemployment") if isinstance(macro.get("unemployment"), Mapping) else {}
        policy = payload("policy_rate_differential_intelligence")
        spread = policy.get("usd_minus_eur_spread") if isinstance(policy.get("usd_minus_eur_spread"), Mapping) else {}
        policy_context = "UNAVAILABLE"
        try:
            low, high = float(spread["low"]), float(spread["high"])
            if not isfinite(low) or not isfinite(high):
                raise ValueError("policy spread must be finite")
            policy_context = (
                "USD_POLICY_RATE_PREMIUM" if low > 0
                else "EUR_POLICY_RATE_PREMIUM" if high < 0
                else "POLICY_RATE_SPREAD_CROSSES_ZERO"
            )
        except (KeyError, TypeError, ValueError):
            low = high = None

        positioning = payload("positioning_sentiment_intelligence")
        groups = positioning.get("groups") if isinstance(positioning.get("groups"), Mapping) else {}
        position_context = {}
        for name, item in groups.items():
            if not isinstance(item, Mapping):
                continue
            position_context[str(name)] = {
                "status": item.get("status"),
                "interpretation": item.get("interpretation"),
                "net_position_pct_open_interest": item.get("net_position_pct_open_interest"),
                "historical_percentile": item.get("historical_percentile"),
                "proxy": "CME_EURO_FX_FUTURES",
            }

        intermarket = payload("intermarket_intelligence")
        drivers = intermarket.get("drivers") if isinstance(intermarket.get("drivers"), Mapping) else {}
        intermarket_context = {}
        for name, item in drivers.items():
            if isinstance(item, Mapping):
                intermarket_context[str(name)] = {
                    "status": item.get("status"),
                    "contemporaneous_correlation": item.get("contemporaneous_correlation"),
                    "aligned_return_count": item.get("aligned_return_count"),
                    "sample_end_utc": item.get("sample_end_utc"),
                    "interpretation": "DESCRIPTIVE_CORRELATION_ONLY",
                }

        quant = payload("quantitative_market_statistics")
        quant_frames = quant.get("timeframes") if isinstance(quant.get("timeframes"), Mapping) else {}
        quant_context = {}
        for timeframe, item in quant_frames.items():
            if isinstance(item, Mapping):
                quant_context[str(timeframe)] = {
                    "directional_efficiency_ratio": item.get("directional_efficiency_ratio"),
                    "return_distribution_pips": item.get("return_distribution_pips"),
                    "true_range_pips": item.get("true_range_pips"),
                    "window_end_utc": item.get("window_end_utc"),
                }

        liquidity = payload("liquidity_microstructure_intelligence")
        liquidity_frames = liquidity.get("timeframes") if isinstance(liquidity.get("timeframes"), Mapping) else {}
        liquidity_context = {}
        for timeframe, item in liquidity_frames.items():
            if isinstance(item, Mapping):
                liquidity_context[str(timeframe)] = {
                    "status": item.get("status"),
                    "spread": item.get("spread"),
                    "tick_activity": item.get("tick_activity"),
                    "price_range": item.get("price_range"),
                    "age_seconds": item.get("age_seconds"),
                }

        calendar = payload("macro_calendar")
        news = payload("news_intelligence")
        setup = payload("setup_assessment")
        session = payload("session_eligibility")
        historical = {
            name: {
                "status": payload(name).get("status", "MISSING"),
                "report_type": payload(name).get("report_type"),
                "classification": "HISTORICAL_DESCRIPTIVE_ONLY",
                "directional_vote": False,
            }
            for name in (
                "setup_outcome_observation",
                "statistical_outcome_evaluation",
                "regime_conditioned_outcome_evaluation",
            )
        }
        return {
            "macro_fundamentals": {
                "status": macro.get("status", "MISSING"),
                "inflation": {
                    "status": inflation.get("status"),
                    "us_minus_euro_area_inflation_pp": inflation.get("us_minus_euro_area_inflation_pp"),
                    "reference_month": inflation.get("reference_month"),
                    "interpretation": "QUALIFIED_INFLATION_COMPARISON_NOT_A_CURRENCY_VOTE",
                },
                "unemployment": {
                    "status": unemployment.get("status"),
                    "us_minus_euro_area_unemployment_pp": unemployment.get("us_minus_euro_area_unemployment_pp"),
                    "reference_month": unemployment.get("reference_month"),
                    "interpretation": "DIFFERING_STATISTICAL_DEFINITIONS_CONTEXT_ONLY",
                },
            },
            "policy_rates": {
                "status": policy.get("status", "MISSING"),
                "usd_minus_eur_spread": {"low": spread.get("low"), "high": spread.get("high")},
                "context": policy_context,
                "directional_vote": False,
            },
            "intermarket": {
                "status": intermarket.get("status", "MISSING"),
                "drivers": intermarket_context,
                "directional_vote": False,
            },
            "positioning": {
                "status": positioning.get("status", "MISSING"),
                "groups": position_context,
                "directional_vote": False,
            },
            "quantitative": {
                "status": quant.get("status", "MISSING"),
                "timeframes": quant_context,
                "directional_vote": False,
            },
            "liquidity": {
                "status": liquidity.get("status", "MISSING"),
                "timeframes": liquidity_context,
                "directional_vote": False,
            },
            "event_risk": {
                "calendar_status": calendar.get("status", "MISSING"),
                "high_impact_event_count": calendar.get("high_impact_count"),
                "upcoming_event_count": calendar.get("event_count", calendar.get("upcoming_event_count")),
                "news_status": news.get("status", "MISSING"),
                "news_article_count": news.get("article_count"),
                "directional_vote": False,
            },
            "operational_gates": {
                "setup_stage": setup.get("stage", setup.get("status", "MISSING")),
                "session_status": session.get("status", "MISSING"),
                "directional_vote": False,
                "execution_authority": False,
            },
            "historical_research": historical,
            "point_in_time_market_regime": {
                "status": payload("point_in_time_market_regime").get("status", "MISSING"),
                "market_regime": payload("point_in_time_market_regime").get("market_regime", "UNKNOWN"),
                "volatility_state": payload("point_in_time_market_regime").get("volatility_state", "UNKNOWN"),
                "domain_coverage": payload("point_in_time_market_regime").get("domain_coverage", {}),
                "directional_vote": False,
                "reason_codes": payload("point_in_time_market_regime").get("reason_codes", []),
            },
            "point_in_time_quantitative_statistics": {
                "status": payload("point_in_time_quantitative_statistics").get("status", "MISSING"),
                "timeframes": payload("point_in_time_quantitative_statistics").get("timeframes", {}),
                "excluded_timeframes": payload("point_in_time_quantitative_statistics").get("excluded_timeframes", {}),
                "directional_vote": False,
            },
            "session_time": {
                "status": payload("session_time_intelligence").get("status", "MISSING"),
                "active_reference_sessions": payload("session_time_intelligence").get("active_reference_sessions", []),
                "london_new_york_overlap_active": payload("session_time_intelligence").get("london_new_york_overlap_active"),
                "historical_session_coverage": payload("session_time_intelligence").get("historical_session_coverage", {}),
                "excluded_timeframes": payload("session_time_intelligence").get("excluded_timeframes", {}),
                "directional_vote": False,
            },
            "cross_domain_relationships": {
                "status": payload("cross_domain_relationship_intelligence").get("status", "MISSING"),
                "relationship_count": payload("cross_domain_relationship_intelligence").get("relationship_count", 0),
                "available_relationship_count": payload("cross_domain_relationship_intelligence").get("available_relationship_count", 0),
                "relationships": payload("cross_domain_relationship_intelligence").get("relationships", []),
                "directional_vote": False,
                "interpretation": "DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL_OR_PREDICTIVE",
            },
            "unified_data_plane": {
                "status": payload("unified_historical_data_plane").get("status", "MISSING"),
                "snapshot_sha256": payload("unified_historical_data_plane").get("snapshot_sha256"),
                "read_mode": payload("unified_historical_data_plane").get("read_mode"),
                "quality_eligible_product_count": payload("unified_historical_data_plane").get("quality_eligible_product_count"),
                "analytics_domain_count": payload("unified_historical_data_plane").get("analytics_domain_count"),
                "directional_vote": False,
            },
        }

    @staticmethod
    def _evidence_dependency_map(sources: Mapping[str, Any]) -> dict[str, Any]:
        """Declare shared-data dependencies so repeated views are never independent votes."""
        groups = {
            "EURUSD_BROKER_PRICE_LINEAGE": [
                "technical_analysis", "price_action_lifecycle", "market_regime_intelligence",
                "point_in_time_market_regime", "point_in_time_quantitative_statistics",
                "session_time_intelligence", "liquidity_microstructure_intelligence",
            ],
            "CFTC_EURO_FX_POSITIONING_LINEAGE": ["positioning_sentiment_intelligence"],
            "INTERMARKET_DRIVER_LINEAGE": ["intermarket_intelligence"],
            "CROSS_DOMAIN_RELATIONSHIP_DERIVED_LINEAGE": ["cross_domain_relationship_intelligence"],
            "MACRO_RELEASE_AND_POLICY_LINEAGE": [
                "macro_fundamentals_intelligence", "policy_rate_differential_intelligence", "macro_calendar"
            ],
            "NEWS_SOURCE_LINEAGE": ["news_intelligence"],
            "HISTORICAL_OUTCOME_RESEARCH_LINEAGE": [
                "setup_outcome_observation", "statistical_outcome_evaluation", "regime_conditioned_outcome_evaluation"
            ],
        }
        active = {}
        for group, members in groups.items():
            present = [name for name in members if isinstance(sources.get(name), Mapping)]
            active[group] = {
                "members_present": present,
                "member_count": len(present),
                "independent_votes": 0,
                "shared_lineage_warning": len(present) > 1 or group == "CROSS_DOMAIN_RELATIONSHIP_DERIVED_LINEAGE" and bool(present),
                "derived_from_domains": (["spot_fx", "macro_fundamentals", "monetary_policy", "intermarket", "positioning_sentiment"] if group == "CROSS_DOMAIN_RELATIONSHIP_DERIVED_LINEAGE" and present else []),
            }
        return {
            "groups": active,
            "policy": "MULTIPLE_SPECIALISTS_OR_FEATURES_WITH_SHARED_UNDERLYING_DATA_ARE_NOT_INDEPENDENT_CONFIRMATIONS",
            "cross_domain_relationships_are_not_causal_proof": True,
            "context_sources_cast_directional_votes": False,
        }

    @staticmethod
    def _tensions(
        direction: str, context: Mapping[str, Any], directional: list[dict]
    ) -> list[dict[str, str]]:
        result = []
        has_range = any(item["direction"] == "RANGE" for item in directional)
        has_trend = any(item["direction"] in {"UP", "DOWN"} for item in directional)
        if has_range and has_trend:
            result.append({
                "type": "PRICE_STRUCTURE_REGIME_TENSION",
                "description": "Directional price structure and a ranging market-regime assessment are both present.",
                "qualification": "This may represent a transition; the engine does not force a directional or range conclusion.",
            })
        policy = context.get("policy_rates", {})
        policy_context = policy.get("context") if isinstance(policy, Mapping) else None
        if direction == "UP" and policy_context == "USD_POLICY_RATE_PREMIUM":
            result.append({
                "type": "PRICE_POLICY_CONTEXT_TENSION",
                "description": "EURUSD price structure is UP while the observed policy-rate spread is USD-positive.",
                "qualification": "Contextual tension only; the policy spread is not a market-implied path or directional vote.",
            })
        elif direction == "DOWN" and policy_context == "EUR_POLICY_RATE_PREMIUM":
            result.append({
                "type": "PRICE_POLICY_CONTEXT_TENSION",
                "description": "EURUSD price structure is DOWN while the observed policy-rate spread is EUR-positive.",
                "qualification": "Contextual tension only; the policy spread is not a market-implied path or directional vote.",
            })
        return result

    @staticmethod
    def _scenarios(direction: str, evidence: list[dict], tensions: list[dict]) -> list[dict[str, Any]]:
        up = [item for item in evidence if item["direction"] == "UP"]
        down = [item for item in evidence if item["direction"] == "DOWN"]
        ranges = [item for item in evidence if item["direction"] == "RANGE"]
        def refs(items):
            return [f"{item['source']}:{item['field']}" for item in items]
        if direction == "UP":
            up_status, down_status, range_status = "LEADING_HYPOTHESIS", "ALTERNATIVE", "NOT_ESTABLISHED"
        elif direction == "DOWN":
            up_status, down_status, range_status = "ALTERNATIVE", "LEADING_HYPOTHESIS", "NOT_ESTABLISHED"
        elif direction == "RANGE":
            up_status, down_status, range_status = "UNRESOLVED", "UNRESOLVED", "LEADING_HYPOTHESIS"
        elif direction in {"CONFLICTED", "MIXED"}:
            up_status = down_status = range_status = "UNRESOLVED_CONFLICT"
        else:
            up_status = down_status = range_status = "UNRESOLVED"
        return [
            {
                "scenario_id": "EURUSD_UP_CONTINUATION",
                "status": up_status,
                "supporting_evidence": refs(up),
                "opposing_evidence": refs(down),
                "context_tensions": [item["type"] for item in tensions],
                "reassessment_conditions": [
                    "A confirmed downside structural break would weaken this hypothesis.",
                    "A loss of confirmed upward structure or material evidence degradation requires reassessment.",
                ],
            },
            {
                "scenario_id": "EURUSD_DOWN_CONTINUATION",
                "status": down_status,
                "supporting_evidence": refs(down),
                "opposing_evidence": refs(up),
                "context_tensions": [item["type"] for item in tensions],
                "reassessment_conditions": [
                    "A confirmed upside structural break would weaken this hypothesis.",
                    "A loss of confirmed downward structure or material evidence degradation requires reassessment.",
                ],
            },
            {
                "scenario_id": "RANGE_OR_TRANSITION",
                "status": range_status,
                "supporting_evidence": refs(ranges),
                "opposing_evidence": refs(up + down),
                "context_tensions": [],
                "reassessment_conditions": [
                    "A confirmed directional structure and a non-ranging regime would weaken this hypothesis.",
                    "Insufficient or contradictory evidence leaves this hypothesis unresolved rather than confirmed.",
                ],
            },
        ]

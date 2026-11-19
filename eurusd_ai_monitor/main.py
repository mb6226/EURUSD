from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from threading import Lock, Thread
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eurusd_ai_monitor.engines.mt5_engine import MT5Connector
from eurusd_ai_monitor.engines.price_action_engine import summarize_structure
from eurusd_ai_monitor.engines.vision_engine import inspect_screenshot
from eurusd_ai_monitor.engines.decision_engine import evaluate
from eurusd_ai_monitor.engines.fusion_engine import (
    EvidenceDirection, EvidenceStatus, FusionEngine, SpecialistEvidence,
)
from eurusd_ai_monitor.engines.market_context_builder import MarketContextBuilder
from eurusd_ai_monitor.engines.price_action_coordinator import PriceActionCoordinator
from eurusd_ai_monitor.engines.price_action_runtime import PriceActionRuntime
from eurusd_ai_monitor.engines.lifecycle_recovery_manager import LifecycleRecoveryManager
from eurusd_ai_monitor.engines.calendar_engine import MacroCalendarEngine
from eurusd_ai_monitor.engines.news_engine import NewsEngine
from eurusd_ai_monitor.engines.technical_engine import TechnicalEngine
from eurusd_ai_monitor.engines.setup_pattern_engine import SetupPatternEngine
from eurusd_ai_monitor.engines.session_eligibility_engine import (
    SessionEligibilityRiskGate, SessionRiskStore,
)
from eurusd_ai_monitor.engines.setup_outcome_tracker import (
    ObservationStore, SetupOutcomeTracker,
)
from eurusd_ai_monitor.engines.statistical_outcome_evaluator import (
    StatisticalOutcomeEvaluator,
)
from eurusd_ai_monitor.engines.regime_conditioned_outcome_evaluator import (
    RegimeConditionedOutcomeEvaluator,
)
from eurusd_ai_monitor.engines.market_regime_engine import MarketRegimeEngine
from eurusd_ai_monitor.engines.research_intelligence_engine import ResearchIntelligenceEngine
from eurusd_ai_monitor.engines.research_intelligence_runtime import build_research_intelligence_payload
from eurusd_ai_monitor.engines.research_intelligence_sources import build_research_intelligence_sources
from eurusd_ai_monitor.strategy_config import load_strategy_config
from eurusd_ai_monitor.storage.market_data_store import MarketDataStore
from eurusd_ai_monitor.storage.lifecycle_store import LifecycleStore
from eurusd_ai_monitor.storage.macro_calendar_store import MacroCalendarStore
from eurusd_ai_monitor.storage.news_store import NewsStore
from eurusd_ai_monitor.storage.mt5_market_adapter import MT5MarketDataAdapter
from eurusd_ai_monitor.alerts.signal_manager import SignalManager


def _candles_frame(candles) -> pd.DataFrame:
    """Convert typed stored candles to the legacy analysis frame without mutating them."""
    return pd.DataFrame([
        {
            "time": candle.candle_open_time_utc,
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "tick_volume": candle.tick_volume,
            "spread": candle.spread,
            "real_volume": candle.real_volume,
        }
        for candle in candles
    ])


def _quality_payload(quality) -> dict:
    return {
        "is_valid": quality.is_valid,
        "issues": list(quality.issues),
        "warnings": list(quality.warnings),
        "last_candle_time": (
            quality.last_candle_time.isoformat() if quality.last_candle_time else None
        ),
        "data_age_seconds": quality.data_age_seconds,
        "missing_timeframes": list(quality.missing_timeframes),
        "candle_counts": dict(quality.candle_counts or {}),
        "timeframe_last_candle_times": {
            tf: value.isoformat() if value else None
            for tf, value in (quality.timeframe_last_candle_times or {}).items()
        },
    }


def _evidence_payload(evidence) -> dict:
    candle = evidence.candle
    return {
        "candle_id": evidence.candle_id,
        "role": evidence.role.value,
        "confirmed_at_utc": evidence.confirmed_at_utc.isoformat(),
        "algorithm_version": evidence.algorithm_version,
        "parameter_version": evidence.parameter_version,
        "supporting_candle_ids": list(evidence.supporting_candle_ids),
        "candle": {
            "timeframe": candle.timeframe,
            "open_time_utc": candle.candle_open_time_utc.isoformat(),
            "open": str(candle.open),
            "high": str(candle.high),
            "low": str(candle.low),
            "close": str(candle.close),
        },
    }


def _technical_structure_payload(structure) -> dict:
    trend = structure.trend
    swing_break = structure.protected_swing_break
    return {
        "status": "ANALYZED",
        "evaluated_at_utc": structure.evaluated_at_utc.isoformat(),
        "algorithm_version": structure.algorithm_version,
        "parameter_version": structure.parameter_version,
        "trend": {
            "direction": trend.direction.value,
            "confirmed_at_utc": trend.confirmed_at_utc.isoformat(),
            "swing_highs": [_evidence_payload(ref) for ref in trend.swing_highs],
            "swing_lows": [_evidence_payload(ref) for ref in trend.swing_lows],
            "protected_swing": (
                _evidence_payload(trend.protected_swing)
                if trend.protected_swing is not None
                else None
            ),
        },
        "pivots": [
            {
                "kind": pivot.kind.value,
                "price": str(pivot.price),
                "evidence": _evidence_payload(pivot.evidence),
            }
            for pivot in structure.pivots
        ],
        "structure_time_utc": (
            structure.structure_time_utc.isoformat()
            if structure.structure_time_utc
            else None
        ),
        "protected_swing_break": (
            {
                "broken_direction": swing_break.broken_direction.value,
                "protected_swing": _evidence_payload(swing_break.protected_swing),
                "structure_time_utc": swing_break.structure_time_utc.isoformat(),
                "break_candle_open_time_utc": swing_break.break_candle.candle_open_time_utc.isoformat(),
                "break_close": str(swing_break.break_candle.close),
                "confirmed_at_utc": swing_break.confirmed_at_utc.isoformat(),
            }
            if swing_break is not None
            else None
        ),
    }


def _price_action_runtime_payload(result, recovery_details: dict) -> dict:
    structure = result.technical_structure
    transition = result.transition
    lifecycle = transition.lifecycle if transition is not None else None
    lifecycle_payload = None
    if lifecycle is not None:
        lifecycle_payload = {
            "lifecycle_id": lifecycle.lifecycle_id,
            "state": lifecycle.state.value,
            "trend_direction": lifecycle.trend_direction.value,
            "impulse": {
                "direction": lifecycle.impulse.direction.value,
                "start_price": str(lifecycle.impulse.start_price),
                "end_price": str(lifecycle.impulse.end_price),
                "size_pips": str(lifecycle.impulse.size_pips),
                "started_at_utc": lifecycle.impulse.started_at_utc.isoformat(),
                "ended_at_utc": lifecycle.impulse.ended_at_utc.isoformat(),
                "confirmed_at_utc": lifecycle.impulse.confirmed_at_utc.isoformat(),
            },
            "depth_pips": str(lifecycle.depth_pips),
            "retracement_ratio": str(lifecycle.retracement_ratio),
            "age_bars": lifecycle.age_bars,
            "last_processed_m5_utc": lifecycle.last_processed_m5_utc.isoformat(),
            "confirmed_at_utc": (
                lifecycle.confirmed_at_utc.isoformat()
                if lifecycle.confirmed_at_utc is not None else None
            ),
            "warnings": [warning.value for warning in lifecycle.warnings],
            "algorithm_version": lifecycle.algorithm_version,
            "parameter_version": lifecycle.parameter_version,
            "evidence_candle_ids": [
                lifecycle.impulse.start_pivot.candle_id,
                lifecycle.impulse.end_pivot.candle_id,
                lifecycle.candidate_start_evidence.candle_id,
                lifecycle.extreme_evidence.candle_id,
                *[ref.candle_id for ref in lifecycle.correction_pivots],
            ],
        }
    return {
        "status": result.status.value,
        "broker_server": result.broker_server,
        "evaluated_at_utc": result.evaluated_at_utc.isoformat(),
        "technical_structure": (
            _technical_structure_payload(structure) if structure is not None else None
        ),
        "transition_type": (
            transition.transition_type.value if transition is not None else None
        ),
        "lifecycle_id": result.lifecycle_id,
        "lifecycle_snapshot": lifecycle_payload,
        "lifecycle_state": (
            result.lifecycle_state.value if result.lifecycle_state is not None else None
        ),
        "persistence_status": (
            result.persistence_status.value
            if result.persistence_status is not None else None
        ),
        "recovery": recovery_details,
        "revision_watermark": result.revision_watermark,
        "record_version": result.record_version,
        "state_version": result.state_version,
        "reason_codes": list(result.reason_codes),
        "trade_authority": result.trade_authority,
    }


def _fusion_evidence(
    specialist: str,
    payload: dict,
    *,
    direction: EvidenceDirection = EvidenceDirection.NEUTRAL,
    evidence_ids: tuple[str, ...] = (),
    context_flags: tuple[str, ...] = (),
) -> SpecialistEvidence:
    raw_status = str(payload.get("status", "UNAVAILABLE")).upper()
    status_map = {
        "ANALYZED": EvidenceStatus.AVAILABLE,
        "AVAILABLE": EvidenceStatus.AVAILABLE,
        "ACTIVE": EvidenceStatus.AVAILABLE,
        "DEGRADED": EvidenceStatus.DEGRADED,
        "STALE": EvidenceStatus.DEGRADED,
        "UNAVAILABLE": EvidenceStatus.UNAVAILABLE,
        "NOT_CONFIGURED": EvidenceStatus.UNAVAILABLE,
        "NOT_CONNECTED": EvidenceStatus.UNAVAILABLE,
        "FAILED": EvidenceStatus.UNAVAILABLE,
    }
    status = status_map.get(raw_status, EvidenceStatus.UNAVAILABLE)
    raw_time = payload.get("evaluated_at_utc")
    if not raw_time:
        status = EvidenceStatus.UNAVAILABLE
        raw_time = datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
    evaluated_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    sources = payload.get("source_states", ())
    if isinstance(sources, dict):
        source_ids = tuple(sorted(sources))
    elif isinstance(sources, list):
        source_ids = tuple(sorted(
            str(item.get("source_id")) for item in sources
            if isinstance(item, dict) and item.get("source_id")
        ))
    else:
        source_ids = ()
    if not source_ids and payload.get("source_id"):
        source_ids = (str(payload["source_id"]),)
    raw_reasons = payload.get("reason_codes", ())
    if not raw_reasons and payload.get("reason_code"):
        raw_reasons = (payload["reason_code"],)
    reasons = tuple(str(value) for value in raw_reasons if value)
    normalized_direction = (
        direction if specialist in {"macro_calendar", "news"}
        else (direction if status is EvidenceStatus.AVAILABLE else EvidenceDirection.UNKNOWN)
    )
    return SpecialistEvidence(
        specialist=specialist,
        status=status,
        direction=normalized_direction,
        evaluated_at_utc=evaluated_at,
        source_ids=source_ids,
        evidence_ids=evidence_ids,
        reason_codes=reasons,
        context_flags=context_flags,
    )


def _build_fusion_assessment(
    fusion_engine: FusionEngine,
    snapshot,
    technical_analysis: dict | None,
    technical_error: str | None,
    price_action_payload: dict,
    macro_calendar_payload: dict,
    news_payload: dict,
):
    technical_payload = technical_analysis or {
        "status": "UNAVAILABLE",
        "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
        "reason_codes": ("TECHNICAL_ANALYSIS_UNAVAILABLE",),
    }
    technical_payload.setdefault("source_id", snapshot.broker_server)
    trend = technical_payload.get("trend", {})
    trend_direction = trend.get("direction", "UNKNOWN") if isinstance(trend, dict) else "UNKNOWN"
    technical_vote = {
        "UP": EvidenceDirection.UP,
        "DOWN": EvidenceDirection.DOWN,
        "RANGE": EvidenceDirection.NEUTRAL,
        "UNKNOWN": EvidenceDirection.NEUTRAL,
    }.get(trend_direction, EvidenceDirection.NEUTRAL)
    if technical_error:
        technical_payload = dict(technical_payload)
        technical_payload["status"] = "UNAVAILABLE"
        technical_payload["reason_codes"] = ("TECHNICAL_ANALYSIS_FAILED",)

    lifecycle = price_action_payload.get("lifecycle_snapshot") or {}
    lifecycle_state = lifecycle.get("state")
    lifecycle_direction = lifecycle.get("trend_direction")
    if (
        price_action_payload.get("status") == "PROCESSED"
        and lifecycle_state in {"CONFIRMED", "DEEPENING"}
    ):
        pa_status = "AVAILABLE"
        pa_direction = {
            "UP": EvidenceDirection.UP,
            "DOWN": EvidenceDirection.DOWN,
        }.get(lifecycle_direction, EvidenceDirection.UNKNOWN)
    else:
        pa_status = "UNAVAILABLE"
        pa_direction = EvidenceDirection.UNKNOWN
    pa_payload = {
        "status": pa_status,
        "source_id": price_action_payload.get("broker_server", snapshot.broker_server),
        "evaluated_at_utc": price_action_payload.get(
            "evaluated_at_utc", snapshot.timestamp_utc.isoformat()
        ),
        "reason_codes": list(price_action_payload.get("reason_codes", ())),
    }
    pa_evidence_ids = tuple(
        str(value) for value in lifecycle.get("evidence_candle_ids", ()) if value
    )

    high_impact = int(macro_calendar_payload.get("high_impact_count", 0) or 0)
    macro_flags = ("HIGH_IMPACT_EVENT_IN_HORIZON",) if high_impact > 0 else ()
    news_count = int(news_payload.get("article_count", 0) or 0)
    news_flags = ("OFFICIAL_NEWS_ITEMS_PRESENT",) if news_count > 0 else ()
    technical_evidence_ids = tuple(
        str(item.get("candle_id"))
        for key in ("swing_highs", "swing_lows")
        for item in (trend.get(key, []) or [])
        if isinstance(item, dict) and item.get("candle_id")
    )

    evidence = (
        _fusion_evidence(
            "technical", technical_payload, direction=technical_vote,
            evidence_ids=technical_evidence_ids,
        ),
        _fusion_evidence(
            "price_action", pa_payload, direction=pa_direction,
            evidence_ids=pa_evidence_ids,
        ),
        _fusion_evidence(
            "macro_calendar", macro_calendar_payload,
            context_flags=macro_flags,
        ),
        _fusion_evidence(
            "news", news_payload,
            context_flags=news_flags,
        ),
    )
    return fusion_engine.assess(snapshot.timestamp_utc, evidence)


def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    data_dir = ROOT / "data" / "market"
    data_dir.mkdir(parents=True, exist_ok=True)
    connector = MT5Connector(config["symbol"])
    market_store = MarketDataStore()
    market_adapter = MT5MarketDataAdapter(connector, market_store)
    context_builder = MarketContextBuilder(
        connector,
        market_store,
        market_adapter,
        minimum_candles=config.get("context_minimum_candles", 3),
        max_age_seconds=config.get("context_max_age_seconds", {"M1": 180, "M5": 900}),
    )
    signals = SignalManager(ROOT / "logs")
    strategy_config = load_strategy_config()
    technical_engine = TechnicalEngine(strategy_config)
    fusion_engine = FusionEngine(max_evidence_age_seconds=300)
    setup_pattern_engine = SetupPatternEngine(strategy_config)
    risk_config = config["risk"]
    session_risk_gate = SessionEligibilityRiskGate(
        SessionRiskStore(data_dir / "session_risk.sqlite3"),
        stop_loss_pips=Decimal(str(risk_config["stop_loss_pips"])),
        take_profit_pips=Decimal(str(risk_config["take_profit_pips"])),
        max_daily_risk_pips=Decimal(str(risk_config["max_daily_risk_pips"])),
    )
    observation_db_path = data_dir / "setup_observations.sqlite3"
    setup_outcome_tracker = SetupOutcomeTracker(
        ObservationStore(observation_db_path),
        pip_size=strategy_config.pip_size,
    )
    statistical_outcome_evaluator = StatisticalOutcomeEvaluator(
        observation_db_path,
        minimum_group_samples=int(config.get("statistics_minimum_group_samples", 30)),
    )
    regime_conditioned_outcome_evaluator = RegimeConditionedOutcomeEvaluator(
        observation_db_path,
        minimum_group_samples=int(config.get("statistics_minimum_group_samples", 30)),
    )
    market_regime_engine = MarketRegimeEngine(pip_size=strategy_config.pip_size)
    research_intelligence_engine = ResearchIntelligenceEngine(
        max_current_age_seconds=int(config.get("research_intelligence_max_age_seconds", 300)),
    )
    lifecycle_store = LifecycleStore(market_store)
    recovery_manager = LifecycleRecoveryManager(lifecycle_store, market_store)
    price_action_runtime = PriceActionRuntime(
        coordinator=PriceActionCoordinator(),
        lifecycle_store=lifecycle_store,
        config=strategy_config,
        recovery_gate=recovery_manager,
    )
    recovered_streams = set()
    macro_calendar_store = MacroCalendarStore()
    macro_calendar_engine = MacroCalendarEngine.from_config(
        macro_calendar_store,
        ROOT / "calendar_sources.json",
    )
    calendar_refresh_lock = Lock()
    news_store = NewsStore()
    news_engine = NewsEngine(news_store)
    news_refresh_lock = Lock()

    def start_calendar_refresh() -> None:
        if not calendar_refresh_lock.acquire(blocking=False):
            return

        def refresh_worker() -> None:
            try:
                macro_calendar_engine.refresh_due()
            except Exception as exc:
                print(f"[MACRO_CALENDAR] {type(exc).__name__}: {exc}")
            finally:
                calendar_refresh_lock.release()

        Thread(target=refresh_worker, name="macro-calendar-refresh", daemon=True).start()

    def start_news_refresh() -> None:
        if not news_refresh_lock.acquire(blocking=False):
            return
        def refresh_worker() -> None:
            try:
                news_engine.refresh_due()
            except Exception as exc:
                print(f"[NEWS] {type(exc).__name__}: {exc}")
            finally:
                news_refresh_lock.release()
        Thread(target=refresh_worker, name="news-refresh", daemon=True).start()

    connector.connect()
    print("[MONITOR] Alert-only mode. No order functions are present.")
    print("[MONITOR] Market context is built from closed candles in SQLite.")
    print("[MONITOR] Press Ctrl+C to stop.")

    try:
        while True:
            try:
                snapshot = context_builder.build(
                    timeframes=tuple(config["timeframes"]),
                    count=config["bars_to_fetch"],
                )
                start_calendar_refresh()
                start_news_refresh()
                try:
                    news_payload = news_engine.build_context(snapshot.timestamp_utc)
                except Exception as exc:
                    news_payload = {
                        "status": "UNAVAILABLE",
                        "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
                        "source_states": [],
                        "stale_sources": ["NEWS_CONTEXT_UNAVAILABLE"],
                        "article_count": 0,
                        "articles": [],
                        "reason_code": "NEWS_CONTEXT_READ_FAILED",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "decision_authority": "CONTEXT_ONLY",
                        "trade_authority": "NONE",
                    }
                try:
                    macro_calendar_payload = macro_calendar_engine.build_context(
                        now_utc=snapshot.timestamp_utc,
                        horizon_hours=int(config.get("calendar_horizon_hours", 72)),
                    )
                except Exception as exc:
                    macro_calendar_payload = {
                        "status": "UNAVAILABLE",
                        "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
                        "horizon_hours": int(config.get("calendar_horizon_hours", 72)),
                        "currencies": ["EUR", "USD"],
                        "source_states": {},
                        "stale_sources": ["CALENDAR_CONTEXT_UNAVAILABLE"],
                        "upcoming_events": [],
                        "event_count": 0,
                        "high_impact_count": 0,
                        "reason_code": "CALENDAR_CONTEXT_READ_FAILED",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "trade_authority": "NONE",
                        "decision_authority": "CONTEXT_ONLY",
                    }
                stream_key = (snapshot.broker_server, snapshot.symbol)
                if stream_key not in recovered_streams:
                    recovery_manager.recover_stream(
                        snapshot.broker_server,
                        snapshot.symbol,
                        strategy_config,
                    )
                    recovered_streams.add(stream_key)
                price_action_result = price_action_runtime.process(snapshot)
                price_action_payload = _price_action_runtime_payload(
                    price_action_result,
                    recovery_manager.get_details(
                        snapshot.broker_server, snapshot.symbol
                    ),
                )
                active_lifecycle = (
                    price_action_result.transition.lifecycle
                    if price_action_result.transition is not None
                    else None
                )
                try:
                    setup_assessment = setup_pattern_engine.assess(
                        active_lifecycle,
                        snapshot.m1_candles,
                        snapshot.timestamp_utc,
                    ).to_dict()
                except Exception as exc:
                    setup_assessment = {
                        "stage": "BLOCKED",
                        "reason_codes": [f"SETUP_ASSESSMENT_ERROR:{type(exc).__name__}"],
                        "decision_authority": "ASSESSMENT_ONLY",
                        "trade_authority": "NONE",
                        "entry_eligibility": "BLOCKED",
                    }
                try:
                    session_eligibility = session_risk_gate.assess(
                        evaluated_at_utc=snapshot.timestamp_utc,
                        broker_server=snapshot.broker_server,
                        symbol=snapshot.symbol,
                        setup_assessment=setup_assessment,
                        lifecycle_id=(active_lifecycle.lifecycle_id if active_lifecycle else price_action_result.lifecycle_id),
                    )
                except Exception as exc:
                    session_eligibility = {
                        "status": "BLOCKED",
                        "reason_codes": [f"SESSION_RISK_GATE_ERROR:{type(exc).__name__}"],
                        "decision_authority": "ASSESSMENT_ONLY",
                        "trade_authority": "NONE",
                        "order_execution": "DISABLED",
                    }
                structures = {}
                screenshots = {}
                technical_analysis = None
                technical_structure = None
                technical_error = None
                if snapshot.quality.is_valid:
                    try:
                        technical_structure = technical_engine.analyze_snapshot(snapshot)
                        technical_analysis = _technical_structure_payload(technical_structure)
                    except Exception as exc:
                        technical_error = (
                            f"TechnicalEngine failed: {type(exc).__name__}: {exc}"
                        )
                else:
                    technical_error = "Market context quality gate failed"
                try:
                    if not snapshot.quality.is_valid:
                        market_regime_report = market_regime_engine.assess(
                            snapshot, technical_structure
                        )
                    elif technical_structure is None:
                        market_regime_report = {
                            "status": "DEGRADED",
                            "regime": "UNKNOWN",
                            "reason_codes": ["TECHNICAL_STRUCTURE_UNAVAILABLE"],
                            "decision_authority": "ASSESSMENT_ONLY",
                            "trade_authority": "NONE",
                            "order_execution": "DISABLED",
                        }
                    else:
                        market_regime_report = market_regime_engine.assess(
                            snapshot, technical_structure
                        )
                except Exception as exc:
                    market_regime_report = {
                        "status": "DEGRADED",
                        "regime": "UNKNOWN",
                        "reason_codes": [f"MARKET_REGIME_ERROR:{type(exc).__name__}"],
                        "decision_authority": "ASSESSMENT_ONLY",
                        "trade_authority": "NONE",
                        "order_execution": "DISABLED",
                    }
                try:
                    setup_outcome = setup_outcome_tracker.assess(
                        evaluated_at_utc=snapshot.timestamp_utc,
                        broker_server=snapshot.broker_server,
                        symbol=snapshot.symbol,
                        lifecycle_id=(active_lifecycle.lifecycle_id if active_lifecycle else price_action_result.lifecycle_id),
                        setup_assessment=setup_assessment,
                        session_eligibility=session_eligibility,
                        m1_candles=snapshot.m1_candles,
                        regime_context=market_regime_report,
                    )
                except Exception as exc:
                    setup_outcome = {
                        "status": "BLOCKED",
                        "reason_code": f"SETUP_OUTCOME_ERROR:{type(exc).__name__}",
                        "observation_type": "PRICE_EXCURSION_ONLY",
                        "trade_authority": "NONE",
                        "order_execution": "DISABLED",
                    }
                try:
                    statistical_outcome_report = statistical_outcome_evaluator.build_report(
                        evaluated_at_utc=snapshot.timestamp_utc,
                    )
                except Exception as exc:
                    statistical_outcome_report = {
                        "status": "DEGRADED",
                        "reason_code": f"STATISTICAL_EVALUATION_ERROR:{type(exc).__name__}",
                        "report_type": "DESCRIPTIVE_PRICE_EXCURSION_STATISTICS",
                        "decision_authority": "ASSESSMENT_ONLY",
                        "trade_authority": "NONE",
                        "order_execution": "DISABLED",
                    }
                try:
                    regime_conditioned_outcome_report = regime_conditioned_outcome_evaluator.build_report(
                        evaluated_at_utc=snapshot.timestamp_utc,
                    )
                except Exception as exc:
                    regime_conditioned_outcome_report = {
                        "status": "DEGRADED",
                        "reason_code": f"REGIME_CONDITIONED_EVALUATION_ERROR:{type(exc).__name__}",
                        "report_type": "REGIME_CONDITIONED_PRICE_EXCURSION_STATISTICS",
                        "decision_authority": "ASSESSMENT_ONLY",
                        "trade_authority": "NONE",
                        "order_execution": "DISABLED",
                    }
                for tf in config["timeframes"]:
                    candles = getattr(snapshot, f"{tf.lower()}_candles", ())
                    frame = _candles_frame(candles)
                    frame.to_csv(data_dir / f"{config['symbol']}_{tf}.csv", index=False)
                    structures[tf] = summarize_structure(
                        frame,
                        closed_candles_only=True,
                    )
                    screenshots[tf] = inspect_screenshot(
                        connector.screenshot_path(tf),
                        config["screenshot_max_age_seconds"],
                    )

                tick = dict(snapshot.tick or {})
                price_action_blocked = price_action_result.status.value not in (
                    "PROCESSED",
                    "NO_LIFECYCLE",
                )
                if (
                    not snapshot.quality.is_valid
                    or technical_error is not None
                    or price_action_blocked
                ):
                    decision_reasons = []
                    if technical_error is not None:
                        decision_reasons.append(technical_error)
                    if not snapshot.quality.is_valid:
                        decision_reasons.append("Market context quality gate failed")
                        decision_reasons.extend(snapshot.quality.issues)
                    if price_action_blocked:
                        decision_reasons.extend(price_action_result.reason_codes)
                    decision = {
                        "decision": "WAIT",
                        "direction": "NONE",
                        "reasons": decision_reasons,
                        "trade_execution": "DISABLED",
                    }
                else:
                    decision = evaluate(
                        structures.get("M1", {}),
                        structures.get("M5", {}),
                        tick,
                        screenshots,
                    )
                fusion_assessment = _build_fusion_assessment(
                    fusion_engine,
                    snapshot,
                    technical_analysis,
                    technical_error,
                    price_action_payload,
                    macro_calendar_payload,
                    news_payload,
                )
                fusion_payload = fusion_assessment.to_dict()
                research_sources = build_research_intelligence_sources(
                    {
                        "fusion_assessment": fusion_payload,
                        "market_regime_intelligence": market_regime_report,
                        "price_action_lifecycle": price_action_payload,
                        "setup_assessment": setup_assessment,
                        "session_eligibility": session_eligibility,
                        "setup_outcome_observation": setup_outcome,
                        "statistical_outcome_evaluation": statistical_outcome_report,
                        "regime_conditioned_outcome_evaluation": regime_conditioned_outcome_report,
                    },
                    broker_server=snapshot.broker_server,
                    symbol=snapshot.symbol,
                )
                research_intelligence = build_research_intelligence_payload(
                    research_intelligence_engine,
                    evaluated_at_utc=snapshot.timestamp_utc,
                    broker_server=snapshot.broker_server,
                    symbol=snapshot.symbol,
                    sources=research_sources,
                )
                payload = {
                    "fusion_assessment": fusion_payload,
                    "research_intelligence": research_intelligence,
                    "symbol": snapshot.symbol,
                    "tick": tick,
                    "market_structure": structures,
                    "price_action_lifecycle": price_action_payload,
                    "setup_assessment": setup_assessment,
                    "session_eligibility": session_eligibility,
                    "setup_outcome_observation": setup_outcome,
                    "statistical_outcome_evaluation": statistical_outcome_report,
                    "regime_conditioned_outcome_evaluation": regime_conditioned_outcome_report,
                    "market_regime_intelligence": market_regime_report,
                    "macro_calendar": macro_calendar_payload,
                    "news_intelligence": news_payload,
                    "technical_analysis": (
                        technical_analysis
                        if technical_analysis is not None
                        else {
                            "status": "SKIPPED",
                            "reason": technical_error,
                        }
                    ),
                    "screenshots": screenshots,
                    "market_context": {
                        "timestamp_utc": snapshot.timestamp_utc.isoformat(),
                        "broker_server": snapshot.broker_server,
                        "source": snapshot.source,
                        "spread_pips": (
                            str(snapshot.spread_pips)
                            if snapshot.spread_pips is not None
                            else None
                        ),
                        "quality": _quality_payload(snapshot.quality),
                    },
                    **decision,
                }
                signals.publish(payload)
                if price_action_result.status.value not in ("PROCESSED", "NO_LIFECYCLE"):
                    print(
                        "[PRICE_ACTION] "
                        + price_action_result.status.value
                        + ": "
                        + " | ".join(price_action_result.reason_codes)
                    )
                if not snapshot.quality.is_valid:
                    print("[CONTEXT] Invalid market context: " + " | ".join(snapshot.quality.issues))
                elif snapshot.quality.warnings:
                    print("[CONTEXT] Warnings: " + " | ".join(snapshot.quality.warnings))
            except Exception as exc:
                print(f"[ERROR] {type(exc).__name__}: {exc}")
            time.sleep(config["poll_seconds"])
    except KeyboardInterrupt:
        print("\n[MONITOR] Stopping...")
    finally:
        connector.close()


if __name__ == "__main__":
    main()

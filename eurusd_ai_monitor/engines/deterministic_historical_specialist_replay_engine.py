from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from eurusd_ai_monitor.engines.central_scenario_intelligence_engine import CentralScenarioIntelligenceEngine
from eurusd_ai_monitor.engines.liquidity_microstructure_engine import LiquidityMicrostructureEngine
from eurusd_ai_monitor.engines.market_regime_engine import MarketRegimeEngine
from eurusd_ai_monitor.engines.quantitative_market_statistics_engine import QuantitativeMarketStatisticsEngine
from eurusd_ai_monitor.engines.multi_domain_runtime import build_live_fundamental_reports
from eurusd_ai_monitor.models.context_quality import ContextQuality
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.market_data_store import Candle, TIMEFRAME_SECONDS


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    return _utc(parsed, field)


class DeterministicHistoricalSpecialistReplayEngine:
    """Re-execute deterministic specialists from point-in-time reconstructed evidence.

    This is research-only. It does not mutate lifecycle state, source archives,
    knowledge stores, strategy configuration, or execution controls.
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        reconstruction_engine,
        *,
        technical_engine,
        observation_store=None,
        macro_engine=None,
        policy_engine=None,
        intermarket_engine=None,
        positioning_engine=None,
        regime_engine=None,
        quantitative_engine=None,
        liquidity_engine=None,
        central_engine: CentralScenarioIntelligenceEngine | None = None,
        pip_size: Decimal | str = Decimal("0.0001"),
    ) -> None:
        if reconstruction_engine is None or not callable(getattr(reconstruction_engine, "reconstruct", None)):
            raise TypeError("reconstruction_engine must expose reconstruct")
        if technical_engine is None or not callable(getattr(technical_engine, "analyze_snapshot", None)):
            raise TypeError("technical_engine must expose analyze_snapshot")
        if observation_store is not None and not getattr(observation_store, "_read_only", False):
            raise ValueError("observation_store must be opened read-only")
        self._reconstruction = reconstruction_engine
        self._technical = technical_engine
        self._observations = observation_store
        self._macro = macro_engine
        self._policy = policy_engine
        self._intermarket = intermarket_engine
        self._positioning = positioning_engine
        self._regime = regime_engine or MarketRegimeEngine(pip_size=pip_size)
        self._quant = quantitative_engine or QuantitativeMarketStatisticsEngine()
        self._liquidity = liquidity_engine or LiquidityMicrostructureEngine()
        self._central = central_engine or CentralScenarioIntelligenceEngine(max_report_age_seconds=86400)
        self._pip_size = Decimal(str(pip_size))
        if not self._pip_size.is_finite() or self._pip_size <= 0:
            raise ValueError("pip_size must be finite and positive")

    def replay(
        self,
        replay_points: Iterable[Mapping[str, Any]],
        *,
        broker_server: str,
        symbol: str,
        start_utc: datetime,
        end_utc: datetime,
        observation_requests: Mapping[str, Iterable[tuple[str, str]]] | None = None,
    ) -> dict[str, Any]:
        start, end = _utc(start_utc, "start_utc"), _utc(end_utc, "end_utc")
        if start >= end:
            raise ValueError("start_utc must be earlier than end_utc")
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if isinstance(replay_points, (str, bytes, Mapping)):
            raise TypeError("replay_points must be an iterable of mappings")

        points = list(replay_points)
        output: list[dict[str, Any]] = []
        rejected: Counter[str] = Counter()
        for index, point in enumerate(points):
            if not isinstance(point, Mapping):
                rejected["REPLAY_POINT_NOT_A_MAPPING"] += 1
                continue
            try:
                evaluated = _time(point.get("evaluated_at_utc"), "evaluated_at_utc")
                if evaluated < start or evaluated > end or evaluated > datetime.now(timezone.utc):
                    raise ValueError("REPLAY_POINT_OUTSIDE_VALID_WINDOW")
                m1 = self._reconstruction.reconstruct(
                    as_of_utc=evaluated, broker_server=broker_server, symbol=symbol,
                    timeframe="M1", start_utc=start, end_utc=evaluated,
                    observation_requests=observation_requests,
                )
                m5 = self._reconstruction.reconstruct(
                    as_of_utc=evaluated, broker_server=broker_server, symbol=symbol,
                    timeframe="M5", start_utc=start, end_utc=evaluated,
                    observation_requests=observation_requests,
                )
                snapshot = self._snapshot(m1, m5, evaluated, broker_server, symbol)
                reports = self._reexecute(snapshot, m1, m5)
                sources = self._scenario_sources(reports, m1, m5, evaluated)
                scenario = self._central.assess(
                    evaluated_at_utc=evaluated, broker_server=broker_server,
                    symbol=symbol, sources=sources,
                )
                output.append({
                    "point_index": index,
                    "evaluated_at_utc": evaluated.isoformat(),
                    "market_snapshot_quality": {
                        "is_valid": snapshot.quality.is_valid,
                        "issues": list(snapshot.quality.issues),
                        "m1_candle_count": len(snapshot.m1_candles),
                        "m5_candle_count": len(snapshot.m5_candles),
                    },
                    "specialist_reports": reports,
                    "scenario_assessment": scenario,
                    "replay_mode": "POINT_IN_TIME_DETERMINISTIC_SPECIALIST_REEXECUTION",
                    "historical_specialists_recomputed": True,
                    "specialists_recomputed": sorted(
                        name for name, report in reports.items()
                        if report.get("reexecution_status") == "REEXECUTED"
                    ),
                    "specialists_not_recomputed": {
                        "price_action_lifecycle": "STATEFUL_LIFECYCLE_REPLAY_NOT_YET_SUPPORTED",
                        "news_semantic_intelligence": "HISTORICAL_NEWS_MODEL_AND_FEATURE_VERSION_NOT_PINNED",
                        "macro_calendar_semantics": "EVENT_CONTEXT_RECONSTRUCTED_BUT_NO_VERSIONED_IMPACT_MODEL",
                        "fusion_assessment": "FUSION_REPLAY_NOT_AUTHORIZED_AS_A_DIRECTIONAL_REPLACEMENT",
                    },
                    "reconstructed_market_evidence_used_for_specialist_reexecution": True,
                    "raw_news_calendar_payloads_used_as_specialist_reports": False,
                })
            except (ValueError, TypeError, KeyError) as exc:
                rejected[str(exc)] += 1

        return {
            "report_type": "DETERMINISTIC_MULTI_DOMAIN_SPECIALIST_HISTORICAL_REPLAY",
            "engine_version": self.VERSION,
            "status": "PARTIAL" if output else "INSUFFICIENT_DATA",
            "broker_server": broker_server,
            "symbol": symbol,
            "requested_window": {"start_utc": start.isoformat(), "end_utc": end.isoformat()},
            "replay_points_received": len(points),
            "replay_points_processed": len(output),
            "rejected_counts": dict(sorted(rejected.items())),
            "points": output,
            "methodology": [
                "M1 and M5 are reconstructed independently at each original evaluation timestamp.",
                "Only closed candles and source observations proven visible by that timestamp are eligible.",
                "Technical structure, market regime, quantitative statistics and liquidity proxies are re-executed from reconstructed candles.",
                "Macro, policy, intermarket and positioning specialists are re-executed only when their engines and point-in-time observation store are supplied.",
                "The central scenario engine receives newly recomputed reports; missing specialists remain missing.",
                "No archived future specialist output is used to fill gaps.",
            ],
            "limitations": [
                "Price Action lifecycle is stateful and is not replayed by this phase; it is explicitly missing from scenario inputs.",
                "News semantic and macro-calendar impact models are not re-executed without pinned model/feature versions; only their reconstructed evidence coverage is reported.",
                "Historical replay uses the currently injected deterministic algorithm versions; exact historical code-version replay requires a future immutable model registry.",
                "No numeric probability calibration, trading P&L, strategy optimization, or profitability claim is produced.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _snapshot(m1_report, m5_report, evaluated, broker, symbol) -> MarketSnapshot:
        m1 = DeterministicHistoricalSpecialistReplayEngine._candles(m1_report, "M1", broker, symbol)
        m5 = DeterministicHistoricalSpecialistReplayEngine._candles(m5_report, "M5", broker, symbol)
        issues = []
        if not m1:
            issues.append("M1_POINT_IN_TIME_CANDLES_UNAVAILABLE")
        if not m5:
            issues.append("M5_POINT_IN_TIME_CANDLES_UNAVAILABLE")
        last_by_tf = {
            tf: rows[-1].candle_open_time_utc + timedelta(seconds=TIMEFRAME_SECONDS[tf])
            for tf, rows in (("M1", m1), ("M5", m5)) if rows
        }
        for tf, maximum_age in (("M1", 180), ("M5", 900)):
            if tf in last_by_tf and (evaluated - last_by_tf[tf]).total_seconds() > maximum_age:
                issues.append(f"{tf}_HISTORICAL_CANDLE_WINDOW_STALE")
        quality = ContextQuality(
            is_valid=not issues,
            issues=tuple(issues),
            last_candle_time=max(
                (c.candle_open_time_utc + timedelta(seconds=TIMEFRAME_SECONDS[c.timeframe])
                 for c in (*m1, *m5)),
                default=None,
            ),
            candle_counts={"M1": len(m1), "M5": len(m5)},
            timeframe_last_candle_times=last_by_tf,
        )
        return MarketSnapshot(
            symbol=symbol, timestamp_utc=evaluated, broker_server=broker,
            m1_candles=m1, m5_candles=m5, tick=None, spread_pips=None,
            quality=quality, source="POINT_IN_TIME_RECONSTRUCTION",
        )

    @staticmethod
    def _candles(report, timeframe, broker, symbol) -> tuple[Candle, ...]:
        component = report.get("market_candles", {})
        if not isinstance(component, Mapping) or component.get("status") not in {"AVAILABLE", "PARTIAL"}:
            return ()
        result = []
        for row in component.get("candles", ()):
            opened = _time(row.get("candle_open_time_utc"), "candle_open_time_utc")
            result.append(Candle(
                broker_server=broker, symbol=symbol, timeframe=timeframe,
                candle_open_time_utc=opened,
                open=Decimal(str(row["open"])), high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])), close=Decimal(str(row["close"])),
                tick_volume=int(row["tick_volume"]), spread=int(row["spread"]),
                real_volume=int(row["real_volume"]),
            ))
        return tuple(result)

    def _reexecute(self, snapshot, m1_report, m5_report) -> dict[str, dict[str, Any]]:
        reports: dict[str, dict[str, Any]] = {}
        if not snapshot.quality.is_valid:
            # Fail closed: stale or incomplete historical market context must not
            # be passed to any specialist or create directional scenario evidence.
            for name in (
                "technical_analysis",
                "market_regime_intelligence",
                "quantitative_market_statistics",
                "liquidity_microstructure_intelligence",
                "macro_fundamentals_intelligence",
                "policy_rate_differential_intelligence",
                "intermarket_intelligence",
                "positioning_sentiment_intelligence",
            ):
                reports[name] = self._quality_blocked_report(snapshot, name)
            return reports

        technical_structure = None
        try:
            technical_structure = self._technical.analyze_snapshot(snapshot)
            technical_report = self._technical_payload(technical_structure)
            reports["technical_analysis"] = {
                **technical_report, "reexecution_status": "REEXECUTED",
                "broker_server": snapshot.broker_server, "symbol": snapshot.symbol,
            }
        except Exception as exc:
            reports["technical_analysis"] = self._failed_report(snapshot, "technical_analysis", exc)

        runners = (
            ("market_regime_intelligence", lambda: self._regime.assess(
                snapshot, technical_structure=technical_structure
            )),
            ("quantitative_market_statistics", lambda: self._quant.assess(snapshot)),
            ("liquidity_microstructure_intelligence", lambda: self._liquidity.analyze(
                evaluated_at_utc=snapshot.timestamp_utc,
                broker_server=snapshot.broker_server, symbol=snapshot.symbol,
                samples=[
                    {"candle": candle, "pip_size": self._pip_size, "spread_pips": None,
                     "retrieved_at_utc": self._retrieved_at(candle, m1_report, m5_report)}
                    for candle in (*snapshot.m1_candles, *snapshot.m5_candles)
                ],
            )),
        )
        for name, runner in runners:
            try:
                report = runner()
                reports[name] = {
                    **report, "reexecution_status": "REEXECUTED",
                    "broker_server": snapshot.broker_server, "symbol": snapshot.symbol,
                }
            except Exception as exc:
                reports[name] = self._failed_report(snapshot, name, exc)

        if self._observations is not None and all((self._macro, self._policy, self._intermarket, self._positioning)):
            try:
                fundamental = build_live_fundamental_reports(
                    snapshot, observation_store=self._observations,
                    macro_engine=self._macro, policy_engine=self._policy,
                    intermarket_engine=self._intermarket, positioning_engine=self._positioning,
                )
                for name, report in fundamental.items():
                    reports[name] = {**report, "reexecution_status": "REEXECUTED"}
            except Exception as exc:
                reports["fundamental_domain_bundle"] = {
                    "status": "UNAVAILABLE", "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
                    "reason_codes": [f"FUNDAMENTAL_REEXECUTION_FAILED:{type(exc).__name__}"],
                    "reexecution_status": "FAILED",
                }
        else:
            for name in ("macro_fundamentals_intelligence", "policy_rate_differential_intelligence",
                         "intermarket_intelligence", "positioning_sentiment_intelligence"):
                reports[name] = {
                    "status": "UNAVAILABLE", "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
                    "reason_codes": ["REQUIRED_ENGINE_OR_POINT_IN_TIME_STORE_NOT_CONFIGURED"],
                    "reexecution_status": "NOT_CONFIGURED",
                }
        return reports

    @staticmethod
    def _quality_blocked_report(snapshot, name):
        return {
            "report_type": name.upper(),
            "status": "UNAVAILABLE",
            "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
            "broker_server": snapshot.broker_server,
            "symbol": snapshot.symbol,
            "reason_codes": [
                "MARKET_SNAPSHOT_QUALITY_INVALID",
                *list(snapshot.quality.issues),
            ],
            "reexecution_status": "BLOCKED_QUALITY_GATE",
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _failed_report(snapshot, name, exc):
        return {
            "report_type": name.upper(), "status": "UNAVAILABLE",
            "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
            "broker_server": snapshot.broker_server, "symbol": snapshot.symbol,
            "reason_codes": [f"REEXECUTION_FAILED:{type(exc).__name__}"],
            "reexecution_status": "FAILED",
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _retrieved_at(candle, m1_report, m5_report):
        report = m1_report if candle.timeframe == "M1" else m5_report
        rows = report.get("market_candles", {}).get("candles", ())
        close_time = candle.candle_open_time_utc + timedelta(seconds=TIMEFRAME_SECONDS[candle.timeframe])
        for row in rows:
            if row.get("candle_open_time_utc") == candle.candle_open_time_utc.isoformat():
                first_seen = _time(row.get("first_seen_at_utc"), "first_seen_at_utc")
                last_seen = _time(row.get("last_seen_at_utc"), "last_seen_at_utc")
                # If the first observation already proves closure, use it; otherwise
                # Phase 31's conservative gate proves closure via last_seen.
                return first_seen if first_seen >= close_time else last_seen
        raise ValueError("reconstructed candle availability provenance is missing")

    @staticmethod
    def _technical_payload(structure) -> dict[str, Any]:
        trend = structure.trend
        return {
            "report_type": "TECHNICAL_ANALYSIS",
            "status": "ANALYZED",
            "evaluated_at_utc": structure.evaluated_at_utc.isoformat(),
            "algorithm_version": structure.algorithm_version,
            "parameter_version": structure.parameter_version,
            "trend": {
                "direction": trend.direction.value,
                "confirmed_at_utc": trend.confirmed_at_utc.isoformat(),
                "swing_highs": [],
                "swing_lows": [],
            },
            "pivots": [{"kind": pivot.kind.value, "price": str(pivot.price),
                        "candle_id": f"{pivot.evidence.candle.timeframe}|{pivot.evidence.candle.candle_open_time_utc.isoformat()}"}
                       for pivot in structure.pivots],
            "protected_swing_break": None if structure.protected_swing_break is None else {
                "broken_direction": structure.protected_swing_break.broken_direction.value,
                "confirmed_at_utc": structure.protected_swing_break.confirmed_at_utc.isoformat(),
            },
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _scenario_sources(reports, m1, m5, evaluated):
        def evidence_status(report):
            status = report.get("status", "UNAVAILABLE")
            if status in {"AVAILABLE", "PARTIAL"}:
                return "PARTIAL"
            if status == "NOT_CONFIGURED":
                return "NOT_CONFIGURED"
            return "UNAVAILABLE"
        news = m1.get("news", {})
        calendar = m1.get("macro_calendar", {})
        news_report = {
            "report_type": "NEWS_EVIDENCE_COVERAGE_ONLY",
            "status": evidence_status(news), "evaluated_at_utc": evaluated.isoformat(),
            "reason_codes": [*news.get("reason_codes", []), "NEWS_SEMANTIC_SPECIALIST_NOT_REEXECUTED"],
            "decision_authority": "CONTEXT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        calendar_report = {
            "report_type": "MACRO_CALENDAR_EVIDENCE_COVERAGE_ONLY",
            "status": evidence_status(calendar), "evaluated_at_utc": evaluated.isoformat(),
            "reason_codes": [*calendar.get("reason_codes", []), "CALENDAR_IMPACT_SPECIALIST_NOT_REEXECUTED"],
            "decision_authority": "CONTEXT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        return {
            "technical_analysis": reports.get("technical_analysis"),
            "price_action_lifecycle": None,
            "market_regime_intelligence": reports.get("market_regime_intelligence"),
            "fusion_assessment": None,
            "macro_fundamentals_intelligence": reports.get("macro_fundamentals_intelligence"),
            "policy_rate_differential_intelligence": reports.get("policy_rate_differential_intelligence"),
            "intermarket_intelligence": reports.get("intermarket_intelligence"),
            "positioning_sentiment_intelligence": reports.get("positioning_sentiment_intelligence"),
            "quantitative_market_statistics": reports.get("quantitative_market_statistics"),
            "liquidity_microstructure_intelligence": reports.get("liquidity_microstructure_intelligence"),
            "macro_calendar": calendar_report, "news_intelligence": news_report,
        }

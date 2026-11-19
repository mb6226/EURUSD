from __future__ import annotations

from typing import Any


def _failure_report(snapshot, specialist: str, exc: Exception) -> dict[str, Any]:
    return {
        "report_type": specialist.upper(),
        "status": "DEGRADED",
        "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
        "broker_server": snapshot.broker_server,
        "symbol": snapshot.symbol,
        "reason_codes": [f"{specialist.upper()}_RUNTIME_ERROR:{type(exc).__name__}"],
        "decision_authority": "ASSESSMENT_ONLY",
        "trade_authority": "NONE",
        "order_execution": "DISABLED",
    }


def build_live_specialist_reports(
    snapshot,
    *,
    quantitative_engine,
    liquidity_engine,
    pip_size,
) -> dict[str, dict[str, Any]]:
    """Run only specialists whose inputs are already present in the cycle snapshot.

    Spread is intentionally left unknown for historical candles: the current
    snapshot spread is not a per-candle spread history and Candle.spread is not
    converted because its broker/symbol point scale is not normalized here.
    """
    reports: dict[str, dict[str, Any]] = {}
    try:
        reports["quantitative_market_statistics"] = quantitative_engine.assess(snapshot)
    except Exception as exc:
        reports["quantitative_market_statistics"] = _failure_report(
            snapshot, "quantitative_market_statistics", exc
        )

    try:
        samples = [
            {
                "candle": candle,
                "pip_size": pip_size,
                "spread_pips": None,
                "retrieved_at_utc": snapshot.timestamp_utc,
            }
            for candle in (*snapshot.m1_candles, *snapshot.m5_candles)
        ]
        reports["liquidity_microstructure_intelligence"] = liquidity_engine.analyze(
            evaluated_at_utc=snapshot.timestamp_utc,
            broker_server=snapshot.broker_server,
            symbol=snapshot.symbol,
            samples=samples,
        )
    except Exception as exc:
        reports["liquidity_microstructure_intelligence"] = _failure_report(
            snapshot, "liquidity_microstructure_intelligence", exc
        )
    return reports

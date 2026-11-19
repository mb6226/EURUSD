from __future__ import annotations

from typing import Any

from eurusd_ai_monitor.engines.macro_fundamentals_engine import SERIES as MACRO_SERIES
from eurusd_ai_monitor.engines.policy_rate_differential_engine import (
    ECB_SOURCE, ECB_PRODUCT, FED_SOURCE, FED_PRODUCT,
)
from eurusd_ai_monitor.engines.intermarket_intelligence_engine import (
    DRIVERS as INTERMARKET_DRIVERS, EURUSD_IDENTITY,
)
from eurusd_ai_monitor.engines.positioning_sentiment_intelligence_engine import (
    PRODUCTS as POSITIONING_PRODUCTS,
)


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


def _identity(report: dict[str, Any], snapshot) -> dict[str, Any]:
    result = dict(report)
    result.setdefault("broker_server", snapshot.broker_server)
    result.setdefault("symbol", snapshot.symbol)
    return result


def _not_configured(snapshot, specialist: str) -> dict[str, Any]:
    return {
        "report_type": specialist.upper(),
        "status": "NOT_CONFIGURED",
        "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
        "broker_server": snapshot.broker_server,
        "symbol": snapshot.symbol,
        "reason_codes": ["POINT_IN_TIME_OBSERVATION_STORE_NOT_CONFIGURED"],
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
    """Run specialists whose inputs are already present in the cycle snapshot.

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


def build_live_fundamental_reports(
    snapshot,
    *,
    observation_store,
    macro_engine,
    policy_engine,
    intermarket_engine,
    positioning_engine,
    observation_store_error: Exception | None = None,
) -> dict[str, dict[str, Any]]:
    """Run four point-in-time specialists from one read-only as-of store snapshot.

    No network access, refresh, or persistence occurs here. The observation store
    must already exist and expose get_many_as_of; every selected record is bounded
    by effective, publication, and retrieval time at the cycle cutoff.
    """
    names = (
        "macro_fundamentals_intelligence",
        "policy_rate_differential_intelligence",
        "intermarket_intelligence",
        "positioning_sentiment_intelligence",
    )
    if observation_store is None:
        if observation_store_error is None:
            return {name: _not_configured(snapshot, name) for name in names}
        return {
            name: _failure_report(snapshot, name, observation_store_error)
            for name in names
        }

    macro_pairs = {name: (source, product) for name, (source, product, _unit) in MACRO_SERIES.items()}
    policy_pairs = {
        "ecb": (ECB_SOURCE, ECB_PRODUCT),
        "fed": (FED_SOURCE, FED_PRODUCT),
    }
    intermarket_pairs = {
        "eurusd": (EURUSD_IDENTITY[0], EURUSD_IDENTITY[1]),
        **{product: (definition["source_id"], product)
           for product, definition in INTERMARKET_DRIVERS.items()},
    }
    positioning_pairs = {
        product: ("CFTC_TFF_POSITIONING", product)
        for product in POSITIONING_PRODUCTS
    }
    requests = list(dict.fromkeys((
        *macro_pairs.values(),
        *policy_pairs.values(),
        *intermarket_pairs.values(),
        *positioning_pairs.values(),
    )))
    try:
        observations = observation_store.get_many_as_of(
            requests, snapshot.timestamp_utc
        )
    except Exception as exc:
        return {
            name: _failure_report(snapshot, name, exc)
            for name in names
        }

    def rows(pair):
        return observations.get(pair, ())

    reports: dict[str, dict[str, Any]] = {}
    calls = {
        "macro_fundamentals_intelligence": lambda: macro_engine.assess(
            as_of_utc=snapshot.timestamp_utc,
            us_cpi_observations=rows(macro_pairs["us_cpi"]),
            us_unemployment_observations=rows(macro_pairs["us_unemployment"]),
            ea_hicp_observations=rows(macro_pairs["ea_hicp"]),
            ea_unemployment_observations=rows(macro_pairs["ea_unemployment"]),
        ),
        "policy_rate_differential_intelligence": lambda: policy_engine.assess(
            as_of_utc=snapshot.timestamp_utc,
            ecb_observations=rows(policy_pairs["ecb"]),
            fed_observations=rows(policy_pairs["fed"]),
        ),
        "intermarket_intelligence": lambda: intermarket_engine.assess(
            as_of_utc=snapshot.timestamp_utc,
            eurusd_observations=rows(intermarket_pairs["eurusd"]),
            driver_observations={
                product: rows(pair) for product, pair in intermarket_pairs.items()
                if product != "eurusd"
            },
        ),
        "positioning_sentiment_intelligence": lambda: positioning_engine.assess(
            as_of_utc=snapshot.timestamp_utc,
            observations={
                product: rows(pair) for product, pair in positioning_pairs.items()
            },
        ),
    }
    for name, assess in calls.items():
        try:
            reports[name] = _identity(assess(), snapshot)
        except Exception as exc:
            reports[name] = _failure_report(snapshot, name, exc)
    return reports

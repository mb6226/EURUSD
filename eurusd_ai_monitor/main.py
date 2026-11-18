from __future__ import annotations

import json
import sys
import time
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
from eurusd_ai_monitor.engines.market_context_builder import MarketContextBuilder
from eurusd_ai_monitor.engines.technical_engine import TechnicalEngine
from eurusd_ai_monitor.strategy_config import load_strategy_config
from eurusd_ai_monitor.storage.market_data_store import MarketDataStore
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
    technical_engine = TechnicalEngine(load_strategy_config())

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
                structures = {}
                screenshots = {}
                technical_analysis = None
                technical_error = None
                if snapshot.quality.is_valid:
                    try:
                        technical_analysis = _technical_structure_payload(
                            technical_engine.analyze_snapshot(snapshot)
                        )
                    except Exception as exc:
                        technical_error = (
                            f"TechnicalEngine failed: {type(exc).__name__}: {exc}"
                        )
                else:
                    technical_error = "Market context quality gate failed"
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
                if not snapshot.quality.is_valid or technical_error is not None:
                    decision = {
                        "decision": "WAIT",
                        "direction": "NONE",
                        "reasons": [
                            technical_error or "Market context quality gate failed",
                            *snapshot.quality.issues,
                        ],
                        "trade_execution": "DISABLED",
                    }
                else:
                    decision = evaluate(
                        structures.get("M1", {}),
                        structures.get("M5", {}),
                        tick,
                        screenshots,
                    )
                payload = {
                    "symbol": snapshot.symbol,
                    "tick": tick,
                    "market_structure": structures,
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

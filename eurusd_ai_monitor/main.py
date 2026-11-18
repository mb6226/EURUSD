from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from engines.mt5_engine import MT5Connector
from engines.price_action_engine import summarize_structure
from engines.vision_engine import inspect_screenshot
from engines.decision_engine import evaluate
from engines.market_context_builder import MarketContextBuilder
from storage.market_data_store import MarketDataStore
from storage.mt5_market_adapter import MT5MarketDataAdapter
from alerts.signal_manager import SignalManager

ROOT = Path(__file__).resolve().parent


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

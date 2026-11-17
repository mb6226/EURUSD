from __future__ import annotations
import json
import time
from pathlib import Path

from engines.mt5_engine import MT5Connector
from engines.price_action_engine import summarize_structure
from engines.vision_engine import inspect_screenshot
from engines.decision_engine import evaluate
from alerts.signal_manager import SignalManager

ROOT = Path(__file__).resolve().parent

def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    data_dir = ROOT / "data" / "market"
    data_dir.mkdir(parents=True, exist_ok=True)
    connector = MT5Connector(config["symbol"])
    signals = SignalManager(ROOT / "logs")

    connector.connect()
    print("[MONITOR] Alert-only mode. No order functions are present.")
    print("[MONITOR] Press Ctrl+C to stop.")

    try:
        while True:
            try:
                tick = connector.tick()
                structures = {}
                screenshots = {}
                for tf in config["timeframes"]:
                    bars = connector.bars(tf, config["bars_to_fetch"])
                    bars.to_csv(data_dir / f"{config['symbol']}_{tf}.csv", index=False)
                    structures[tf] = summarize_structure(bars)
                    screenshots[tf] = inspect_screenshot(
                        connector.screenshot_path(tf),
                        config["screenshot_max_age_seconds"]
                    )

                decision = evaluate(
                    structures.get("M1", {}),
                    structures.get("M5", {}),
                    tick,
                    screenshots
                )
                payload = {
                    "symbol": config["symbol"],
                    "tick": tick,
                    "market_structure": structures,
                    "screenshots": screenshots,
                    **decision,
                }
                signals.publish(payload)
            except Exception as exc:
                print(f"[ERROR] {type(exc).__name__}: {exc}")
            time.sleep(config["poll_seconds"])
    except KeyboardInterrupt:
        print("\n[MONITOR] Stopping...")
    finally:
        connector.close()

if __name__ == "__main__":
    main()

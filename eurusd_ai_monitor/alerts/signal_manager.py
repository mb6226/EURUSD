from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

class SignalManager:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, payload: dict) -> None:
        payload["created_at_utc"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(payload, ensure_ascii=False)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with (self.log_dir / f"monitor-{day}.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print("\n" + "=" * 60)
        print(f"EURUSD AI MONITOR | {payload['decision']}")
        print("Reasons:")
        for reason in payload.get("reasons", []):
            print(f" - {reason}")
        print("=" * 60 + "\n")

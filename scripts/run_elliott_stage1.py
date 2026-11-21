"""Run the Stage-1 Elliott Intelligence Core on all derived EURUSD timeframes."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from eurusd_ai.data_catalog import EURUSD_TIMEFRAMES, PROJECT_ROOT, require_dataset
from eurusd_ai.market_data import load_ohlcv_csv
from Modules.Elliott_Waves.Detection.detector import detect_pivots
from Modules.Elliott_Waves.Detection.engine import ElliottEngine

THRESHOLDS_PIPS = {"M5": 8.0, "M15": 15.0, "H1": 25.0, "H4": 40.0, "D1": 60.0}


def main() -> None:
    out_dir = PROJECT_ROOT / "Modules" / "Elliott_Waves" / "Evaluation" / "stage1"
    out_dir.mkdir(parents=True, exist_ok=True)
    for timeframe in ("M5", "M15", "H1", "H4", "D1"):
        source = require_dataset(EURUSD_TIMEFRAMES[timeframe])
        candles = load_ohlcv_csv(source)
        pivots = detect_pivots(candles, THRESHOLDS_PIPS[timeframe], include_provisional=True)
        candidates = ElliottEngine(min_score=25).analyze_pivots(pivots)
        pattern_counts = Counter(c.pattern for c in candidates)
        payload = {
            "symbol": "EURUSD", "timeframe": timeframe,
            "source_file": source.name, "candles": len(candles),
            "pivot_threshold_pips": THRESHOLDS_PIPS[timeframe],
            "pivots": len(pivots),
            "confirmed_pivots": sum(p.confirmed for p in pivots),
            "provisional_pivots": sum(not p.confirmed for p in pivots),
            "candidate_count": len(candidates),
            "pattern_counts": dict(pattern_counts),
            "score_note": "Heuristic ranking only; not a probability or validated Elliott count.",
            "candidates": [c.to_dict() for c in candidates[:25]],
        }
        target = out_dir / f"{timeframe.lower()}_candidates.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{timeframe}: candles={len(candles)} pivots={len(pivots)} candidates={len(candidates)} patterns={dict(pattern_counts)} -> {target}")


if __name__ == "__main__":
    main()

from __future__ import annotations
import argparse
import json
from pathlib import Path
from .market_data import load_ohlcv_csv


def main():
    p = argparse.ArgumentParser(prog="eurusd-ai", description="Modular EURUSD research framework")
    sub = p.add_subparsers(dest="command", required=True)
    ins = sub.add_parser("inspect-csv"); ins.add_argument("csv_path")
    det = sub.add_parser("detect-waves"); det.add_argument("csv_path"); det.add_argument("--pip-size", type=float, default=0.0001); det.add_argument("--min-leg-pips", type=float, default=5.0)
    ana = sub.add_parser("analyze-elliott", help="Generate and rank Elliott Wave hypotheses")
    ana.add_argument("csv_path")
    ana.add_argument("--pip-size", type=float, default=0.0001)
    ana.add_argument("--min-leg-pips", type=float, default=10.0)
    ana.add_argument("--min-score", type=float, default=25.0)
    ana.add_argument("--top", type=int, default=20)
    ana.add_argument("--include-provisional", action="store_true")
    ana.add_argument("--output", default="")
    tr = sub.add_parser("train-elliott"); tr.add_argument("labels_csv"); tr.add_argument("--model-path", default="Modules/Elliott_Waves/Models/elliott_wave_model.joblib")
    a = p.parse_args()
    if a.command == "train-elliott":
        from Modules.Elliott_Waves.Training.train import train
        train(a.labels_csv, a.model_path); return
    candles = load_ohlcv_csv(a.csv_path)
    if a.command == "inspect-csv":
        print(f"Rows: {len(candles)} | First: {candles[0].time} | Last: {candles[-1].time}")
        return
    from Modules.Elliott_Waves.Detection.detector import detect_pivots, find_five_wave_candidates
    if a.command == "detect-waves":
        pivots = detect_pivots(candles, a.min_leg_pips, a.pip_size)
        candidates = find_five_wave_candidates(pivots)
        print(f"Candles: {len(candles)} | Pivots: {len(pivots)} | 5-wave candidates: {len(candidates)}")
        return
    from Modules.Elliott_Waves.Detection.engine import ElliottEngine
    pivots = detect_pivots(candles, a.min_leg_pips, a.pip_size, a.include_provisional)
    candidates = ElliottEngine(a.pip_size, a.min_score).analyze_pivots(pivots)
    payload = {
        "symbol": "EURUSD", "candles": len(candles), "pivots": len(pivots),
        "confirmed_pivots": sum(x.confirmed for x in pivots),
        "provisional_pivots": sum(not x.confirmed for x in pivots),
        "candidate_count": len(candidates),
        "warning": "Heuristic research ranking, not calibrated probability or trading advice.",
        "candidates": [x.to_dict() for x in candidates[:max(1, a.top)]],
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if a.output:
        out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        print(f"Saved {min(len(candidates), max(1, a.top))} ranked candidates to {out}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()

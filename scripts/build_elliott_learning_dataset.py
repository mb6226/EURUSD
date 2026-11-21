"""Build a causal, weakly supervised multi-timeframe Elliott learning dataset."""
from __future__ import annotations
import bisect
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from eurusd_ai.data_catalog import EURUSD_TIMEFRAMES, PROJECT_ROOT, require_dataset
from eurusd_ai.market_data import load_ohlcv_csv
from Modules.Elliott_Waves.Detection.detector import detect_pivots
from Modules.Elliott_Waves.Detection.engine import ElliottEngine
from Modules.Elliott_Waves.Detection.features import candidate_features

THRESHOLDS_PIPS = {"M5": 8.0, "M15": 15.0, "H1": 25.0, "H4": 40.0, "D1": 60.0}
BAR_SECONDS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
OUT = PROJECT_ROOT / "Modules" / "Elliott_Waves" / "Dataset" / "generated"
PIP = 0.0001

def iso_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()

def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    by_tf: dict[str, list[dict]] = {}
    summary: dict[str, dict] = {}
    all_swings: list[dict] = []
    all_structures: list[dict] = []
    for tf in ("M5", "M15", "H1", "H4", "D1"):
        source = require_dataset(EURUSD_TIMEFRAMES[tf])
        candles = load_ohlcv_csv(source)
        pivots = detect_pivots(candles, THRESHOLDS_PIPS[tf], include_provisional=False, confirmation_delay_seconds=BAR_SECONDS[tf])
        swings: list[dict] = []
        for i in range(1, len(pivots)):
            a, b = pivots[i - 1], pivots[i]
            if not a.confirmed or not b.confirmed or not b.confirmation_time:
                continue
            delta = b.price - a.price
            prior = abs(a.price - pivots[i - 2].price) / PIP if i >= 2 else None
            length = abs(delta) / PIP
            swings.append({
                "symbol": "EURUSD", "timeframe": tf, "event_type": "swing",
                "start_extreme_time": a.time, "end_extreme_time": b.time,
                "available_at": b.confirmation_time,
                "start_confirmation_time": a.confirmation_time,
                "end_confirmation_time": b.confirmation_time,
                "direction": "up" if delta > 0 else "down",
                "length_pips": round(length, 3),
                "duration_bars": b.index - a.index,
                "confirmation_lag_bars": b.confirmation_index - b.index if b.confirmation_index is not None else None,
                "retracement_of_previous_wave_pct": round(length / prior * 100, 3) if prior else None,
                "start_price": a.price, "end_price": b.price,
                "label_source": "causal_directional_change", "label_confidence": "mechanical_swing",
                "training_eligible": True
            })
        engine = ElliottEngine(min_score=25.0)
        candidates = engine.analyze_pivots(pivots)
        structures: list[dict] = []
        for c in candidates:
            ps = c.pivots
            if not ps or not all(p.confirmed and p.confirmation_time for p in ps):
                continue
            available = max(p.confirmation_time for p in ps if p.confirmation_time)
            feats = candidate_features(ps, PIP) if c.pattern == "impulse" else None
            legs = [round(abs(ps[j+1].price - ps[j].price) / PIP, 3) for j in range(len(ps)-1)]
            structures.append({
                "symbol": "EURUSD", "timeframe": tf, "event_type": "structure_candidate",
                "pattern": c.pattern, "direction": c.direction,
                "start_extreme_time": ps[0].time, "end_extreme_time": ps[-1].time,
                "available_at": available,
                "pivot_confirmation_times": [p.confirmation_time for p in ps],
                "pivot_extreme_times": [p.time for p in ps],
                "leg_lengths_pips": legs, "features": feats,
                "heuristic_score": c.score, "hard_valid": c.hard_valid,
                "rule_reasons": list(c.reasons),
                "label_source": "elliott_rule_engine_weak_label",
                "label_confidence": "weak_rule_based_not_expert_truth",
                "training_eligible": bool(c.hard_valid and c.score >= 50.0),
                "requires_independent_validation": True
            })
        swings.sort(key=lambda x: iso_epoch(x["available_at"]))
        structures.sort(key=lambda x: iso_epoch(x["available_at"]))
        by_tf[tf] = swings
        all_swings.extend(swings)
        all_structures.extend(structures)
        summary[tf] = {
            "source_file": source.name, "candles": len(candles),
            "pivot_threshold_pips": THRESHOLDS_PIPS[tf], "confirmed_pivots": len(pivots),
            "swing_records": len(swings), "structure_candidates": len(structures),
            "training_eligible_weak_labels": sum(x["training_eligible"] for x in structures),
            "pattern_counts": dict(Counter(x["pattern"] for x in structures))
        }
        print(f"{tf}: candles={len(candles):,} confirmed_pivots={len(pivots):,} swings={len(swings):,} structures={len(structures):,}", flush=True)
    # As-of joins: each event can only see other timeframe swings already confirmed.
    timelines = {}
    for tf, rows in by_tf.items():
        timelines[tf] = ( [iso_epoch(x["available_at"]) for x in rows], rows )
    mtf_rows = []
    for tf, events in ((t, by_tf[t] + [x for x in all_structures if x["timeframe"] == t]) for t in by_tf):
        for event in events:
            cutoff = iso_epoch(event["available_at"])
            context = {}
            for other, (times, rows) in timelines.items():
                pos = bisect.bisect_right(times, cutoff) - 1
                if pos >= 0:
                    last = rows[pos]
                    context[other] = {"direction": last["direction"], "length_pips": last["length_pips"],
                                      "retracement_of_previous_wave_pct": last["retracement_of_previous_wave_pct"],
                                      "available_at": last["available_at"]}
            mtf_rows.append({"symbol": "EURUSD", "event_time": event["available_at"],
                             "base_timeframe": tf, "event": event, "asof_swing_context": context,
                             "leakage_policy": "all context events have available_at <= event_time"})
    all_swings.sort(key=lambda x: (iso_epoch(x["available_at"]), x["timeframe"]))
    all_structures.sort(key=lambda x: (iso_epoch(x["available_at"]), x["timeframe"]))
    mtf_rows.sort(key=lambda x: (iso_epoch(x["event_time"]), x["base_timeframe"]))
    write_jsonl(OUT / "causal_swings.jsonl", all_swings)
    write_jsonl(OUT / "weak_structure_labels.jsonl", all_structures)
    write_jsonl(OUT / "multitimeframe_asof_events.jsonl", mtf_rows)
    manifest = {"dataset_id": "eurusd_elliott_learning_2021-11-20_2026-11-20", "status": "built",
                "source_manifest": "data/dataset_manifest.json", "date_range_utc": ["2021-11-20", "2026-11-20"],
                "timeframes": summary, "totals": {"swings": len(all_swings), "structure_candidates": len(all_structures),
                "multitimeframe_events": len(mtf_rows), "training_eligible_weak_labels": sum(x["training_eligible"] for x in all_structures)},
                "label_policy": "No expert ground truth is claimed. Weak labels are rule-engine hypotheses; rejected/ambiguous candidates remain in the dataset with explicit eligibility flags.",
                "causality_policy": "Pivot extreme time is separate from confirmation/availability time. Every event and as-of context is timestamped when it became knowable; no provisional pivot is emitted.",
                "generated_at_utc": datetime.now().astimezone().isoformat()}
    (OUT / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["totals"], indent=2), flush=True)
    print(f"OUTPUT={OUT}", flush=True)

if __name__ == "__main__":
    main()




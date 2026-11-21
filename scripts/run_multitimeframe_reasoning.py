from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5")
MAX_AGE_HOURS = {"D1": 24 * 10, "H4": 24 * 4, "H1": 48, "M15": 18, "M5": 6}


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must be timezone-aware: {value}")
    return dt.astimezone(timezone.utc)


def intervals_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a0, a1 = parse_time(a["start_extreme_time"]), parse_time(a["end_extreme_time"])
    b0, b1 = parse_time(b["start_extreme_time"]), parse_time(b["end_extreme_time"])
    return max(a0, b0) <= min(a1, b1)


def contains_interval(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    p0, p1 = parse_time(parent["start_extreme_time"]), parse_time(parent["end_extreme_time"])
    c0, c1 = parse_time(child["start_extreme_time"]), parse_time(child["end_extreme_time"])
    return p0 <= c0 and c1 <= p1 and (p0 < c0 or c1 < p1)


def _candidate_score(row: dict[str, Any], now: datetime, model: dict[str, Any] | None) -> float:
    # Transparent heuristic ranking, deliberately not a probability.
    score = max(0.0, min(100.0, float(row.get("heuristic_score") or 0.0)))
    if row.get("hard_valid") is not True:
        score *= 0.35
    age_hours = max(0.0, (now - parse_time(row["available_at"])).total_seconds() / 3600)
    age_limit = MAX_AGE_HOURS[row["timeframe"]]
    recency = max(0.0, 1.0 - age_hours / age_limit)
    score = 0.75 * score + 25.0 * recency
    # The stage-3 model is only an auxiliary weak-label morphology agreement signal.
    if model and model.get("model_prediction") == row.get("pattern"):
        score += min(3.0, max(0.0, float(model.get("model_score_not_calibrated_probability") or 0.0)) * 3.0)
    return round(min(100.0, score), 3)


def build_snapshot(now: datetime, active: dict[str, deque], model_index: dict[tuple, dict]) -> dict[str, Any]:
    selected: dict[str, list[dict]] = {}
    for tf in TIMEFRAMES:
        valid = []
        for row in active[tf]:
            age = (now - parse_time(row["available_at"])).total_seconds() / 3600
            if 0 <= age <= MAX_AGE_HOURS[tf]:
                model = model_index.get((tf, row["available_at"], row["pattern"]))
                item = dict(row)
                item["reasoning_score_not_probability"] = _candidate_score(row, now, model)
                valid.append(item)
        selected[tf] = sorted(valid, key=lambda x: (x["reasoning_score_not_probability"], x["available_at"]), reverse=True)[:3]

    candidates = [x for tf in TIMEFRAMES for x in selected[tf]]
    # One leading structure per timeframe is used for the directional hierarchy.
    # Opposite lower-timeframe legs can be ordinary corrections, not contradictions.
    leaders = {tf: next((x for x in selected[tf] if x.get("hard_valid") and x.get("direction") in ("up", "down")), None)
               for tf in TIMEFRAMES}
    direction_votes = Counter(x["direction"] for x in leaders.values() if x)
    represented = sum(bool(selected[tf]) for tf in TIMEFRAMES)
    conflicts = []
    if leaders["D1"] and leaders["H4"] and leaders["D1"]["direction"] != leaders["H4"]["direction"]:
        conflicts.append("higher_degree_D1_H4_conflict")
    if leaders["H4"] and leaders["H1"] and leaders["H4"]["direction"] != leaders["H1"]["direction"]:
        # Only flag when the two structures overlap in time without a parent/child containment.
        if intervals_overlap(leaders["H4"], leaders["H1"]) and not (
            contains_interval(leaders["H4"], leaders["H1"]) or contains_interval(leaders["H1"], leaders["H4"])):
            conflicts.append("H4_H1_overlap_direction_conflict")

    relationships = []
    for parent_tf, child_tf in zip(TIMEFRAMES, TIMEFRAMES[1:]):
        for parent in selected[parent_tf]:
            for child in selected[child_tf]:
                if contains_interval(parent, child):
                    relationships.append({
                        "parent_timeframe": parent_tf, "parent_available_at": parent["available_at"],
                        "child_timeframe": child_tf, "child_available_at": child["available_at"],
                        "direction_relation": "aligned" if parent["direction"] == child["direction"] else "countertrend",
                    })
                elif intervals_overlap(parent, child):
                    relationships.append({
                        "parent_timeframe": parent_tf, "parent_available_at": parent["available_at"],
                        "child_timeframe": child_tf, "child_available_at": child["available_at"],
                        "direction_relation": "overlap_without_containment",
                    })

    # Preserve alternative directional scenarios rather than forcing a single count.
    scenarios = []
    for direction in ("up", "down"):
        members = [x for x in candidates if x.get("direction") == direction and x.get("hard_valid")]
        if not members:
            continue
        by_tf = {tf: [x for x in members if x["timeframe"] == tf] for tf in TIMEFRAMES}
        tf_count = sum(bool(by_tf[tf]) for tf in TIMEFRAMES)
        mean_score = sum(x["reasoning_score_not_probability"] for x in members) / len(members)
        aligned_pairs = sum(1 for rel in relationships if rel["direction_relation"] == "aligned"
                            and any(x["timeframe"] == rel["parent_timeframe"] and x["available_at"] == rel["parent_available_at"] and x["direction"] == direction for x in members)
                            and any(x["timeframe"] == rel["child_timeframe"] and x["available_at"] == rel["child_available_at"] and x["direction"] == direction for x in members))
        scenarios.append({
            "direction": direction, "timeframes_represented": tf_count,
            "candidate_count": len(members), "mean_reasoning_score_not_probability": round(mean_score, 3),
            "aligned_parent_child_links": aligned_pairs,
            "degree_hint": {"D1": "primary", "H4": "intermediate", "H1": "minor", "M15": "minute", "M5": "subminute"},
            "candidate_refs": [{"timeframe": x["timeframe"], "pattern": x["pattern"],
                                "available_at": x["available_at"], "start_extreme_time": x["start_extreme_time"],
                                "end_extreme_time": x["end_extreme_time"],
                                "reasoning_score_not_probability": x["reasoning_score_not_probability"]}
                               for x in sorted(members, key=lambda z: TIMEFRAMES.index(z["timeframe"]))],
        })
    scenarios.sort(key=lambda x: (x["timeframes_represented"], x["aligned_parent_child_links"],
                                  x["mean_reasoning_score_not_probability"]), reverse=True)
    abstain_reasons = []
    if represented < 3:
        abstain_reasons.append("insufficient_timeframe_coverage")
    if conflicts:
        abstain_reasons.append("unresolved_direction_conflict")
    if not scenarios:
        abstain_reasons.append("no_hard_valid_candidates")
    if len(scenarios) > 1 and scenarios[0]["timeframes_represented"] == scenarios[1]["timeframes_represented"] and abs(
        scenarios[0]["mean_reasoning_score_not_probability"] - scenarios[1]["mean_reasoning_score_not_probability"]) < 8:
        abstain_reasons.append("competing_scenarios_close")
    return {
        "symbol": "EURUSD", "as_of": now.isoformat(), "timeframe_order": list(TIMEFRAMES),
        "candidate_count": len(candidates), "timeframes_represented": represented,
        "direction_votes": dict(direction_votes), "timeframe_leaders": {
            tf: ({"direction": leaders[tf]["direction"], "pattern": leaders[tf]["pattern"],
                  "available_at": leaders[tf]["available_at"]} if leaders[tf] else None) for tf in TIMEFRAMES
        }, "conflicts": conflicts,
        "relationships": relationships, "scenarios": scenarios[:2],
        "abstain": bool(abstain_reasons), "abstain_reasons": abstain_reasons,
        "invalidation": {"status": "unavailable_from_stage2_schema",
                         "note": "Candidate records do not include a verified invalidation price; none is fabricated."},
        "confidence_semantics": "heuristic ranking only; not calibrated probability, expert truth, or trade signal",
    }


def run(project_root: Path, output_dir: Path) -> dict[str, Any]:
    dataset = project_root / "Modules/Elliott_Waves/Dataset/generated/weak_structure_labels.jsonl"
    predictions = project_root / "Modules/Elliott_Waves/Training/stage3/heldout_predictions.jsonl"
    if not dataset.exists():
        raise FileNotFoundError(dataset)
    model_index = {}
    if predictions.exists():
        with predictions.open(encoding="utf-8") as handle:
            for line in handle:
                p = json.loads(line)
                # Stage-3 outputs don't carry pattern direction; match by weak label as pattern.
                model_index[(p["timeframe"], p["available_at"], p["weak_label"])] = p

    rows = []
    with dataset.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("timeframe") in TIMEFRAMES and row.get("available_at"):
                parse_time(row["available_at"])
                rows.append(row)
    rows.sort(key=lambda x: (parse_time(x["available_at"]), TIMEFRAMES.index(x["timeframe"])))
    active = {tf: deque(maxlen=30) for tf in TIMEFRAMES}
    snapshots = []
    current_time = None
    for row in rows:
        now = parse_time(row["available_at"])
        if current_time is not None and now != current_time:
            snapshots.append(build_snapshot(current_time, active, model_index))
        active[row["timeframe"]].append(row)
        current_time = now
    if current_time is not None:
        snapshots.append(build_snapshot(current_time, active, model_index))

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "multitimeframe_scenarios.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        for item in snapshots:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    summary = {
        "stage": 4, "name": "Multi-Timeframe Reasoning", "input_candidates": len(rows),
        "snapshots": len(snapshots), "abstained_snapshots": sum(x["abstain"] for x in snapshots),
        "direction_conflict_snapshots": sum(bool(x["conflicts"]) for x in snapshots),
        "scenario_appearances_by_direction": dict(Counter(s["direction"] for x in snapshots for s in x["scenarios"])),
        "timeframe_coverage_counts": dict(Counter(str(x["timeframes_represented"]) for x in snapshots)),
        "abstention_reason_counts": dict(Counter(reason for x in snapshots for reason in x["abstain_reasons"])),
        "timeframes": list(TIMEFRAMES), "max_candidate_age_hours": MAX_AGE_HOURS,
        "output": str(out.relative_to(project_root)),
        "limitations": [
            "Stage-2 structures are weak rule-engine labels, not expert-confirmed Elliott counts.",
            "Stage-3 auxiliary match uses timeframe, availability timestamp and weak pattern label only; it is not a unique candidate join and its raw score is never treated as probability.",
            "Candidate schema has no verified invalidation price, so invalidation is explicitly unavailable.",
            "Reasoning scores are transparent heuristics, not calibrated confidence or a trading signal.",
        ],
    }
    (output_dir / "stage4_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    output = args.output_dir or args.project_root / "Modules/Elliott_Waves/Evaluation/stage4"
    print(json.dumps(run(args.project_root, output), indent=2))


if __name__ == "__main__":
    main()

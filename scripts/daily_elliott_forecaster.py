"""Stage 7: daily, causal, structure-first Elliott scenario forecaster.

This is a research report generator, not a trading signal. It preserves competing
Stage-4 counts, refuses stale/ambiguous contexts, and never turns heuristic scores
into probabilities. Targets are empirical historical swing ranges, not Fibonacci.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ELLIOTT = ROOT / "Modules/Elliott_Waves"
STAGE4 = ELLIOTT / "Evaluation/stage4/multitimeframe_scenarios.jsonl"
WEAK = ELLIOTT / "Dataset/generated/weak_structure_labels.jsonl"
SWINGS = ELLIOTT / "Dataset/generated/causal_swings.jsonl"
OUT = ELLIOTT / "Evaluation/stage7"
NY = ZoneInfo("America/New_York")
PIP = 0.0001
TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5")


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_jsonl(path: Path):
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def last_csv_row(path: Path) -> dict:
    last = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            last = row
    if last is None:
        raise ValueError(f"No candles found: {path}")
    return last


def latest_market_state() -> dict:
    m1 = last_csv_row(DATA / "eurusd-m1-bid-2021-11-20-2026-11-20.csv")
    ts = datetime.fromtimestamp(int(m1["timestamp"]) / 1000, tz=timezone.utc)
    # The CSV timestamp is candle-open time; add one minute for its close/availability.
    available = ts + timedelta(minutes=1)
    return {"last_candle_open": ts.isoformat(), "as_of": available.isoformat(),
            "close": float(m1["close"]), "source": "EURUSD M1 BID"}


def next_weekday_session(as_of: datetime, now_utc: datetime | None = None) -> str:
    reference_day = as_of.astimezone(NY).date()
    if now_utc is not None:
        reference_day = max(reference_day, now_utc.astimezone(NY).date())
    day = reference_day + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def load_stage4(as_of: datetime, max_age_hours: float) -> tuple[dict | None, float | None]:
    latest = None
    for row in read_jsonl(STAGE4):
        stamp = parse_time(row["as_of"])
        if stamp <= as_of and (latest is None or stamp > parse_time(latest["as_of"])):
            latest = row
    if latest is None:
        return None, None
    age = (as_of - parse_time(latest["as_of"])).total_seconds() / 3600
    return latest, age


def load_swings(as_of: datetime, days: int = 90) -> list[dict]:
    floor = as_of - timedelta(days=days)
    rows = []
    for row in read_jsonl(SWINGS):
        available = parse_time(row["available_at"])
        if available <= as_of and available >= floor:
            if row.get("timeframe") in ("H4", "H1", "M15", "M5"):
                rows.append(row)
    rows.sort(key=lambda x: parse_time(x["available_at"]))
    return rows


def empirical_target(direction: str, swings: list[dict]) -> dict:
    # H1/H4 historical swing magnitudes in the same direction; no fixed Fib ratios.
    eligible = [float(x["length_pips"]) for x in swings
                if x["timeframe"] in ("H1", "H4") and x["direction"] == direction
                and float(x.get("length_pips", 0)) > 0]
    return {
        "method": "rolling 90-day empirical H1/H4 directional swing distribution",
        "sample_size": len(eligible),
        "p25_pips": round(percentile(eligible, 0.25), 1) if eligible else None,
        "median_pips": round(median(eligible), 1) if eligible else None,
        "p75_pips": round(percentile(eligible, 0.75), 1) if eligible else None,
    }


def invalidation_proxy(direction: str, swings: list[dict]) -> dict:
    # A mechanical nearby confirmed-swing boundary, explicitly not an Elliott rule invalidation.
    opposite = "down" if direction == "up" else "up"
    candidates = [x for x in swings if x["timeframe"] in ("H1", "H4")
                  and x["direction"] == opposite]
    if not candidates:
        return {"price": None, "method": "unavailable", "warning": "No confirmed opposing H1/H4 swing"}
    latest = max(candidates, key=lambda x: parse_time(x["available_at"]))
    price = float(latest["end_price"])
    return {
        "price": round(price, 5),
        "method": "latest confirmed opposing H1/H4 swing endpoint",
        "source_timeframe": latest["timeframe"],
        "source_available_at": latest["available_at"],
        "warning": "Technical reference only; not a verified Elliott rule invalidation level",
    }


def build_scenario(scenario: dict, snapshot: dict, swings: list[dict],
                   weak_index: dict, current_price: float) -> dict:
    direction = scenario.get("direction", "").lower()
    refs = scenario.get("candidate_refs", [])
    structures = []
    timeframes = set()
    hard_valid_count = 0
    for ref in refs:
        tf = ref.get("timeframe")
        if tf:
            timeframes.add(tf)
        key = (tf, ref.get("pattern"), ref.get("available_at"))
        label = weak_index.get(key)
        if label:
            hard_valid_count += int(bool(label.get("hard_valid")))
        structures.append({
            "timeframe": tf,
            "pattern": ref.get("pattern"),
            "available_at": ref.get("available_at"),
            "start_extreme_time": ref.get("start_extreme_time"),
            "end_extreme_time": ref.get("end_extreme_time"),
            "heuristic_score_not_probability": ref.get("reasoning_score_not_probability"),
            "weak_label_hard_valid": label.get("hard_valid") if label else None,
            "leg_lengths_pips": label.get("leg_lengths_pips") if label else None,
            "rule_reasons": label.get("rule_reasons") if label else [],
        })
    target = empirical_target(direction, swings)
    invalidation = invalidation_proxy(direction, swings)
    if direction == "up":
        target_zone = ([round(current_price + target["p25_pips"] * PIP, 5),
                        round(current_price + target["p75_pips"] * PIP, 5)]
                       if target["p25_pips"] is not None else None)
    else:
        target_zone = ([round(current_price - target["p75_pips"] * PIP, 5),
                        round(current_price - target["p25_pips"] * PIP, 5)]
                       if target["p25_pips"] is not None else None)
    return {
        "directional_bias": direction.upper(),
        "structure_type": "corrective_candidate" if any(
            x.get("pattern") in ("zigzag", "flat_candidate") for x in structures
        ) else "motive_or_other_candidate",
        "degree_hints": scenario.get("degree_hint", {}),
        "timeframes_represented": sorted(timeframes, key=lambda x: TIMEFRAMES.index(x) if x in TIMEFRAMES else 99),
        "candidate_count": len(structures),
        "aligned_parent_child_links": scenario.get("aligned_parent_child_links", 0),
        "mean_reasoning_score_not_probability": scenario.get("mean_reasoning_score_not_probability"),
        "hard_valid_candidate_refs_found": hard_valid_count,
        "structures": structures,
        "empirical_target_range": {
            **target,
            "price_zone": target_zone,
            "reference_price": round(current_price, 5),
        },
        "invalidation_reference": invalidation,
        "confidence": {
            "grade": "LOW",
            "numeric_probability": None,
            "semantics": "ordinal evidence grade only; not calibrated probability",
            "reason": "No independently validated Elliott ground truth or calibrated forward model exists.",
        },
    }


def generate(max_snapshot_age_hours: float = 6.0, now_utc: datetime | None = None) -> dict:
    market = latest_market_state()
    as_of = parse_time(market["as_of"])
    now_utc = now_utc or datetime.now(timezone.utc)
    data_age_hours = max(0.0, (now_utc - as_of).total_seconds() / 3600)
    snapshot, age = load_stage4(as_of, max_snapshot_age_hours)
    swings = load_swings(as_of)
    weak_index = {}
    for row in read_jsonl(WEAK):
        if parse_time(row["available_at"]) <= as_of:
            key = (row.get("timeframe"), row.get("pattern"), row.get("available_at"))
            weak_index[key] = row

    reasons = []
    if data_age_hours > 24:
        reasons.append("market_data_stale_over_24_hours")
    if snapshot is None:
        reasons.append("no_causal_stage4_snapshot_available")
    elif age is not None and age > max_snapshot_age_hours:
        reasons.append("stage4_snapshot_stale")
    if not swings:
        reasons.append("no_confirmed_recent_swings")
    if snapshot and snapshot.get("abstain"):
        reasons.extend(snapshot.get("abstain_reasons", []) or ["stage4_abstention"])
    if snapshot and int(snapshot.get("timeframes_represented", 0)) < 3:
        reasons.append("insufficient_multitimeframe_coverage")
    if snapshot and snapshot.get("conflicts"):
        reasons.append("multitimeframe_conflicts")

    scenarios = []
    if snapshot and age is not None and age <= max_snapshot_age_hours:
        for scenario in snapshot.get("scenarios", [])[:3]:
            scenarios.append(build_scenario(scenario, snapshot, swings, weak_index, market["close"]))
    # Daily report is intentionally conservative: any Stage-4 abstention or material
    # conflict makes the overall forecast abstain, while preserving scenario research.
    abstain = bool(reasons) or not scenarios
    return {
        "schema_version": 1,
        "symbol": "EURUSD",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "forecast_as_of_utc": market["as_of"],
        "forecast_for_next_ny_weekday_session": next_weekday_session(as_of, now_utc),
        "market_data_age_hours_at_generation": round(data_age_hours, 2),
        "market_data": market,
        "stage4_snapshot": {
            "as_of": snapshot.get("as_of") if snapshot else None,
            "age_hours": round(age, 2) if age is not None else None,
            "timeframes_represented": snapshot.get("timeframes_represented") if snapshot else 0,
            "candidate_count": snapshot.get("candidate_count") if snapshot else 0,
            "abstain": snapshot.get("abstain") if snapshot else True,
            "abstain_reasons": snapshot.get("abstain_reasons", []) if snapshot else [],
            "conflicts": snapshot.get("conflicts", []) if snapshot else [],
        },
        "decision": "ABSTAIN" if abstain else "SCENARIO_RESEARCH_ONLY",
        "abstain": abstain,
        "abstain_reasons": sorted(set(reasons)),
        "scenarios": scenarios,
        "swing_context": {
            "lookback_days": 90,
            "confirmed_swings_available": len(swings),
            "timeframes": sorted({x["timeframe"] for x in swings}),
            "target_method": "empirical historical swing quantiles; no fixed Fibonacci projection",
        },
        "safety": {
            "is_trade_signal": False,
            "probabilities_calibrated": False,
            "weak_labels_are_expert_truth": False,
            "invalidation_is_verified_elliott_rule": False,
            "causality": "Only Stage-4 snapshots and confirmed swings available at or before forecast_as_of_utc are used.",
            "warning": "Research scenario only. Do not use as an executable order or trading recommendation.",
        },
    }


def write_report(report: dict, output_dir: Path = OUT) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "daily_elliott_forecast.json"
    md_path = output_dir / "daily_elliott_forecast.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# EURUSD â€” Daily Elliott Forecast",
        "",
        f"- Generated UTC: {report['generated_at_utc']}",
        f"- Forecast as of: {report['forecast_as_of_utc']}",
        f"- Next NY weekday session: {report['forecast_for_next_ny_weekday_session']}",
        f"- Reference close: {report['market_data']['close']:.5f}",
        f"- Decision: **{report['decision']}**",
        "",
        "## Abstention / quality checks",
        "",
    ]
    lines += [f"- {x}" for x in report["abstain_reasons"]] or ["- No abstention reason recorded."]
    lines += ["", "## Elliott scenarios", ""]
    if not report["scenarios"]:
        lines.append("No scenario could be formed from available causal inputs.")
    for i, scenario in enumerate(report["scenarios"], 1):
        lines += [
            f"### Scenario {i}: {scenario['directional_bias']}",
            f"- Structure: {scenario['structure_type']}",
            f"- Timeframes: {', '.join(scenario['timeframes_represented'])}",
            f"- Candidate structures: {scenario['candidate_count']}",
            f"- Mean heuristic ranking (not probability): {scenario['mean_reasoning_score_not_probability']}",
            f"- Evidence grade: {scenario['confidence']['grade']}",
        ]
        zone = scenario["empirical_target_range"]["price_zone"]
        lines.append(f"- Empirical target zone: {zone if zone else 'unavailable'}")
        inv = scenario["invalidation_reference"]
        lines.append(f"- Invalidation reference: {inv['price'] if inv['price'] is not None else 'unavailable'} ({inv['warning']})")
        for structure in scenario["structures"]:
            lines.append(f"  - {structure['timeframe']} {structure['pattern']} available {structure['available_at']}; legs={structure['leg_lengths_pips']}")
        lines.append("")
    lines += [
        "## Interpretation and limitations",
        "",
        "This report preserves Stage-4 competing structures and does not assign calibrated probabilities. "
        "Target zones use empirical 90-day H1/H4 swing quantiles, not Fibonacci ratios. "
        "Invalidation references are mechanical opposing-swing boundaries, not verified Elliott rule invalidations. "
        "The current Stage-5 directional model has not demonstrated an edge over causal baselines; it is not used to override this structure report.",
        "",
        "A forecast marked ABSTAIN is not a bullish or bearish call. It means the evidence is insufficient or conflicting. "
        "Even when scenarios are shown, they remain research hypotheses rather than trading instructions.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the daily causal Elliott scenario report.")
    parser.add_argument("--max-snapshot-age-hours", type=float, default=6.0)
    args = parser.parse_args()
    report = generate(args.max_snapshot_age_hours)
    write_report(report)
    print(json.dumps({
        "decision": report["decision"],
        "as_of": report["forecast_as_of_utc"],
        "next_session": report["forecast_for_next_ny_weekday_session"],
        "scenario_count": len(report["scenarios"]),
        "abstain_reasons": report["abstain_reasons"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


import importlib.util
from datetime import datetime, timezone
from collections import deque
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_multitimeframe_reasoning.py"
spec = importlib.util.spec_from_file_location("multitimeframe_reasoning", MODULE_PATH)
mtr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mtr)


def candidate(tf="H4", direction="up", start="2026-01-01T00:00:00+00:00",
              end="2026-01-03T00:00:00+00:00", available="2026-01-03T01:00:00+00:00",
              score=70):
    return {
        "timeframe": tf, "direction": direction, "pattern": "impulse",
        "start_extreme_time": start, "end_extreme_time": end,
        "available_at": available, "hard_valid": True,
        "heuristic_score": score, "rule_reasons": [],
    }


def test_future_candidate_is_not_selected_by_causal_snapshot():
    now = datetime(2026, 1, 3, 2, tzinfo=timezone.utc)
    active = {tf: deque(maxlen=30) for tf in mtr.TIMEFRAMES}
    active["H4"].append(candidate(available="2026-01-03T03:00:00+00:00"))
    snap = mtr.build_snapshot(now, active, {})
    assert snap["candidate_count"] == 0
    assert "no_hard_valid_candidates" in snap["abstain_reasons"]


def test_parent_child_interval_requires_containment():
    parent = candidate("D1", start="2026-01-01T00:00:00+00:00", end="2026-01-10T00:00:00+00:00")
    child = candidate("H4", start="2026-01-02T00:00:00+00:00", end="2026-01-03T00:00:00+00:00")
    assert mtr.contains_interval(parent, child)
    assert not mtr.contains_interval(child, parent)
    assert mtr.intervals_overlap(parent, child)


def test_opposite_lower_timeframe_leg_is_not_automatically_conflict():
    now = datetime(2026, 1, 4, tzinfo=timezone.utc)
    active = {tf: deque(maxlen=30) for tf in mtr.TIMEFRAMES}
    active["D1"].append(candidate("D1", "up"))
    active["H4"].append(candidate("H4", "up"))
    active["H1"].append(candidate("H1", "down",
                                  start="2026-01-02T00:00:00+00:00",
                                  end="2026-01-02T12:00:00+00:00"))
    snap = mtr.build_snapshot(now, active, {})
    assert "higher_degree_D1_H4_conflict" not in snap["conflicts"]
    assert snap["timeframe_leaders"]["D1"]["direction"] == "up"


def test_higher_degree_conflict_is_flagged_and_abstained():
    now = datetime(2026, 1, 4, tzinfo=timezone.utc)
    active = {tf: deque(maxlen=30) for tf in mtr.TIMEFRAMES}
    active["D1"].append(candidate("D1", "up"))
    active["H4"].append(candidate("H4", "down"))
    snap = mtr.build_snapshot(now, active, {})
    assert "higher_degree_D1_H4_conflict" in snap["conflicts"]
    assert snap["abstain"]


def test_reasoning_score_is_bounded_and_not_a_probability():
    now = datetime(2026, 1, 4, tzinfo=timezone.utc)
    score = mtr._candidate_score(candidate(), now, None)
    assert 0 <= score <= 100

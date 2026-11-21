from datetime import datetime, timezone
from eurusd_ai.market_data import Candle
from Modules.Elliott_Waves.Training.walk_forward import session_cutoffs, build_labels, _timeframe_features


def test_ny_cutoffs_are_timezone_aware_and_skip_weekends():
    bars = [
        Candle("2026-06-01T20:55:00+00:00", 1.1, 1.101, 1.099, 1.1),
        Candle("2026-06-02T20:55:00+00:00", 1.1, 1.101, 1.099, 1.1),
    ]
    cutoffs = session_cutoffs(bars)
    assert len(cutoffs) == 2
    assert all(x.tzinfo is not None for x in cutoffs)
    assert cutoffs[0].isoformat() == "2026-06-01T21:00:00+00:00"


def test_labels_measure_only_the_next_completed_session():
    cutoffs = [
        datetime(2026, 6, 1, 21, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 2, 21, 0, tzinfo=timezone.utc),
    ]
    bars = [
        Candle("2026-06-01T20:55:00+00:00", 1.1000, 1.1005, 1.0995, 1.1000),
        Candle("2026-06-01T21:00:00+00:00", 1.1000, 1.1010, 1.0990, 1.1005),
        Candle("2026-06-02T20:55:00+00:00", 1.1005, 1.1020, 1.1000, 1.1015),
    ]
    labels = build_labels({"M5": bars}, cutoffs)
    assert labels[0] is not None
    assert abs(labels[0]["close_return_pips"] - 15.0) < 1e-6
    assert abs(labels[0]["high_excursion_pips"] - 20.0) < 1e-6
    assert abs(labels[0]["low_excursion_pips"] + 10.0) < 1e-6
    assert labels[1] is None


def test_timeframe_features_are_finite():
    bars = [
        Candle(f"2026-06-01T{hour:02d}:00:00+00:00", 1.1 + hour * 0.0001,
               1.1002 + hour * 0.0001, 1.0998 + hour * 0.0001,
               1.1001 + hour * 0.0001)
        for hour in range(1, 20)
    ]
    features = _timeframe_features("H1", bars)
    assert features["h1_ret1"] > 0
    assert all(value == value and abs(value) != float("inf") for value in features.values())


import json
from datetime import datetime, timezone
from Modules.Elliott_Waves.Training.walk_forward import add_stage4_reasoning_features


def test_stage4_join_never_uses_future_snapshot(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    snapshots = [
        {"as_of": "2026-06-01T20:00:00+00:00", "timeframes_represented": 3,
         "candidate_count": 5, "abstain": False, "conflicts": [],
         "scenarios": [{"direction": "up", "timeframes_represented": 3,
                        "mean_reasoning_score_not_probability": 72,
                        "aligned_parent_child_links": 2}],
         "timeframe_leaders": {"D1": {"direction": "up"}}},
        {"as_of": "2026-06-01T22:00:00+00:00", "timeframes_represented": 5,
         "candidate_count": 9, "abstain": False, "conflicts": [],
         "scenarios": [{"direction": "down", "timeframes_represented": 4,
                        "mean_reasoning_score_not_probability": 81,
                        "aligned_parent_child_links": 1}],
         "timeframe_leaders": {"D1": {"direction": "down"}}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in snapshots), encoding="utf-8")
    features = [{}]
    cutoffs = [datetime(2026, 6, 1, 21, 0, tzinfo=timezone.utc)]
    add_stage4_reasoning_features(features, cutoffs, path)
    assert features[0]["stage4_timeframes_represented"] == 3
    assert features[0]["stage4_up_score"] == 72
    assert features[0]["stage4_down_score"] == 0
    assert features[0]["stage4_d1_direction"] == 1


def test_stage4_stale_snapshot_is_marked_unavailable(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    item = {"as_of": "2026-05-20T00:00:00+00:00", "timeframes_represented": 5,
            "candidate_count": 10, "abstain": False, "conflicts": [],
            "scenarios": [], "timeframe_leaders": {}}
    path.write_text(json.dumps(item), encoding="utf-8")
    features = [{}]
    cutoffs = [datetime(2026, 6, 1, 21, 0, tzinfo=timezone.utc)]
    add_stage4_reasoning_features(features, cutoffs, path)
    assert features[0]["stage4_snapshot_available"] == 0
    assert features[0]["stage4_abstain"] == 1
    assert features[0]["stage4_timeframes_represented"] == 0


def test_stage4_no_snapshot_is_safe(tmp_path):
    features = [{}]
    cutoffs = [datetime(2026, 6, 1, 21, 0, tzinfo=timezone.utc)]
    add_stage4_reasoning_features(features, cutoffs, tmp_path / "missing.jsonl")
    assert features[0]["stage4_snapshot_available"] == 0
    assert features[0]["stage4_up_score"] == 0

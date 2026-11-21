import math
from scripts.train_elliott_ai import FEATURE_NAMES, make_features


def test_elliott_candidate_feature_vector_is_finite_and_fixed_width():
    row = {
        "timeframe": "M5", "direction": "up",
        "leg_lengths_pips": [20.0, 10.0, 30.0],
        "pivot_extreme_times": [
            "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00",
            "2026-01-01T02:00:00+00:00", "2026-01-01T03:00:00+00:00"
        ]
    }
    values = make_features(row)
    assert len(values) == len(FEATURE_NAMES)
    assert all(math.isfinite(x) for x in values)
    assert values[0] == 1.0
    assert values[1] == 1.0


def test_elliott_candidate_features_encode_direction_and_leg_count():
    row = {
        "timeframe": "H1", "direction": "down",
        "leg_lengths_pips": [10.0, 5.0, 20.0, 7.0, 12.0],
        "pivot_extreme_times": [
            "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00",
            "2026-01-01T02:00:00+00:00", "2026-01-01T03:00:00+00:00",
            "2026-01-01T04:00:00+00:00", "2026-01-01T05:00:00+00:00"
        ]
    }
    values = make_features(row)
    assert values[0] == 3.0
    assert values[1] == -1.0
    assert values[2] == 5.0

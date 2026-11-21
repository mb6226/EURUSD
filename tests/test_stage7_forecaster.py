from datetime import datetime, timezone

import scripts.daily_elliott_forecaster as stage7


def test_next_ny_weekday_uses_today_not_stale_market_date():
    as_of = datetime(2026, 11, 19, 23, 59, tzinfo=timezone.utc)
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    assert stage7.next_weekday_session(as_of, now) == "2026-11-23"


def test_empirical_target_uses_directional_h1_h4_swings_only():
    swings = [
        {"timeframe": "H1", "direction": "down", "length_pips": 20},
        {"timeframe": "H4", "direction": "down", "length_pips": 40},
        {"timeframe": "M5", "direction": "down", "length_pips": 900},
        {"timeframe": "H1", "direction": "up", "length_pips": 700},
    ]
    target = stage7.empirical_target("down", swings)
    assert target["sample_size"] == 2
    assert target["median_pips"] == 30.0
    assert target["p25_pips"] == 25.0
    assert target["p75_pips"] == 35.0


def test_invalidation_uses_latest_opposing_confirmed_swing():
    swings = [
        {"timeframe": "H1", "direction": "up", "end_price": 1.105, "available_at": "2026-11-18T12:00:00+00:00"},
        {"timeframe": "H4", "direction": "up", "end_price": 1.108, "available_at": "2026-11-19T12:00:00+00:00"},
        {"timeframe": "M5", "direction": "up", "end_price": 1.2, "available_at": "2026-11-19T13:00:00+00:00"},
    ]
    result = stage7.invalidation_proxy("down", swings)
    assert result["price"] == 1.108
    assert result["source_timeframe"] == "H4"


def test_load_stage4_never_uses_future_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "stage4.jsonl"
    path.write_text(
        '{"as_of":"2026-11-20T10:00:00+00:00"}\n'
        '{"as_of":"2026-11-20T12:00:00+00:00"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(stage7, "STAGE4", path)
    snapshot, age = stage7.load_stage4(
        datetime(2026, 11, 20, 11, 0, tzinfo=timezone.utc), 6
    )
    assert snapshot["as_of"] == "2026-11-20T10:00:00+00:00"
    assert age == 1.0


def test_stale_market_data_forces_abstention_and_keeps_scenarios(monkeypatch):
    as_of = datetime(2026, 11, 19, 23, 59, tzinfo=timezone.utc)
    now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    snapshot = {
        "as_of": "2026-11-19T21:25:00+00:00",
        "timeframes_represented": 4,
        "candidate_count": 1,
        "abstain": False,
        "abstain_reasons": [],
        "conflicts": [],
        "scenarios": [{
            "direction": "down",
            "degree_hint": {},
            "candidate_refs": [],
            "mean_reasoning_score_not_probability": 50,
            "aligned_parent_child_links": 0,
        }],
    }
    monkeypatch.setattr(stage7, "latest_market_state", lambda: {
        "last_candle_open": "2026-11-19T23:58:00+00:00",
        "as_of": as_of.isoformat(),
        "close": 1.09668,
        "source": "test",
    })
    monkeypatch.setattr(stage7, "load_stage4", lambda *_: (snapshot, 2.57))
    monkeypatch.setattr(stage7, "load_swings", lambda *_: [
        {"timeframe": "H1", "direction": "down", "length_pips": 20,
         "available_at": as_of.isoformat(), "start_price": 1.1, "end_price": 1.098}
    ])
    monkeypatch.setattr(stage7, "read_jsonl", lambda *_: iter([]))
    report = stage7.generate(now_utc=now)
    assert report["decision"] == "ABSTAIN"
    assert "market_data_stale_over_24_hours" in report["abstain_reasons"]
    assert report["forecast_for_next_ny_weekday_session"] == "2026-11-23"
    assert len(report["scenarios"]) == 1

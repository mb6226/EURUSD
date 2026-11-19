from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from eurusd_ai_monitor.engines.deterministic_historical_specialist_replay_engine import (
    DeterministicHistoricalSpecialistReplayEngine,
)


UTC = timezone.utc
AS_OF = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)


class StubReconstruction:
    def __init__(self):
        self.calls = []

    def reconstruct(self, **kwargs):
        self.calls.append(kwargs)
        timeframe = kwargs["timeframe"]
        rows = []
        for index in range(40):
            opened = AS_OF - timedelta(seconds=(40 - index) * (60 if timeframe == "M1" else 300))
            rows.append({
                "candle_open_time_utc": opened.isoformat(),
                "open": "1.1000", "high": "1.1005", "low": "1.0995",
                "close": "1.1002", "tick_volume": 10, "spread": 0,
                "real_volume": 0, "first_seen_at_utc": (opened + timedelta(seconds=60 if timeframe == "M1" else 300)).isoformat(),
                "last_seen_at_utc": AS_OF.isoformat(),
            })
        return {
            "status": "PARTIAL", "as_of_utc": AS_OF.isoformat(),
            "market_candles": {"status": "AVAILABLE", "candles": rows},
            "news": {"status": "NOT_CONFIGURED", "items": []},
            "macro_calendar": {"status": "NOT_CONFIGURED", "events": []},
        }


class StubTechnical:
    def analyze_snapshot(self, snapshot):
        trend = SimpleNamespace(
            direction=SimpleNamespace(value="UP"),
            confirmed_at_utc=AS_OF - timedelta(minutes=5),
        )
        return SimpleNamespace(
            trend=trend, evaluated_at_utc=snapshot.timestamp_utc,
            algorithm_version="stub-tech-v1", parameter_version="stub-params",
            pivots=(), protected_swing_break=None,
        )


def test_replay_reconstructs_both_timeframes_and_reexecutes_specialists():
    reconstruction = StubReconstruction()
    engine = DeterministicHistoricalSpecialistReplayEngine(
        reconstruction, technical_engine=StubTechnical(), pip_size=Decimal("0.0001")
    )

    result = engine.replay(
        [{"evaluated_at_utc": AS_OF.isoformat()}],
        broker_server="Broker-Demo", symbol="EURUSD",
        start_utc=AS_OF - timedelta(hours=2), end_utc=AS_OF,
    )

    assert result["replay_points_processed"] == 1
    assert [call["timeframe"] for call in reconstruction.calls] == ["M1", "M5"]
    point = result["points"][0]
    assert point["market_snapshot_quality"]["is_valid"] is True
    assert point["specialist_reports"]["technical_analysis"]["reexecution_status"] == "REEXECUTED"
    assert point["specialist_reports"]["technical_analysis"]["trend"]["direction"] == "UP"
    assert point["specialist_reports"]["quantitative_market_statistics"]["reexecution_status"] == "REEXECUTED"
    assert point["historical_specialists_recomputed"] is True
    assert point["specialists_not_recomputed"]["price_action_lifecycle"] == "STATEFUL_LIFECYCLE_REPLAY_NOT_YET_SUPPORTED"
    assert point["scenario_assessment"]["scenario_hypotheses"][0]["scenario_id"] == "EURUSD_UP_CONTINUATION"


def test_replay_rejects_future_and_malformed_points_without_reconstruction():
    reconstruction = StubReconstruction()
    engine = DeterministicHistoricalSpecialistReplayEngine(
        reconstruction, technical_engine=StubTechnical()
    )
    future = datetime.now(UTC) + timedelta(days=1)
    result = engine.replay(
        [{"evaluated_at_utc": future.isoformat()}, {"bad": "point"}],
        broker_server="Broker-Demo", symbol="EURUSD",
        start_utc=AS_OF, end_utc=future,
    )
    assert result["replay_points_processed"] == 0
    assert result["rejected_counts"]
    assert reconstruction.calls == []


def test_snapshot_does_not_claim_quality_when_a_timeframe_is_missing():
    report = {
        "market_candles": {"status": "UNAVAILABLE", "candles": []}
    }
    snapshot = DeterministicHistoricalSpecialistReplayEngine._snapshot(
        report, report, AS_OF, "Broker-Demo", "EURUSD"
    )
    assert snapshot.quality.is_valid is False
    assert set(snapshot.quality.issues) == {
        "M1_POINT_IN_TIME_CANDLES_UNAVAILABLE",
        "M5_POINT_IN_TIME_CANDLES_UNAVAILABLE",
    }


def test_candle_reconstruction_preserves_values_and_identity():
    row = {
        "market_candles": {
            "status": "AVAILABLE",
            "candles": [{
                "candle_open_time_utc": AS_OF.isoformat(),
                "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15",
                "tick_volume": 7, "spread": 2, "real_volume": 0,
            }],
        }
    }
    candles = DeterministicHistoricalSpecialistReplayEngine._candles(
        row, "M5", "Broker-Demo", "EURUSD"
    )
    assert len(candles) == 1
    assert candles[0].close == Decimal("1.15")
    assert candles[0].timeframe == "M5"
    assert candles[0].broker_server == "Broker-Demo"


from datetime import timedelta
from decimal import Decimal

from eurusd_ai_monitor.storage.market_data_store import Candle
from eurusd_ai_monitor.engines.deterministic_historical_specialist_replay_engine import (
    DeterministicHistoricalSpecialistReplayEngine,
)


def test_liquidity_retrieval_uses_first_observation_that_proves_bar_closed():
    candle = Candle(
        broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
        candle_open_time_utc=AS_OF - timedelta(minutes=1),
        open=Decimal("1.1"), high=Decimal("1.2"), low=Decimal("1.0"),
        close=Decimal("1.15"), tick_volume=1, spread=0, real_volume=0,
    )
    first_seen = AS_OF
    later_refresh = AS_OF + timedelta(days=1)
    report = {"market_candles": {"candles": [{
        "candle_open_time_utc": candle.candle_open_time_utc.isoformat(),
        "first_seen_at_utc": first_seen.isoformat(),
        "last_seen_at_utc": later_refresh.isoformat(),
    }]}}
    retrieved = DeterministicHistoricalSpecialistReplayEngine._retrieved_at(
        candle, report, report
    )
    assert retrieved == first_seen
    assert retrieved <= AS_OF



def test_snapshot_marks_stale_historical_bars_invalid():
    stale_m1 = AS_OF - timedelta(minutes=10)
    stale_m5 = AS_OF - timedelta(minutes=30)
    def report(opened, timeframe):
        duration = 60 if timeframe == "M1" else 300
        candle = {
            "candle_open_time_utc": opened.isoformat(),
            "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15",
            "tick_volume": 1, "spread": 0, "real_volume": 0,
            "first_seen_at_utc": (opened + timedelta(seconds=duration)).isoformat(),
            "last_seen_at_utc": AS_OF.isoformat(),
        }
        return {"market_candles": {"status": "AVAILABLE", "candles": [candle]}}
    snapshot = DeterministicHistoricalSpecialistReplayEngine._snapshot(
        report(stale_m1, "M1"), report(stale_m5, "M5"),
        AS_OF, "Broker-Demo", "EURUSD",
    )
    assert snapshot.quality.is_valid is False
    assert "M1_HISTORICAL_CANDLE_WINDOW_STALE" in snapshot.quality.issues
    assert "M5_HISTORICAL_CANDLE_WINDOW_STALE" in snapshot.quality.issues


def test_writable_observation_store_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="read-only"):
        DeterministicHistoricalSpecialistReplayEngine(
            StubReconstruction(), technical_engine=StubTechnical(),
            observation_store=SimpleNamespace(_read_only=False),
        )



def test_invalid_market_snapshot_blocks_all_specialist_reexecution():
    class StaleReconstruction(StubReconstruction):
        def reconstruct(self, **kwargs):
            report = super().reconstruct(**kwargs)
            for row in report["market_candles"]["candles"]:
                opened = datetime.fromisoformat(row["candle_open_time_utc"])
                row["candle_open_time_utc"] = (opened - timedelta(hours=1)).isoformat()
            return report

    class CountingTechnical(StubTechnical):
        def __init__(self):
            self.calls = 0

        def analyze_snapshot(self, snapshot):
            self.calls += 1
            return super().analyze_snapshot(snapshot)

    technical = CountingTechnical()
    engine = DeterministicHistoricalSpecialistReplayEngine(
        StaleReconstruction(), technical_engine=technical
    )
    result = engine.replay(
        [{"evaluated_at_utc": AS_OF.isoformat()}],
        broker_server="Broker-Demo", symbol="EURUSD",
        start_utc=AS_OF - timedelta(hours=2), end_utc=AS_OF,
    )

    point = result["points"][0]
    assert point["market_snapshot_quality"]["is_valid"] is False
    assert technical.calls == 0
    assert all(
        report["reexecution_status"] == "BLOCKED_QUALITY_GATE"
        for report in point["specialist_reports"].values()
    )
    assert point["scenario_assessment"]["directional_assessment"]["state"] == "UNRESOLVED"

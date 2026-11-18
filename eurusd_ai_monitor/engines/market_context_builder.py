from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from eurusd_ai_monitor.engines.mt5_engine import MT5Connector
from eurusd_ai_monitor.storage.market_data_store import MarketDataStore, TIMEFRAME_SECONDS
from eurusd_ai_monitor.storage.mt5_market_adapter import MT5MarketDataAdapter
from eurusd_ai_monitor.models.context_quality import ContextQuality
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot


class MarketContextBuilder:
    """Syncs the latest MT5 bars into the store and builds a shared snapshot."""

    DEFAULT_TIMEFRAMES = ("M1", "M5")

    def __init__(
        self,
        connector: MT5Connector,
        store: MarketDataStore,
        adapter: MT5MarketDataAdapter,
        *,
        clock: Callable[[], datetime] | None = None,
        minimum_candles: int = 3,
        max_age_seconds: dict[str, int] | None = None,
    ) -> None:
        if isinstance(minimum_candles, bool) or not isinstance(minimum_candles, int) or minimum_candles < 1:
            raise ValueError("minimum_candles must be a positive integer")
        age_limits = dict(max_age_seconds or {"M1": 180, "M5": 900})
        if any(
            not isinstance(tf, str)
            or tf not in TIMEFRAME_SECONDS
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for tf, value in age_limits.items()
        ):
            raise ValueError("max_age_seconds must contain supported timeframes and non-negative integer limits")
        self._connector = connector
        self._store = store
        self._adapter = adapter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._minimum_candles = minimum_candles
        self._max_age_seconds = age_limits

    @staticmethod
    def _utc(value: datetime, name: str) -> datetime:
        if not isinstance(value, datetime):
            raise TypeError(f"{name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")
        return value.astimezone(timezone.utc)

    def build(
        self,
        *,
        timeframes: Iterable[str] = DEFAULT_TIMEFRAMES,
        count: int = 300,
    ) -> MarketSnapshot:
        frames = tuple(timeframes)
        if frames != self.DEFAULT_TIMEFRAMES:
            raise ValueError("MarketSnapshot requires timeframes exactly ('M1', 'M5')")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("count must be a positive integer")

        now = self._utc(self._clock(), "clock")
        issues: list[str] = []
        warnings: list[str] = []
        try:
            self._adapter.sync_latest(timeframes=frames, count=count, as_of_utc=now)
        except Exception as exc:
            issues.append(f"Market data sync failed: {type(exc).__name__}: {exc}")

        symbol = self._connector.symbol
        try:
            broker_server = self._connector.broker_server()
        except Exception as exc:
            broker_server = "UNKNOWN"
            issues.append(f"Broker server unavailable: {type(exc).__name__}: {exc}")

        candles_by_tf = {}
        counts = {}
        last_times = {}
        missing = []
        for timeframe in frames:
            try:
                candles = self._store.get_closed_candles(
                    broker_server, symbol, timeframe, limit=count
                )
            except Exception as exc:
                candles = []
                issues.append(f"{timeframe} candle query failed: {type(exc).__name__}: {exc}")
            candles_by_tf[timeframe] = tuple(candles)
            counts[timeframe] = len(candles)
            last_close_time = (
                candles[-1].candle_open_time_utc
                + timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
                if candles
                else None
            )
            last_times[timeframe] = last_close_time
            if len(candles) < self._minimum_candles:
                missing.append(timeframe)
                issues.append(
                    f"{timeframe} has {len(candles)} closed candles; "
                    f"minimum is {self._minimum_candles}"
                )
            if last_close_time is not None:
                age = (now - last_close_time).total_seconds()
                max_age = self._max_age_seconds.get(timeframe)
                if age < 0:
                    issues.append(f"{timeframe} latest closed candle is in the future")
                elif max_age is not None and age > max_age:
                    issues.append(
                        f"{timeframe} data is stale ({age:.0f}s; max {max_age}s)"
                    )

        try:
            tick = self._connector.tick()
            spread = Decimal(str(tick.get("spread_pips"))) if tick.get("spread_pips") is not None else None
            if spread is not None and (not spread.is_finite() or spread < 0):
                raise ValueError("tick spread must be finite and non-negative")
        except Exception as exc:
            tick = None
            spread = None
            warnings.append(f"Tick unavailable: {type(exc).__name__}: {exc}")

        relevant_last_times = [v for v in last_times.values() if v is not None]
        last_candle_time = max(relevant_last_times) if relevant_last_times else None
        data_age = (
            (now - last_candle_time).total_seconds()
            if last_candle_time is not None and (now - last_candle_time).total_seconds() >= 0
            else None
        )
        quality = ContextQuality(
            is_valid=not issues,
            issues=tuple(issues),
            warnings=tuple(warnings),
            last_candle_time=last_candle_time,
            data_age_seconds=data_age,
            missing_timeframes=tuple(missing),
            candle_counts=counts,
            timeframe_last_candle_times=last_times,
        )
        return MarketSnapshot(
            symbol=symbol,
            timestamp_utc=now,
            broker_server=broker_server,
            m1_candles=candles_by_tf.get("M1", ()),
            m5_candles=candles_by_tf.get("M5", ()),
            tick=tick,
            spread_pips=spread,
            quality=quality,
        )

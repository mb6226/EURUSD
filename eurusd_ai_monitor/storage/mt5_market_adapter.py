from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum

from eurusd_ai_monitor.engines.mt5_engine import MT5Connector

from .market_data_store import (
    Candle,
    MarketDataStore,
    TIMEFRAME_SECONDS,
    UpsertSummary,
)

_REQUIRED_RATE_FIELDS = {
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
}


class MT5MarketDataError(RuntimeError):
    """Raised when MT5 data cannot be safely normalized or stored."""


class BackfillStatus(str, Enum):
    COMPLETE = "complete"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MT5SyncResult:
    broker_server: str
    symbol: str
    timeframes: tuple[str, ...]
    records_received: int
    observed_at_utc: datetime
    store_summary: UpsertSummary


@dataclass(frozen=True)
class MT5BackfillResult:
    broker_server: str
    symbol: str
    timeframes: tuple[str, ...]
    start_utc: datetime
    end_utc: datetime
    chunks_processed: int
    records_received: int
    store_summary: UpsertSummary
    completed: bool
    status: BackfillStatus


class MT5MarketDataAdapter:
    """Maps data from an existing MT5Connector to the independent market store."""

    def __init__(
        self,
        connector: MT5Connector,
        store: MarketDataStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connector = connector
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def sync_latest(
        self,
        *,
        timeframes: Iterable[str] = ("M1", "M5"),
        count: int = 300,
        as_of_utc: datetime | None = None,
    ) -> MT5SyncResult:
        frames = self._validate_timeframes(timeframes)
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("count must be a positive integer")
        symbol = self._connected_symbol()
        broker_server = self._broker_server()

        candles: list[Candle] = []
        for timeframe in frames:
            try:
                rates = self._connector.bars(timeframe, count)
            except Exception as exc:
                raise MT5MarketDataError(
                    f"Failed to fetch {timeframe} bars from MT5"
                ) from exc
            candles.extend(
                self._candles_from_frame(rates, broker_server, symbol, timeframe)
            )

        observed_at = self._now_utc()
        effective_as_of = (
            _utc_datetime(as_of_utc, "as_of_utc")
            if as_of_utc is not None
            else observed_at
        )
        summary = self._store.upsert_candles(
            candles,
            as_of_utc=effective_as_of,
            observed_at_utc=observed_at,
            source_id="MT5_COPY_RATES",
            provenance={
                "provider": "MetaTrader5 Python integration",
                "method": "copy_rates_from_pos",
                "broker_server": broker_server,
                "symbol": symbol,
                "timeframes": list(frames),
                "bar_time_basis": "UTC",
                "price_basis": self._price_basis_metadata(),
            },
        )
        return MT5SyncResult(
            broker_server=broker_server,
            symbol=symbol,
            timeframes=frames,
            records_received=len(candles),
            observed_at_utc=observed_at,
            store_summary=summary,
        )

    def backfill(
        self,
        start_utc: datetime,
        end_utc: datetime,
        *,
        timeframes: Iterable[str] = ("M1", "M5"),
        chunk_days: int = 7,
    ) -> MT5BackfillResult:
        start = _utc_datetime(start_utc, "start_utc")
        end = _utc_datetime(end_utc, "end_utc")
        if start >= end:
            raise ValueError("start_utc must be earlier than end_utc")
        if isinstance(chunk_days, bool) or not isinstance(chunk_days, int):
            raise TypeError("chunk_days must be an integer")
        if chunk_days <= 0:
            raise ValueError("chunk_days must be positive")

        frames = self._validate_timeframes(timeframes)
        symbol = self._connected_symbol()
        broker_server = self._broker_server()
        chunk_size = timedelta(days=chunk_days)
        totals = _SummaryTotals()
        chunks_processed = 0
        records_received = 0

        for timeframe in frames:
            checkpoint = self._store.get_backfill_checkpoint(
                broker_server,
                symbol,
                timeframe,
                start,
                end,
            )
            if checkpoint is None:
                checkpoint = self._store.save_backfill_checkpoint(
                    broker_server,
                    symbol,
                    timeframe,
                    start,
                    end,
                    start,
                    is_complete=False,
                    updated_at_utc=self._now_utc(),
                )
            if checkpoint.is_complete:
                continue

            cursor = checkpoint.next_from_utc
            while cursor < end:
                chunk_end = min(cursor + chunk_size, end)
                try:
                    rates = self._connector.bars_range(
                        timeframe,
                        cursor,
                        chunk_end,
                    )
                except Exception as exc:
                    raise MT5MarketDataError(
                        f"Failed to fetch {timeframe} backfill chunk "
                        f"{cursor.isoformat()}..{chunk_end.isoformat()}"
                    ) from exc

                batch = self._candles_from_frame(
                    rates,
                    broker_server,
                    symbol,
                    timeframe,
                    allow_empty=True,
                )
                if any(
                    candle.candle_open_time_utc < cursor
                    or candle.candle_open_time_utc > chunk_end
                    for candle in batch
                ):
                    raise MT5MarketDataError(
                        "MT5 returned a candle outside the requested backfill chunk"
                    )
                batch = [
                    candle
                    for candle in batch
                    if candle.candle_open_time_utc < chunk_end
                ]
                if not self._has_contiguous_coverage(
                    batch,
                    cursor,
                    chunk_end,
                    timeframe,
                ):
                    return MT5BackfillResult(
                        broker_server=broker_server,
                        symbol=symbol,
                        timeframes=frames,
                        start_utc=start,
                        end_utc=end,
                        chunks_processed=chunks_processed,
                        records_received=records_received,
                        store_summary=totals.result(),
                        completed=False,
                        status=BackfillStatus.UNKNOWN,
                    )

                observed_at = self._now_utc()
                chunk_summary = self._store.upsert_candles(
                    batch,
                    as_of_utc=observed_at,
                    observed_at_utc=observed_at,
                    source_id="MT5_COPY_RATES_RANGE",
                    provenance={
                        "provider": "MetaTrader5 Python integration",
                        "method": "copy_rates_range",
                        "broker_server": broker_server,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "requested_start_utc": cursor.isoformat(),
                        "requested_end_utc_exclusive": chunk_end.isoformat(),
                        "chunk_days": chunk_days,
                        "bar_time_basis": "UTC",
                        "price_basis": self._price_basis_metadata(),
                    },
                )
                totals.add(chunk_summary)
                records_received += len(batch)
                chunks_processed += 1

                cursor = chunk_end
                self._store.save_backfill_checkpoint(
                    broker_server,
                    symbol,
                    timeframe,
                    start,
                    end,
                    cursor,
                    is_complete=cursor >= end,
                    updated_at_utc=observed_at,
                )

        return MT5BackfillResult(
            broker_server=broker_server,
            symbol=symbol,
            timeframes=frames,
            start_utc=start,
            end_utc=end,
            chunks_processed=chunks_processed,
            records_received=records_received,
            store_summary=totals.result(),
            completed=True,
            status=BackfillStatus.COMPLETE,
        )

    def _connected_symbol(self) -> str:
        if not getattr(self._connector, "connected", False):
            raise MT5MarketDataError("MT5 connector is not connected")
        symbol = getattr(self._connector, "symbol", None)
        if not isinstance(symbol, str) or not symbol.strip():
            raise MT5MarketDataError("Connected MT5 connector has no symbol")
        return symbol.strip()

    def _broker_server(self) -> str:
        try:
            server = self._connector.broker_server()
        except Exception as exc:
            raise MT5MarketDataError(
                "Unable to identify broker server from the active MT5 connection"
            ) from exc
        if not isinstance(server, str) or not server.strip():
            raise MT5MarketDataError(
                "Active MT5 connection returned an empty broker server"
            )
        return server.strip()

    def _price_basis_metadata(self) -> dict[str, object]:
        reader = getattr(self._connector, "market_data_metadata", None)
        if not callable(reader):
            return {"price_basis": "UNKNOWN", "reason": "connector_metadata_unavailable"}
        try:
            metadata = reader()
        except Exception as exc:
            return {"price_basis": "UNKNOWN", "reason": type(exc).__name__}
        if not isinstance(metadata, Mapping):
            return {"price_basis": "UNKNOWN", "reason": "invalid_connector_metadata"}
        return dict(metadata)

    def _now_utc(self) -> datetime:
        return _utc_datetime(self._clock(), "clock")

    @staticmethod
    def _validate_timeframes(timeframes: Iterable[str]) -> tuple[str, ...]:
        if isinstance(timeframes, str):
            raise TypeError("timeframes must be an iterable of timeframe names")
        frames = tuple(timeframes)
        if not frames:
            raise ValueError("at least one timeframe is required")
        if any(not isinstance(frame, str) for frame in frames):
            raise TypeError("timeframe names must be strings")
        if len(set(frames)) != len(frames):
            raise ValueError("timeframes must not contain duplicates")
        unsupported = [frame for frame in frames if frame not in TIMEFRAME_SECONDS]
        if unsupported:
            raise ValueError(f"Unsupported timeframe(s): {unsupported!r}")
        return frames

    @classmethod
    def _candles_from_frame(
        cls,
        rates: object,
        broker_server: str,
        symbol: str,
        timeframe: str,
        *,
        allow_empty: bool = False,
    ) -> list[Candle]:
        columns = getattr(rates, "columns", None)
        if columns is None:
            raise MT5MarketDataError(
                f"MT5 {timeframe} response is not a tabular rates object"
            )
        missing = _REQUIRED_RATE_FIELDS.difference(columns)
        if missing:
            raise MT5MarketDataError(
                f"MT5 {timeframe} response is missing fields: "
                + ", ".join(sorted(missing))
            )
        try:
            rows = rates.to_dict(orient="records")
        except (AttributeError, TypeError, ValueError) as exc:
            raise MT5MarketDataError(
                f"Unable to read MT5 {timeframe} rates"
            ) from exc
        if not rows:
            if allow_empty:
                return []
            raise MT5MarketDataError(
                f"MT5 returned no {timeframe} candle records"
            )

        candles: list[Candle] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise MT5MarketDataError(
                    f"MT5 {timeframe} row {index} is not a mapping"
                )
            try:
                candle = Candle(
                    broker_server=broker_server,
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_open_time_utc=_row_datetime(row["time"]),
                    open=_row_decimal(row["open"], "open"),
                    high=_row_decimal(row["high"], "high"),
                    low=_row_decimal(row["low"], "low"),
                    close=_row_decimal(row["close"], "close"),
                    tick_volume=_row_integer(row["tick_volume"], "tick_volume"),
                    spread=_row_integer(row["spread"], "spread"),
                    real_volume=_row_integer(row["real_volume"], "real_volume"),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise MT5MarketDataError(
                    f"Invalid MT5 {timeframe} candle at row {index}: {exc}"
                ) from exc
            candles.append(candle)
        return candles

    @staticmethod
    def _has_contiguous_coverage(
        candles: list[Candle],
        start_utc: datetime,
        end_utc: datetime,
        timeframe: str,
    ) -> bool:
        if not candles:
            return False

        interval = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
        first_open = _first_open_at_or_after(start_utc, interval)
        last_open = _last_open_before(end_utc, interval)
        if first_open > last_open:
            return False

        by_time: dict[datetime, Candle] = {}
        for candle in candles:
            previous = by_time.get(candle.candle_open_time_utc)
            if previous is not None and previous != candle:
                raise MT5MarketDataError(
                    "Conflicting MT5 candles share the same open time"
                )
            by_time[candle.candle_open_time_utc] = candle

        times = sorted(by_time)
        if times[0] != first_open or times[-1] != last_open:
            return False
        return all(
            right - left == interval
            for left, right in zip(times, times[1:])
        )


def _utc_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _first_open_at_or_after(value: datetime, interval: timedelta) -> datetime:
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    slots, remainder = divmod(delta, interval)
    if remainder:
        slots += 1
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + slots * interval


def _last_open_before(value: datetime, interval: timedelta) -> datetime:
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    if delta.microseconds == 0:
        delta -= timedelta(microseconds=1)
    slots = delta // interval
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + slots * interval


def _row_datetime(value: object) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError("time must be a datetime")
    return _utc_datetime(value, "time")


def _row_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} is not a decimal value") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _row_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} is not an integer value") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"{field_name} must be a finite integer")
    result = int(number)
    if result < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return result


class _SummaryTotals:
    def __init__(self) -> None:
        self.inserted = 0
        self.updated = 0
        self.unchanged = 0
        self.revisions_recorded = 0
        self.duplicates_ignored = 0

    def add(self, summary: UpsertSummary) -> None:
        self.inserted += summary.inserted
        self.updated += summary.updated
        self.unchanged += summary.unchanged
        self.revisions_recorded += summary.revisions_recorded
        self.duplicates_ignored += summary.duplicates_ignored

    def result(self) -> UpsertSummary:
        return UpsertSummary(
            inserted=self.inserted,
            updated=self.updated,
            unchanged=self.unchanged,
            revisions_recorded=self.revisions_recorded,
            duplicates_ignored=self.duplicates_ignored,
        )

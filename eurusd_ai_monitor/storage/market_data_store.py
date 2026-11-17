from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3


TIMEFRAME_SECONDS = {"M1": 60, "M5": 300}
DEFAULT_MARKET_DATA_DB_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "market"
    / "market_data.sqlite"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    broker_server TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK (timeframe IN ('M1', 'M5')),
    candle_open_time_utc TEXT NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    tick_volume INTEGER NOT NULL CHECK (tick_volume >= 0),
    spread INTEGER NOT NULL CHECK (spread >= 0),
    real_volume INTEGER NOT NULL CHECK (real_volume >= 0),
    is_closed INTEGER NOT NULL CHECK (is_closed IN (0, 1)),
    first_seen_at_utc TEXT NOT NULL,
    last_seen_at_utc TEXT NOT NULL,
    PRIMARY KEY (
        broker_server,
        symbol,
        timeframe,
        candle_open_time_utc
    )
);

CREATE INDEX IF NOT EXISTS idx_candles_closed_time
    ON candles (
        broker_server,
        symbol,
        timeframe,
        is_closed,
        candle_open_time_utc
    );

CREATE TABLE IF NOT EXISTS candle_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_server TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    candle_open_time_utc TEXT NOT NULL,
    detected_at_utc TEXT NOT NULL,
    old_values_json TEXT NOT NULL,
    new_values_json TEXT NOT NULL,
    FOREIGN KEY (
        broker_server,
        symbol,
        timeframe,
        candle_open_time_utc
    ) REFERENCES candles (
        broker_server,
        symbol,
        timeframe,
        candle_open_time_utc
    ) ON DELETE RESTRICT
);
"""

_BACKFILL_SCHEMA = """
CREATE TABLE IF NOT EXISTS backfill_checkpoints (
    broker_server TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK (timeframe IN ('M1', 'M5')),
    requested_start_utc TEXT NOT NULL,
    requested_end_utc TEXT NOT NULL,
    next_from_utc TEXT NOT NULL,
    is_complete INTEGER NOT NULL CHECK (is_complete IN (0, 1)),
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (
        broker_server,
        symbol,
        timeframe,
        requested_start_utc,
        requested_end_utc
    ),
    CHECK (requested_start_utc < requested_end_utc),
    CHECK (next_from_utc >= requested_start_utc),
    CHECK (next_from_utc <= requested_end_utc)
);
"""


def _utc_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp_to_db(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _timestamp_from_db(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _decimal(value: Decimal | str, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} must be a decimal value") from exc
    else:
        raise TypeError(f"{field_name} must be Decimal or a decimal string")

    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if result <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return result


def _whole_epoch_seconds(value: datetime) -> int:
    delta = value - _EPOCH
    if delta.microseconds:
        raise ValueError("candle_open_time_utc must have whole-second precision")
    return delta.days * 86400 + delta.seconds


def _validate_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class Candle:
    broker_server: str
    symbol: str
    timeframe: str
    candle_open_time_utc: datetime
    open: Decimal | str
    high: Decimal | str
    low: Decimal | str
    close: Decimal | str
    tick_volume: int
    spread: int
    real_volume: int

    def __post_init__(self) -> None:
        _validate_identifier(self.broker_server, "broker_server")
        _validate_identifier(self.symbol, "symbol")
        if self.timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported timeframe: {self.timeframe!r}")

        candle_time = _utc_datetime(
            self.candle_open_time_utc,
            "candle_open_time_utc",
        )
        seconds = _whole_epoch_seconds(candle_time)
        if seconds % TIMEFRAME_SECONDS[self.timeframe]:
            raise ValueError(
                "candle_open_time_utc is not aligned to the timeframe"
            )
        object.__setattr__(self, "candle_open_time_utc", candle_time)

        for field_name in ("open", "high", "low", "close"):
            object.__setattr__(
                self,
                field_name,
                _decimal(getattr(self, field_name), field_name),
            )

        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be greater than or equal to OHLC values")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be less than or equal to OHLC values")

        for field_name in ("tick_volume", "spread", "real_volume"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")


@dataclass(frozen=True)
class UpsertSummary:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    revisions_recorded: int = 0
    duplicates_ignored: int = 0


@dataclass(frozen=True)
class BackfillCheckpoint:
    next_from_utc: datetime
    is_complete: bool
    updated_at_utc: datetime


class MarketDataStore:
    """Independent SQLite archive for validated MT5 candle data."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_MARKET_DATA_DB_PATH,
    ) -> None:
        self.db_path = Path(db_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, _SCHEMA_VERSION):
                raise RuntimeError(
                    f"Unsupported market database schema version: {version}"
                )
            schema = _BACKFILL_SCHEMA if version == 1 else (
                _SCHEMA + "\n" + _BACKFILL_SCHEMA
            )
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + schema
                + f"\nPRAGMA user_version = {_SCHEMA_VERSION};\nCOMMIT;"
            )

    @staticmethod
    def _key(candle: Candle) -> tuple[str, str, str, str]:
        return (
            candle.broker_server,
            candle.symbol,
            candle.timeframe,
            _timestamp_to_db(candle.candle_open_time_utc),
        )

    @staticmethod
    def _value_tuple(candle: Candle) -> tuple[object, ...]:
        return (
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.tick_volume,
            candle.spread,
            candle.real_volume,
        )

    @staticmethod
    def _stored_value_tuple(row: sqlite3.Row) -> tuple[object, ...]:
        return (
            Decimal(row["open"]),
            Decimal(row["high"]),
            Decimal(row["low"]),
            Decimal(row["close"]),
            row["tick_volume"],
            row["spread"],
            row["real_volume"],
        )

    @staticmethod
    def _values_json(values: tuple[object, ...]) -> str:
        names = (
            "open",
            "high",
            "low",
            "close",
            "tick_volume",
            "spread",
            "real_volume",
        )
        payload = {
            name: format(value, "f") if isinstance(value, Decimal) else value
            for name, value in zip(names, values)
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def upsert_candles(
        self,
        candles: Iterable[Candle],
        *,
        as_of_utc: datetime | None = None,
        observed_at_utc: datetime | None = None,
    ) -> UpsertSummary:
        as_of = _utc_datetime(
            as_of_utc or datetime.now(timezone.utc),
            "as_of_utc",
        )
        observed_at = _utc_datetime(
            observed_at_utc or datetime.now(timezone.utc),
            "observed_at_utc",
        )

        unique_candles: dict[tuple[str, str, str, str], Candle] = {}
        duplicates_ignored = 0
        for candle in candles:
            if not isinstance(candle, Candle):
                raise TypeError("candles must contain only Candle values")
            key = self._key(candle)
            previous = unique_candles.get(key)
            if previous is not None:
                if previous != candle:
                    raise ValueError(
                        "Conflicting candles share a key in the same batch"
                    )
                duplicates_ignored += 1
                continue
            unique_candles[key] = candle

        if not unique_candles:
            return UpsertSummary(duplicates_ignored=duplicates_ignored)

        counts = {
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "revisions_recorded": 0,
        }
        observed_text = _timestamp_to_db(observed_at)

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for key, candle in unique_candles.items():
                    existing = connection.execute(
                        """
                        SELECT * FROM candles
                        WHERE broker_server = ?
                          AND symbol = ?
                          AND timeframe = ?
                          AND candle_open_time_utc = ?
                        """,
                        key,
                    ).fetchone()
                    candle_time = candle.candle_open_time_utc
                    incoming_is_closed = (
                        candle_time
                        + timedelta(seconds=TIMEFRAME_SECONDS[candle.timeframe])
                        <= as_of
                    )
                    new_values = self._value_tuple(candle)

                    if existing is None:
                        connection.execute(
                            """
                            INSERT INTO candles (
                                broker_server, symbol, timeframe,
                                candle_open_time_utc, open, high, low, close,
                                tick_volume, spread, real_volume, is_closed,
                                first_seen_at_utc, last_seen_at_utc
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            key
                            + tuple(
                                format(value, "f")
                                if isinstance(value, Decimal)
                                else value
                                for value in new_values
                            )
                            + (
                                int(incoming_is_closed),
                                observed_text,
                                observed_text,
                            ),
                        )
                        counts["inserted"] += 1
                        continue

                    old_values = self._stored_value_tuple(existing)
                    values_changed = old_values != new_values
                    was_closed = bool(existing["is_closed"])
                    is_closed = was_closed or incoming_is_closed

                    if values_changed and was_closed:
                        connection.execute(
                            """
                            INSERT INTO candle_revisions (
                                broker_server, symbol, timeframe,
                                candle_open_time_utc, detected_at_utc,
                                old_values_json, new_values_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            key
                            + (
                                observed_text,
                                self._values_json(old_values),
                                self._values_json(new_values),
                            ),
                        )
                        counts["revisions_recorded"] += 1

                    if values_changed or is_closed != was_closed:
                        connection.execute(
                            """
                            UPDATE candles
                            SET open = ?, high = ?, low = ?, close = ?,
                                tick_volume = ?, spread = ?, real_volume = ?,
                                is_closed = ?, last_seen_at_utc = ?
                            WHERE broker_server = ? AND symbol = ?
                              AND timeframe = ?
                              AND candle_open_time_utc = ?
                            """,
                            tuple(
                                format(value, "f")
                                if isinstance(value, Decimal)
                                else value
                                for value in new_values
                            )
                            + (int(is_closed), observed_text)
                            + key,
                        )
                        counts["updated"] += 1
                    else:
                        connection.execute(
                            """
                            UPDATE candles
                            SET last_seen_at_utc = ?
                            WHERE broker_server = ? AND symbol = ?
                              AND timeframe = ? AND candle_open_time_utc = ?
                            """,
                            (observed_text,) + key,
                        )
                        counts["unchanged"] += 1
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        return UpsertSummary(
            inserted=counts["inserted"],
            updated=counts["updated"],
            unchanged=counts["unchanged"],
            revisions_recorded=counts["revisions_recorded"],
            duplicates_ignored=duplicates_ignored,
        )

    def get_closed_candles(
        self,
        broker_server: str,
        symbol: str,
        timeframe: str,
        *,
        start_utc: datetime | None = None,
        end_utc: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        _validate_identifier(broker_server, "broker_server")
        _validate_identifier(symbol, "symbol")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe!r}")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise ValueError("limit must be a positive integer or None")

        start = (
            _timestamp_to_db(_utc_datetime(start_utc, "start_utc"))
            if start_utc is not None
            else None
        )
        end = (
            _timestamp_to_db(_utc_datetime(end_utc, "end_utc"))
            if end_utc is not None
            else None
        )
        if start is not None and end is not None and start >= end:
            raise ValueError("start_utc must be earlier than end_utc")

        clauses = [
            "broker_server = ?",
            "symbol = ?",
            "timeframe = ?",
            "is_closed = 1",
        ]
        parameters: list[object] = [broker_server, symbol, timeframe]
        if start is not None:
            clauses.append("candle_open_time_utc >= ?")
            parameters.append(start)
        if end is not None:
            clauses.append("candle_open_time_utc < ?")
            parameters.append(end)

        order = "DESC" if limit is not None else "ASC"
        query = (
            "SELECT * FROM candles WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY candle_open_time_utc {order}"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        if limit is not None:
            rows.reverse()

        return [
            Candle(
                broker_server=row["broker_server"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                candle_open_time_utc=_timestamp_from_db(
                    row["candle_open_time_utc"]
                ),
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                tick_volume=row["tick_volume"],
                spread=row["spread"],
                real_volume=row["real_volume"],
            )
            for row in rows
        ]

    @staticmethod
    def _backfill_key(
        broker_server: str,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> tuple[str, str, str, str, str]:
        _validate_identifier(broker_server, "broker_server")
        _validate_identifier(symbol, "symbol")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe!r}")
        start = _utc_datetime(start_utc, "start_utc")
        end = _utc_datetime(end_utc, "end_utc")
        if start >= end:
            raise ValueError("start_utc must be earlier than end_utc")
        return (
            broker_server,
            symbol,
            timeframe,
            _timestamp_to_db(start),
            _timestamp_to_db(end),
        )

    def get_backfill_checkpoint(
        self,
        broker_server: str,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> BackfillCheckpoint | None:
        key = self._backfill_key(
            broker_server,
            symbol,
            timeframe,
            start_utc,
            end_utc,
        )
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT next_from_utc, is_complete, updated_at_utc
                FROM backfill_checkpoints
                WHERE broker_server = ? AND symbol = ? AND timeframe = ?
                  AND requested_start_utc = ? AND requested_end_utc = ?
                """,
                key,
            ).fetchone()
        if row is None:
            return None
        return BackfillCheckpoint(
            next_from_utc=_timestamp_from_db(row["next_from_utc"]),
            is_complete=bool(row["is_complete"]),
            updated_at_utc=_timestamp_from_db(row["updated_at_utc"]),
        )

    def save_backfill_checkpoint(
        self,
        broker_server: str,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
        next_from_utc: datetime,
        *,
        is_complete: bool,
        updated_at_utc: datetime | None = None,
    ) -> BackfillCheckpoint:
        key = self._backfill_key(
            broker_server,
            symbol,
            timeframe,
            start_utc,
            end_utc,
        )
        next_from = _utc_datetime(next_from_utc, "next_from_utc")
        start_text, end_text = key[3], key[4]
        next_text = _timestamp_to_db(next_from)
        if not start_text <= next_text <= end_text:
            raise ValueError("next_from_utc must be within the requested range")
        if not isinstance(is_complete, bool):
            raise TypeError("is_complete must be a bool")
        if is_complete and next_text != end_text:
            raise ValueError(
                "A backfill can be complete only at the requested end time"
            )
        updated = _utc_datetime(
            updated_at_utc or datetime.now(timezone.utc),
            "updated_at_utc",
        )
        values = key + (
            next_text,
            int(is_complete),
            _timestamp_to_db(updated),
        )

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO backfill_checkpoints (
                        broker_server, symbol, timeframe,
                        requested_start_utc, requested_end_utc,
                        next_from_utc, is_complete, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (
                        broker_server, symbol, timeframe,
                        requested_start_utc, requested_end_utc
                    ) DO UPDATE SET
                        next_from_utc = MAX(
                            backfill_checkpoints.next_from_utc,
                            excluded.next_from_utc
                        ),
                        is_complete = MAX(
                            backfill_checkpoints.is_complete,
                            excluded.is_complete
                        ),
                        updated_at_utc = excluded.updated_at_utc
                    """,
                    values,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        checkpoint = self.get_backfill_checkpoint(
            broker_server,
            symbol,
            timeframe,
            start_utc,
            end_utc,
        )
        if checkpoint is None:
            raise RuntimeError("Backfill checkpoint was not persisted")
        return checkpoint

from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from hashlib import sha256
from uuid import uuid4
from collections.abc import Mapping


TIMEFRAME_SECONDS = {"M1": 60, "M5": 300}
DEFAULT_MARKET_DATA_DB_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "market"
    / "market_data.sqlite"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SCHEMA_VERSION = 4

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


_CANDLE_VERSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS candle_ingestion_runs (
    run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    batch_sha256 TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candle_versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    broker_server TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK (timeframe IN ('M1', 'M5')),
    candle_open_time_utc TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    is_closed INTEGER NOT NULL CHECK (is_closed IN (0, 1)),
    values_sha256 TEXT NOT NULL,
    values_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES candle_ingestion_runs(run_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_candle_versions_stream
    ON candle_versions (broker_server, symbol, timeframe,
                        candle_open_time_utc, version_id);
CREATE TRIGGER IF NOT EXISTS trg_candle_versions_no_update
BEFORE UPDATE ON candle_versions
BEGIN
    SELECT RAISE(ABORT, 'candle versions are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_candle_versions_no_delete
BEFORE DELETE ON candle_versions
BEGIN
    SELECT RAISE(ABORT, 'candle versions are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_candle_ingestion_runs_no_update
BEFORE UPDATE ON candle_ingestion_runs
BEGIN
    SELECT RAISE(ABORT, 'candle ingestion runs are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_candle_ingestion_runs_no_delete
BEFORE DELETE ON candle_ingestion_runs
BEGIN
    SELECT RAISE(ABORT, 'candle ingestion runs are append-only');
END;
"""


_PA_LIFECYCLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pa_lifecycle_state (
    lifecycle_id TEXT PRIMARY KEY,
    broker_server TEXT NOT NULL,
    symbol TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('CANDIDATE', 'CONFIRMED', 'DEEPENING',
                  'RESOLVED', 'INVALIDATED', 'EXPIRED')
    ),
    state_version INTEGER NOT NULL CHECK (state_version >= 0),
    record_version INTEGER NOT NULL CHECK (record_version > 0),
    algorithm_version TEXT NOT NULL,
    parameter_version TEXT NOT NULL,
    last_processed_m5_utc TEXT NOT NULL,
    revision_watermark INTEGER NOT NULL CHECK (revision_watermark >= 0),
    snapshot_json TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pa_active_lifecycle_stream
    ON pa_lifecycle_state (broker_server, symbol)
    WHERE state IN ('CANDIDATE', 'CONFIRMED', 'DEEPENING');

CREATE INDEX IF NOT EXISTS idx_pa_lifecycle_stream_updated
    ON pa_lifecycle_state (broker_server, symbol, updated_at_utc);

CREATE TABLE IF NOT EXISTS pa_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    lifecycle_id TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
    transition_type TEXT NOT NULL,
    previous_state TEXT,
    current_state TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    lifecycle_snapshot_json TEXT NOT NULL,
    revision_watermark INTEGER NOT NULL CHECK (revision_watermark >= 0),
    created_at_utc TEXT NOT NULL,
    UNIQUE (lifecycle_id, event_sequence),
    FOREIGN KEY (lifecycle_id)
        REFERENCES pa_lifecycle_state (lifecycle_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_pa_lifecycle_events_time
    ON pa_lifecycle_events (lifecycle_id, event_sequence);

CREATE TRIGGER IF NOT EXISTS trg_pa_lifecycle_events_no_update
BEFORE UPDATE ON pa_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'pa_lifecycle_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_pa_lifecycle_events_no_delete
BEFORE DELETE ON pa_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'pa_lifecycle_events is append-only');
END;

CREATE INDEX IF NOT EXISTS idx_candle_revisions_stream
    ON candle_revisions (
        broker_server, symbol, timeframe, revision_id
    );

CREATE TABLE IF NOT EXISTS pa_lifecycle_recovery (
    broker_server TEXT NOT NULL,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('NORMAL', 'RECONCILIATION', 'QUARANTINED')
    ),
    reason_code TEXT NOT NULL,
    revision_watermark INTEGER NOT NULL CHECK (revision_watermark >= 0),
    checked_at_utc TEXT NOT NULL,
    details_json TEXT NOT NULL,
    PRIMARY KEY (broker_server, symbol)
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


@dataclass(frozen=True)
class CandleRevision:
    revision_id: int
    broker_server: str
    symbol: str
    timeframe: str
    candle_open_time_utc: datetime
    detected_at_utc: datetime
    old_values: dict[str, object]
    new_values: dict[str, object]


class MarketDataStore:
    """Independent SQLite archive for validated MT5 candle data."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_MARKET_DATA_DB_PATH,
        *,
        read_only: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self._read_only = bool(read_only)
        if self._read_only:
            if not self.db_path.is_file():
                raise FileNotFoundError(self.db_path)
        else:
            self._initialize()

    @classmethod
    def open_read_only(cls, db_path: str | Path = DEFAULT_MARKET_DATA_DB_PATH) -> "MarketDataStore":
        """Open an existing market archive without migration or write access."""
        return cls(db_path, read_only=True)

    def _connect(self) -> sqlite3.Connection:
        if self._read_only:
            uri = self.db_path.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=30)
        else:
            connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        if not self._read_only:
            connection.execute("PRAGMA synchronous = FULL")
        return connection

    def get_history_metadata(self) -> dict[str, object]:
        """Inspect spot archive coverage and provenance readiness without migration."""
        with closing(self._connect()) as connection:
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            legacy_count = int(connection.execute(
                "SELECT COUNT(*) FROM candles"
            ).fetchone()[0]) if "candles" in tables else 0
            if schema_version >= 4 and "candle_versions" in tables:
                streams = connection.execute(
                    "SELECT DISTINCT broker_server, symbol, timeframe FROM candle_versions "
                    "ORDER BY broker_server, symbol, timeframe"
                ).fetchall()
                version_count = int(connection.execute(
                    "SELECT COUNT(*) FROM candle_versions"
                ).fetchone()[0])
            else:
                streams = connection.execute(
                    "SELECT DISTINCT broker_server, symbol, timeframe FROM candles "
                    "ORDER BY broker_server, symbol, timeframe"
                ).fetchall() if "candles" in tables else []
                version_count = 0
        return {
            "schema_version": schema_version,
            "legacy_candle_count": legacy_count,
            "versioned_candle_count": version_count,
            "version_ledger_available": schema_version >= 4 and "candle_versions" in tables,
            "streams": [dict(row) for row in streams],
            "read_only": self._read_only,
        }

    def get_candle_versions_as_of(
        self, broker_server: str, symbol: str, timeframe: str, as_of_utc: datetime,
    ) -> list[dict[str, object]]:
        """Return latest closed candle versions visible to system knowledge at cutoff."""
        _validate_identifier(broker_server, "broker_server")
        _validate_identifier(symbol, "symbol")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe!r}")
        cutoff = _utc_datetime(as_of_utc, "as_of_utc")
        metadata = self.get_history_metadata()
        if not metadata["version_ledger_available"]:
            raise RuntimeError("CANDLE_VERSION_LEDGER_UNAVAILABLE")
        cutoff_text = _timestamp_to_db(cutoff)
        latest_open_allowed = _timestamp_to_db(
            cutoff - timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
        )
        query = """SELECT cv.*, cir.provenance_json
                   FROM candle_versions cv
                   JOIN candle_ingestion_runs cir ON cir.run_id = cv.run_id
                   WHERE cv.broker_server = ? AND cv.symbol = ? AND cv.timeframe = ?
                     AND cv.observed_at_utc <= ? AND cv.as_of_utc <= ?
                     AND cv.candle_open_time_utc <= ?
                   ORDER BY cv.candle_open_time_utc, cv.observed_at_utc, cv.version_id"""
        with closing(self._connect()) as connection:
            rows = connection.execute(query, (
                broker_server, symbol, timeframe, cutoff_text, cutoff_text,
                latest_open_allowed,
            )).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            key = row["candle_open_time_utc"]
            current = latest.get(key)
            if current is None or (row["observed_at_utc"], row["version_id"]) > (current["observed_at_utc"], current["version_id"]):
                latest[key] = row
        output = []
        for row in latest.values():
            if not bool(row["is_closed"]):
                continue
            opened = _timestamp_from_db(row["candle_open_time_utc"])
            closed = opened + timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
            if closed > cutoff:
                continue
            output.append({
                "source_id": row["source_id"], "broker_server": row["broker_server"],
                "symbol": row["symbol"], "timeframe": row["timeframe"],
                "candle_open_time_utc": row["candle_open_time_utc"],
                "candle_close_time_utc": _timestamp_to_db(closed),
                "observed_at_utc": row["observed_at_utc"], "as_of_utc": row["as_of_utc"],
                "is_closed": True, "version_id": int(row["version_id"]),
                "values": json.loads(row["values_json"]),
                "values_sha256": row["values_sha256"],
                "provenance": json.loads(row["provenance_json"]),
            })
        return output

    def get_candle_version_history(
        self, broker_server: str, symbol: str, timeframe: str, *,
        start_utc: datetime, end_utc: datetime,
        observed_at_or_before_utc: datetime,
    ) -> list[dict[str, object]]:
        """Read every immutable candle version in a bounded replay window.

        This method never migrates or writes. Replay callers must use a read-only
        MarketDataStore and apply the per-cutoff observed/as-of filters themselves.
        """
        _validate_identifier(broker_server, "broker_server")
        _validate_identifier(symbol, "symbol")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe!r}")
        start = _utc_datetime(start_utc, "start_utc")
        end = _utc_datetime(end_utc, "end_utc")
        observed_cutoff = _utc_datetime(
            observed_at_or_before_utc, "observed_at_or_before_utc"
        )
        if end < start:
            raise ValueError("end_utc must not precede start_utc")
        if not self._read_only:
            raise RuntimeError("HISTORICAL_REPLAY_REQUIRES_READ_ONLY_MARKET_STORE")
        metadata = self.get_history_metadata()
        if not metadata["version_ledger_available"]:
            raise RuntimeError("CANDLE_VERSION_LEDGER_UNAVAILABLE")
        query = """SELECT cv.*, cir.provenance_json
                   FROM candle_versions cv
                   JOIN candle_ingestion_runs cir ON cir.run_id = cv.run_id
                   WHERE cv.broker_server = ? AND cv.symbol = ? AND cv.timeframe = ?
                     AND cv.candle_open_time_utc >= ? AND cv.candle_open_time_utc <= ?
                     AND cv.observed_at_utc <= ? AND cv.as_of_utc <= ?
                   ORDER BY cv.candle_open_time_utc, cv.observed_at_utc, cv.version_id"""
        with closing(self._connect()) as connection:
            rows = connection.execute(query, (
                broker_server, symbol, timeframe, _timestamp_to_db(start),
                _timestamp_to_db(end), _timestamp_to_db(observed_cutoff),
                _timestamp_to_db(observed_cutoff),
            )).fetchall()
        output = []
        for row in rows:
            opened = _timestamp_from_db(row["candle_open_time_utc"])
            closed = opened + timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
            output.append({
                "source_id": row["source_id"], "broker_server": row["broker_server"],
                "symbol": row["symbol"], "timeframe": row["timeframe"],
                "candle_open_time_utc": row["candle_open_time_utc"],
                "candle_close_time_utc": _timestamp_to_db(closed),
                "observed_at_utc": row["observed_at_utc"],
                "as_of_utc": row["as_of_utc"], "is_closed": bool(row["is_closed"]),
                "version_id": int(row["version_id"]),
                "values": json.loads(row["values_json"]),
                "values_sha256": row["values_sha256"],
                "provenance": json.loads(row["provenance_json"]),
            })
        return output

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, _SCHEMA_VERSION):
                raise RuntimeError(
                    f"Unsupported market database schema version: {version}"
                )
            if version == 1:
                schema = _BACKFILL_SCHEMA + "\n" + _PA_LIFECYCLE_SCHEMA
            elif version == 2:
                schema = _PA_LIFECYCLE_SCHEMA
            else:
                schema = _SCHEMA + "\n" + _BACKFILL_SCHEMA + "\n" + _PA_LIFECYCLE_SCHEMA
            schema += "\n" + _CANDLE_VERSION_SCHEMA
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
        source_id: str = "UNSPECIFIED",
        provenance: Mapping[str, object] | None = None,
    ) -> UpsertSummary:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id must be a non-empty string")
        if provenance is not None and not isinstance(provenance, Mapping):
            raise TypeError("provenance must be a mapping")
        provenance_json = json.dumps(
            dict(provenance or {}), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, default=str,
        )
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
        as_of_text = _timestamp_to_db(as_of)
        canonical_rows = []
        for key, candle in sorted(unique_candles.items()):
            values_json = self._values_json(self._value_tuple(candle))
            canonical_rows.append({"key": key, "values": json.loads(values_json)})
        batch_sha256 = sha256(json.dumps(
            canonical_rows, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        run_id = str(uuid4())

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """INSERT INTO candle_ingestion_runs (
                        run_id, source_id, observed_at_utc, as_of_utc,
                        row_count, batch_sha256, provenance_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, source_id, observed_text, as_of_text,
                     len(unique_candles), batch_sha256, provenance_json),
                )
                for key, candle in unique_candles.items():
                    values_json = self._values_json(self._value_tuple(candle))
                    values_sha256 = sha256(values_json.encode("utf-8")).hexdigest()
                    candle_time = candle.candle_open_time_utc
                    version_is_closed = (
                        candle_time + timedelta(
                            seconds=TIMEFRAME_SECONDS[candle.timeframe]
                        ) <= as_of
                    )
                    latest_version = connection.execute(
                        """SELECT values_sha256, source_id, is_closed
                           FROM candle_versions
                           WHERE broker_server = ? AND symbol = ? AND timeframe = ?
                             AND candle_open_time_utc = ?
                           ORDER BY version_id DESC LIMIT 1""", key,
                    ).fetchone()
                    if (latest_version is None
                            or latest_version["values_sha256"] != values_sha256
                            or latest_version["source_id"] != source_id
                            or bool(latest_version["is_closed"]) != version_is_closed):
                        connection.execute(
                            """INSERT INTO candle_versions (
                                run_id, source_id, broker_server, symbol, timeframe,
                                candle_open_time_utc, observed_at_utc, as_of_utc,
                                is_closed, values_sha256, values_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (run_id, source_id, *key, observed_text, as_of_text,
                             int(version_is_closed), values_sha256, values_json),
                        )
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

    def get_candle_revision_watermark(
        self,
        broker_server: str,
        symbol: str,
        timeframe: str,
    ) -> int:
        """Return the latest revision ID for one broker/symbol/timeframe stream."""
        _validate_identifier(broker_server, "broker_server")
        _validate_identifier(symbol, "symbol")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe!r}")
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(revision_id), 0) AS watermark
                FROM candle_revisions
                WHERE broker_server = ? AND symbol = ? AND timeframe = ?
                """,
                (broker_server, symbol, timeframe),
            ).fetchone()
        return int(row["watermark"])

    def get_candle_revisions(
        self,
        broker_server: str,
        symbol: str,
        timeframe: str,
        *,
        after_revision_id: int = 0,
        through_revision_id: int | None = None,
        limit: int = 500,
    ) -> list[CandleRevision]:
        """Read revisions in stable revision-ID order, using an exclusive lower bound."""
        _validate_identifier(broker_server, "broker_server")
        _validate_identifier(symbol, "symbol")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe!r}")
        if isinstance(after_revision_id, bool) or not isinstance(after_revision_id, int) or after_revision_id < 0:
            raise ValueError("after_revision_id must be a non-negative integer")
        if through_revision_id is not None and (
            isinstance(through_revision_id, bool)
            or not isinstance(through_revision_id, int)
            or through_revision_id < after_revision_id
        ):
            raise ValueError("through_revision_id must be an integer >= after_revision_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")

        clauses = [
            "broker_server = ?",
            "symbol = ?",
            "timeframe = ?",
            "revision_id > ?",
        ]
        parameters: list[object] = [
            broker_server, symbol, timeframe, after_revision_id
        ]
        if through_revision_id is not None:
            clauses.append("revision_id <= ?")
            parameters.append(through_revision_id)
        parameters.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT revision_id, broker_server, symbol, timeframe,
                       candle_open_time_utc, detected_at_utc,
                       old_values_json, new_values_json
                FROM candle_revisions
                WHERE """ + " AND ".join(clauses) + """
                ORDER BY revision_id ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        return [
            CandleRevision(
                revision_id=int(row["revision_id"]),
                broker_server=row["broker_server"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                candle_open_time_utc=_timestamp_from_db(row["candle_open_time_utc"]),
                detected_at_utc=_timestamp_from_db(row["detected_at_utc"]),
                old_values=json.loads(row["old_values_json"]),
                new_values=json.loads(row["new_values_json"]),
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

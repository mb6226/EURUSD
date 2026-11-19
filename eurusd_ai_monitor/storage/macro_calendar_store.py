from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from eurusd_ai_monitor.models.macro_event import MacroEvent


DEFAULT_MACRO_CALENDAR_DB_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "calendar" / "macro_calendar.sqlite"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS macro_events (
    event_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    scheduled_at_utc TEXT,
    scheduled_date TEXT NOT NULL,
    impact TEXT NOT NULL CHECK (impact IN ('HIGH','MEDIUM','LOW','UNKNOWN')),
    status TEXT NOT NULL CHECK (status IN ('SCHEDULED','TENTATIVE','CANCELLED','RELEASED','UNKNOWN')),
    payload_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    first_seen_at_utc TEXT NOT NULL,
    last_seen_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_macro_events_time
    ON macro_events(scheduled_at_utc, scheduled_date, impact);
CREATE INDEX IF NOT EXISTS idx_macro_events_source
    ON macro_events(source_id, scheduled_date);
CREATE TABLE IF NOT EXISTS macro_event_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    changed_at_utc TEXT NOT NULL,
    previous_payload_json TEXT NOT NULL,
    current_payload_json TEXT NOT NULL,
    previous_sha256 TEXT NOT NULL,
    current_sha256 TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES macro_events(event_id) ON DELETE RESTRICT
);
CREATE TRIGGER IF NOT EXISTS trg_macro_event_revisions_no_update
BEFORE UPDATE ON macro_event_revisions
BEGIN
    SELECT RAISE(ABORT, 'macro_event_revisions is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_macro_event_revisions_no_delete
BEFORE DELETE ON macro_event_revisions
BEGIN
    SELECT RAISE(ABORT, 'macro_event_revisions is append-only');
END;
CREATE TABLE IF NOT EXISTS macro_source_state (
    source_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('NOT_CONNECTED','ACTIVE','STALE','FAILED','DEGRADED')),
    last_attempt_at_utc TEXT,
    last_success_at_utc TEXT,
    event_count INTEGER NOT NULL DEFAULT 0 CHECK(event_count >= 0),
    last_error_code TEXT,
    last_error_message TEXT,
    updated_at_utc TEXT NOT NULL
);
PRAGMA user_version = 1;
"""


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_stamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class MacroCalendarStore:
    """Independent event store; deliberately separate from market and RAG databases."""

    def __init__(self, db_path: str | Path = DEFAULT_MACRO_CALENDAR_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError(f"Unsupported macro calendar schema version: {version}")
            connection.executescript(_SCHEMA)
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def upsert_events(self, events: Iterable[MacroEvent], retrieved_at_utc: datetime) -> int:
        stamp = _stamp(retrieved_at_utc)
        items = tuple(events)
        seen: dict[str, str] = {}
        for event in items:
            if not isinstance(event, MacroEvent):
                raise TypeError("events must contain MacroEvent values")
            payload = event.to_dict(include_retrieved_at=False)
            encoded = _canonical(payload)
            prior = seen.get(event.event_id)
            if prior is not None and prior != encoded:
                raise ValueError(f"conflicting duplicate event in batch: {event.event_id}")
            seen[event.event_id] = encoded

        revisions = 0
        with closing(self._connect()) as connection:
            try:
                for event in items:
                    payload = event.to_dict()
                    encoded = _canonical(payload)
                    semantic = _canonical(event.to_dict(include_retrieved_at=False))
                    digest = hashlib.sha256(semantic.encode("utf-8")).hexdigest()
                    previous = connection.execute(
                        "SELECT payload_json, content_sha256 FROM macro_events WHERE event_id = ?",
                        (event.event_id,),
                    ).fetchone()
                    if previous is None:
                        connection.execute(
                            """
                            INSERT INTO macro_events (
                                event_id, source_id, scheduled_at_utc, scheduled_date,
                                impact, status, payload_json, content_sha256,
                                first_seen_at_utc, last_seen_at_utc
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                event.event_id, event.source_id,
                                _stamp(event.scheduled_at_utc) if event.scheduled_at_utc else None,
                                event.scheduled_date.isoformat(), event.impact.value,
                                event.status.value, encoded, digest, stamp, stamp,
                            ),
                        )
                    else:
                        if previous["content_sha256"] != digest:
                            connection.execute(
                                """
                                INSERT INTO macro_event_revisions (
                                    event_id, changed_at_utc, previous_payload_json,
                                    current_payload_json, previous_sha256, current_sha256
                                ) VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    event.event_id, stamp, previous["payload_json"],
                                    encoded, previous["content_sha256"], digest,
                                ),
                            )
                            revisions += 1
                        connection.execute(
                            """
                            UPDATE macro_events SET
                                scheduled_at_utc = ?, scheduled_date = ?, impact = ?,
                                status = ?, payload_json = ?, content_sha256 = ?,
                                last_seen_at_utc = ?
                            WHERE event_id = ?
                            """,
                            (
                                _stamp(event.scheduled_at_utc) if event.scheduled_at_utc else None,
                                event.scheduled_date.isoformat(), event.impact.value,
                                event.status.value, encoded, digest, stamp, event.event_id,
                            ),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return revisions

    def record_source_state(
        self,
        source_id: str,
        status: str,
        attempted_at_utc: datetime,
        successful_at_utc: datetime | None,
        event_count: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in {"NOT_CONNECTED", "ACTIVE", "STALE", "FAILED", "DEGRADED"}:
            raise ValueError("unsupported source status")
        if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 0:
            raise ValueError("event_count must be a non-negative integer")
        attempted = _stamp(attempted_at_utc)
        successful = _stamp(successful_at_utc) if successful_at_utc else None
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO macro_source_state (
                    source_id, status, last_attempt_at_utc, last_success_at_utc,
                    event_count, last_error_code, last_error_message, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    status = excluded.status,
                    last_attempt_at_utc = excluded.last_attempt_at_utc,
                    last_success_at_utc = COALESCE(excluded.last_success_at_utc, macro_source_state.last_success_at_utc),
                    event_count = CASE WHEN excluded.status IN ('ACTIVE','DEGRADED') THEN excluded.event_count ELSE macro_source_state.event_count END,
                    last_error_code = excluded.last_error_code,
                    last_error_message = excluded.last_error_message,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (source_id, status, attempted, successful, event_count, error_code, error_message, attempted),
            )
            connection.commit()

    def get_source_states(self) -> dict[str, dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM macro_source_state ORDER BY source_id").fetchall()
        return {
            row["source_id"]: {
                "status": row["status"],
                "last_attempt_at_utc": _parse_stamp(row["last_attempt_at_utc"]),
                "last_success_at_utc": _parse_stamp(row["last_success_at_utc"]),
                "event_count": row["event_count"],
                "last_error_code": row["last_error_code"],
                "last_error_message": row["last_error_message"],
            }
            for row in rows
        }

    def list_events(
        self,
        start_utc: datetime,
        end_utc: datetime,
        currencies: tuple[str, ...] = ("EUR", "USD"),
        include_cancelled: bool = False,
        limit: int = 250,
    ) -> tuple[MacroEvent, ...]:
        if start_utc.tzinfo is None or end_utc.tzinfo is None or start_utc >= end_utc:
            raise ValueError("start_utc and end_utc must be ordered timezone-aware datetimes")
        if not 1 <= limit <= 2000:
            raise ValueError("limit must be between 1 and 2000")
        start_day = start_utc.astimezone(timezone.utc).date()
        end_day = end_utc.astimezone(timezone.utc).date()
        # Include adjacent local calendar dates; final filtering uses the true UTC instant.
        start_date = (start_day - timedelta(days=1)).isoformat()
        end_date = (end_day + timedelta(days=1)).isoformat()
        clauses = ["scheduled_date >= ?", "scheduled_date <= ?"]
        params: list[object] = [start_date, end_date]
        if not include_cancelled:
            clauses.append("status != 'CANCELLED'")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM macro_events WHERE " + " AND ".join(clauses) +
                " ORDER BY COALESCE(scheduled_at_utc, scheduled_date), event_id LIMIT ?",
                (*params, limit),
            ).fetchall()
        results = []
        allowed = set(currencies)
        for row in rows:
            event = MacroEvent.from_dict(json.loads(row["payload_json"]))
            if not allowed.intersection(event.currency_codes):
                continue
            if event.scheduled_at_utc is not None:
                if not (start_utc.astimezone(timezone.utc) <= event.scheduled_at_utc <= end_utc.astimezone(timezone.utc)):
                    continue
            # Date-only releases have no exact instant. Include adjacent local
            # calendar dates so UTC/local midnight offsets cannot hide them.
            elif not (start_day - timedelta(days=1) <= event.scheduled_date <= end_day + timedelta(days=1)):
                continue
            results.append(event)
        return tuple(results)

    def revision_count(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM macro_event_revisions").fetchone()[0])

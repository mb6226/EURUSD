from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from .adapters.models import FetchResult, Observation

DEFAULT_OBSERVATION_DB = (
    Path(__file__).resolve().parent / "operational" / "observations.sqlite"
)
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fetch_batches (
    batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    retrieved_at_utc TEXT NOT NULL,
    source_url TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    payload_sha256 TEXT NOT NULL,
    UNIQUE (source_id, product_id, retrieved_at_utc, payload_sha256)
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    observation_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    effective_at_utc TEXT NOT NULL,
    published_at_utc TEXT,
    retrieved_at_utc TEXT NOT NULL,
    value_json TEXT NOT NULL,
    unit TEXT NOT NULL,
    source_record_id TEXT,
    source_url TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    batch_id INTEGER NOT NULL REFERENCES fetch_batches(batch_id)
        ON DELETE RESTRICT,
    UNIQUE (source_id, product_id, observation_key, version),
    UNIQUE (source_id, product_id, observation_key, payload_sha256)
);

CREATE INDEX IF NOT EXISTS idx_observations_pit_lookup
    ON observations (
        source_id, product_id, observation_key,
        published_at_utc, retrieved_at_utc, version
    );

CREATE INDEX IF NOT EXISTS idx_observations_effective
    ON observations (source_id, product_id, effective_at_utc);

CREATE TRIGGER IF NOT EXISTS trg_observations_no_update
BEFORE UPDATE ON observations
BEGIN
    SELECT RAISE(ABORT, 'observations is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_observations_no_delete
BEFORE DELETE ON observations
BEGIN
    SELECT RAISE(ABORT, 'observations is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_fetch_batches_no_update
BEFORE UPDATE ON fetch_batches
BEGIN
    SELECT RAISE(ABORT, 'fetch_batches is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_fetch_batches_no_delete
BEFORE DELETE ON fetch_batches
BEGIN
    SELECT RAISE(ABORT, 'fetch_batches is append-only');
END;
"""


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _observation_value(observation: Observation) -> Any:
    value = observation.value
    return value.to_dict() if hasattr(value, "to_dict") else format(value, "f")


def _observation_key(observation: Observation) -> str:
    if observation.source_record_id is not None:
        return "record:" + observation.source_record_id
    return "natural:" + "|".join((
        _stamp(observation.effective_at_utc),
        observation.unit,
    ))


@dataclass(frozen=True)
class PersistSummary:
    batches_inserted: int = 0
    observations_inserted: int = 0
    observations_unchanged: int = 0
    observations_revised: int = 0


class PointInTimeObservationStore:
    """Append-only store for source-registry observations with strict as-of reads.

    A record is visible at an as-of time only if both its publication time and
    retrieval time are known and no later than that time. Unknown publication
    timestamps are excluded by default because their historical availability
    cannot be established.
    """

    def __init__(self, db_path: str | Path = DEFAULT_OBSERVATION_DB) -> None:
        self.db_path = Path(db_path).resolve()
        self._read_only = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise RuntimeError(
                    f"Unsupported observation database schema version: {version}"
                )
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()

    @classmethod
    def open_read_only(cls, db_path: str | Path) -> "PointInTimeObservationStore":
        """Open an existing observation database without creating or mutating it."""
        path = Path(db_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        instance = cls.__new__(cls)
        instance.db_path = path
        instance._read_only = True
        connection = instance._connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported or uninitialized observation database schema version: {version}"
                )
            required = {"observations", "fetch_batches"}
            present = {
                row["name"] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not required.issubset(present):
                raise RuntimeError("Observation database schema is incomplete")
        finally:
            connection.close()
        return instance

    def _connect(self) -> sqlite3.Connection:
        if getattr(self, "_read_only", False):
            connection = sqlite3.connect(
                self.db_path.as_uri() + "?mode=ro", uri=True, timeout=30
            )
        else:
            connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def persist_fetch_result(self, result: FetchResult) -> PersistSummary:
        if not isinstance(result, FetchResult):
            raise TypeError("result must be a FetchResult")
        result.validate(require_retrieved_at=True)
        retrieved = _stamp(result.retrieved_at_utc)
        serialized = result.to_dict()
        batch_payload = _canonical(serialized)
        batch_digest = sha256(batch_payload.encode("utf-8")).hexdigest()
        counts = {
            "batches_inserted": 0,
            "observations_inserted": 0,
            "observations_unchanged": 0,
            "observations_revised": 0,
        }

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_batch = connection.execute(
                """
                SELECT batch_id FROM fetch_batches
                WHERE source_id = ? AND product_id = ?
                  AND retrieved_at_utc = ? AND payload_sha256 = ?
                """,
                (
                    result.source_id, result.product_id, retrieved,
                    batch_digest,
                ),
            ).fetchone()
            if existing_batch is None:
                cursor = connection.execute(
                    """
                    INSERT INTO fetch_batches (
                        source_id, product_id, retrieved_at_utc,
                        source_url, record_count, payload_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.source_id, result.product_id, retrieved,
                        result.source_url, result.record_count, batch_digest,
                    ),
                )
                batch_id = cursor.lastrowid
                counts["batches_inserted"] = 1
            else:
                batch_id = existing_batch["batch_id"]

            for observation in result.observations:
                key = _observation_key(observation)
                value = _observation_value(observation)
                payload = {
                    "source_id": observation.source_id,
                    "product_id": observation.product_id,
                    "observation_key": key,
                    "effective_at_utc": _stamp(observation.effective_at_utc),
                    "published_at_utc": (
                        _stamp(observation.published_at_utc)
                        if observation.published_at_utc is not None else None
                    ),
                    "value": value,
                    "unit": observation.unit,
                    "source_record_id": observation.source_record_id,
                    "source_url": result.source_url,
                }
                encoded = _canonical(payload)
                digest = sha256(encoded.encode("utf-8")).hexdigest()
                prior = connection.execute(
                    """
                    SELECT version, payload_sha256 FROM observations
                    WHERE source_id = ? AND product_id = ?
                      AND observation_key = ?
                    ORDER BY version DESC LIMIT 1
                    """,
                    (result.source_id, result.product_id, key),
                ).fetchone()

                if prior is not None and prior["payload_sha256"] == digest:
                    counts["observations_unchanged"] += 1
                    continue

                version = 1 if prior is None else prior["version"] + 1
                connection.execute(
                    """
                    INSERT INTO observations (
                        source_id, product_id, observation_key, version,
                        effective_at_utc, published_at_utc, retrieved_at_utc,
                        value_json, unit, source_record_id, source_url,
                        payload_sha256, batch_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.source_id, result.product_id, key, version,
                        payload["effective_at_utc"], payload["published_at_utc"],
                        retrieved, _canonical(value), observation.unit,
                        observation.source_record_id, result.source_url,
                        digest, batch_id,
                    ),
                )
                counts["observations_inserted"] += 1
                if prior is not None:
                    counts["observations_revised"] += 1

            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return PersistSummary(**counts)

    def get_as_of(
        self,
        source_id: str,
        product_id: str,
        as_of_utc: datetime,
        *,
        include_future_effective: bool = False,
        include_unknown_publication: bool = False,
    ) -> list[dict[str, Any]]:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id must be non-empty")
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id must be non-empty")
        cutoff = _stamp(_utc(as_of_utc, "as_of_utc"))
        clauses = [
            "source_id = ?",
            "product_id = ?",
            "retrieved_at_utc <= ?",
        ]
        parameters: list[Any] = [source_id, product_id, cutoff]
        if not include_unknown_publication:
            clauses.append("published_at_utc IS NOT NULL")
        clauses.append("(published_at_utc IS NULL OR published_at_utc <= ?)")
        parameters.append(cutoff)
        if not include_future_effective:
            clauses.append("effective_at_utc <= ?")
            parameters.append(cutoff)

        query = (
            "SELECT * FROM observations WHERE "
            + " AND ".join(clauses)
            + " ORDER BY observation_key, retrieved_at_utc, version"
        )
        connection = self._connect()
        try:
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            key = row["observation_key"]
            current = latest.get(key)
            if current is None or (
                row["retrieved_at_utc"], row["version"]
            ) > (
                current["retrieved_at_utc"], current["version"]
            ):
                latest[key] = row

        return [
            {
                "source_id": row["source_id"],
                "product_id": row["product_id"],
                "observation_key": row["observation_key"],
                "version": row["version"],
                "effective_at_utc": row["effective_at_utc"],
                "published_at_utc": row["published_at_utc"],
                "retrieved_at_utc": row["retrieved_at_utc"],
                "value": json.loads(row["value_json"]),
                "unit": row["unit"],
                "source_record_id": row["source_record_id"],
                "source_url": row["source_url"],
                "payload_sha256": row["payload_sha256"],
            }
            for row in sorted(
                latest.values(),
                key=lambda item: (
                    item["effective_at_utc"], item["observation_key"]
                ),
            )
        ]

    def get_many_as_of(
        self,
        requests: list[tuple[str, str]],
        as_of_utc: datetime,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """Read several products in one point-in-time, read-only SQLite query."""
        if not isinstance(requests, (list, tuple)):
            raise TypeError("requests must be a list or tuple of (source_id, product_id)")
        pairs = []
        for pair in requests:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("each request must contain source_id and product_id")
            source_id, product_id = pair
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("source_id must be non-empty")
            if not isinstance(product_id, str) or not product_id.strip():
                raise ValueError("product_id must be non-empty")
            normalized = (source_id, product_id)
            if normalized not in pairs:
                pairs.append(normalized)
        if not pairs:
            return {}
        cutoff = _stamp(_utc(as_of_utc, "as_of_utc"))
        pair_clause = " OR ".join("(source_id = ? AND product_id = ?)" for _ in pairs)
        parameters: list[Any] = [value for pair in pairs for value in pair]
        parameters.extend((cutoff, cutoff, cutoff))
        query = (
            "SELECT * FROM observations WHERE (" + pair_clause + ") "
            "AND retrieved_at_utc <= ? AND published_at_utc IS NOT NULL "
            "AND published_at_utc <= ? AND effective_at_utc <= ? "
            "ORDER BY source_id, product_id, observation_key, retrieved_at_utc, version"
        )
        connection = self._connect()
        try:
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()
        latest: dict[tuple[str, str, str], sqlite3.Row] = {}
        for row in rows:
            key = (row["source_id"], row["product_id"], row["observation_key"])
            current = latest.get(key)
            if current is None or (
                row["retrieved_at_utc"], row["version"]
            ) > (
                current["retrieved_at_utc"], current["version"]
            ):
                latest[key] = row
        result = {pair: [] for pair in pairs}
        for (source_id, product_id, _), row in latest.items():
            result[(source_id, product_id)].append({
                "source_id": row["source_id"],
                "product_id": row["product_id"],
                "observation_key": row["observation_key"],
                "version": row["version"],
                "effective_at_utc": row["effective_at_utc"],
                "published_at_utc": row["published_at_utc"],
                "retrieved_at_utc": row["retrieved_at_utc"],
                "value": json.loads(row["value_json"]),
                "unit": row["unit"],
                "source_record_id": row["source_record_id"],
                "source_url": row["source_url"],
                "payload_sha256": row["payload_sha256"],
            })
        for values in result.values():
            values.sort(key=lambda item: (
                item["effective_at_utc"], item["observation_key"]
            ))
        return result

    def get_revision_history(
        self,
        source_id: str,
        product_id: str,
        *,
        as_of_utc: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return append-only versions for audit under optional strict as-of cutoff."""
        return self.get_many_revision_history(
            [(source_id, product_id)], as_of_utc=as_of_utc
        ).get((source_id, product_id), [])

    def get_many_revision_history(
        self,
        requests: list[tuple[str, str]],
        *,
        as_of_utc: datetime | None = None,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """Read append-only versions for multiple products in one read-only query."""
        if not isinstance(requests, (list, tuple)):
            raise TypeError("requests must be a list or tuple of (source_id, product_id)")
        pairs: list[tuple[str, str]] = []
        for pair in requests:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("each request must contain source_id and product_id")
            source_id, product_id = pair
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("source_id must be non-empty")
            if not isinstance(product_id, str) or not product_id.strip():
                raise ValueError("product_id must be non-empty")
            normalized = (source_id, product_id)
            if normalized not in pairs:
                pairs.append(normalized)
        result = {pair: [] for pair in pairs}
        if not pairs:
            return result
        pair_clause = " OR ".join("(source_id = ? AND product_id = ?)" for _ in pairs)
        clauses = ["(" + pair_clause + ")"]
        parameters: list[Any] = [value for pair in pairs for value in pair]
        if as_of_utc is not None:
            cutoff = _stamp(_utc(as_of_utc, "as_of_utc"))
            clauses.extend(("retrieved_at_utc <= ?", "published_at_utc IS NOT NULL", "published_at_utc <= ?", "effective_at_utc <= ?"))
            parameters.extend((cutoff, cutoff, cutoff))
        query = "SELECT * FROM observations WHERE " + " AND ".join(clauses) + " ORDER BY source_id, product_id, observation_key, version, retrieved_at_utc"
        connection = self._connect()
        try:
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()
        for row in rows:
            pair = (row["source_id"], row["product_id"])
            result[pair].append({
                "source_id": row["source_id"], "product_id": row["product_id"],
                "observation_key": row["observation_key"], "version": row["version"],
                "effective_at_utc": row["effective_at_utc"], "published_at_utc": row["published_at_utc"],
                "retrieved_at_utc": row["retrieved_at_utc"], "value": json.loads(row["value_json"]),
                "unit": row["unit"], "source_record_id": row["source_record_id"],
                "payload_sha256": row["payload_sha256"],
            })
        return result

    def count_observations(self) -> int:
        connection = self._connect()
        try:
            return connection.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0]
        finally:
            connection.close()

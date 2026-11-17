from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_STATE_DB = PACKAGE_ROOT / "operational" / "state.db"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_state (
    source_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (
        status IN (
            'NOT_CONNECTED',
            'ACTIVE',
            'STALE',
            'DEGRADED',
            'FAILED',
            'VALIDATION_REQUIRED',
            'RETIRED'
        )
    ),
    last_attempt_at_utc TEXT,
    last_success_at_utc TEXT,
    last_source_data_at_utc TEXT,
    next_due_at_utc TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
        CHECK (consecutive_failures >= 0),
    last_error_code TEXT,
    last_error_message TEXT,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_state (
    source_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'NOT_CONNECTED',
            'ACTIVE',
            'STALE',
            'DEGRADED',
            'FAILED',
            'VALIDATION_REQUIRED',
            'RETIRED'
        )
    ),
    last_attempt_at_utc TEXT,
    last_success_at_utc TEXT,
    last_source_data_at_utc TEXT,
    next_due_at_utc TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
        CHECK (consecutive_failures >= 0),
    last_error_code TEXT,
    last_error_message TEXT,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (source_id, product_id),
    FOREIGN KEY (source_id)
        REFERENCES source_state(source_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS source_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK (
        trigger_type IN ('SCHEDULED', 'MANUAL', 'EVENT')
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'QUEUED',
            'RUNNING',
            'SUCCEEDED',
            'FAILED',
            'VALIDATION_FAILED',
            'SKIPPED'
        )
    ),
    created_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    finished_at_utc TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    items_seen INTEGER NOT NULL DEFAULT 0
        CHECK (items_seen >= 0),
    items_accepted INTEGER NOT NULL DEFAULT 0
        CHECK (items_accepted >= 0),
    items_rejected INTEGER NOT NULL DEFAULT 0
        CHECK (items_rejected >= 0),
    source_revision TEXT,
    response_etag TEXT,
    content_sha256 TEXT,
    error_code TEXT,
    error_message TEXT,
    UNIQUE (run_id, source_id),
    FOREIGN KEY (source_id)
        REFERENCES source_state(source_id)
        ON DELETE RESTRICT,
    CHECK (status != 'RUNNING' OR started_at_utc IS NOT NULL),
    CHECK (status != 'QUEUED' OR started_at_utc IS NULL),
    CHECK (
        status NOT IN (
            'SUCCEEDED',
            'FAILED',
            'VALIDATION_FAILED',
            'SKIPPED'
        )
        OR finished_at_utc IS NOT NULL
    ),
    CHECK (
        started_at_utc IS NULL
        OR finished_at_utc IS NULL
        OR finished_at_utc >= started_at_utc
    )
);

CREATE TABLE IF NOT EXISTS source_run_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    product_id TEXT,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('SUCCEEDED', 'FAILED', 'VALIDATION_FAILED')
    ),
    transport_status_code INTEGER,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY (run_id, source_id)
        REFERENCES source_runs(run_id, source_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (source_id, product_id)
        REFERENCES product_state(source_id, product_id)
        ON DELETE RESTRICT,
    CHECK (
        finished_at_utc IS NULL
        OR finished_at_utc >= started_at_utc
    )
);

CREATE TABLE IF NOT EXISTS source_status_history (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    run_id INTEGER,
    from_status TEXT,
    to_status TEXT NOT NULL CHECK (
        to_status IN (
            'NOT_CONNECTED',
            'ACTIVE',
            'STALE',
            'DEGRADED',
            'FAILED',
            'VALIDATION_REQUIRED',
            'RETIRED'
        )
    ),
    reason_code TEXT NOT NULL,
    changed_at_utc TEXT NOT NULL,
    FOREIGN KEY (source_id)
        REFERENCES source_state(source_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (run_id, source_id)
        REFERENCES source_runs(run_id, source_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS product_status_history (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    run_id INTEGER,
    from_status TEXT,
    to_status TEXT NOT NULL CHECK (
        to_status IN (
            'NOT_CONNECTED',
            'ACTIVE',
            'STALE',
            'DEGRADED',
            'FAILED',
            'VALIDATION_REQUIRED',
            'RETIRED'
        )
    ),
    reason_code TEXT NOT NULL,
    changed_at_utc TEXT NOT NULL,
    FOREIGN KEY (source_id, product_id)
        REFERENCES product_state(source_id, product_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (run_id, source_id)
        REFERENCES source_runs(run_id, source_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_source_runs_source_created
    ON source_runs(source_id, created_at_utc);

CREATE INDEX IF NOT EXISTS idx_source_runs_status_created
    ON source_runs(status, created_at_utc);

CREATE INDEX IF NOT EXISTS idx_source_run_attempts_run
    ON source_run_attempts(run_id, attempt_number);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_run_attempts_source_unique
    ON source_run_attempts(run_id, attempt_number)
    WHERE product_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_run_attempts_product_unique
    ON source_run_attempts(run_id, product_id, attempt_number)
    WHERE product_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_status_history_source_changed
    ON source_status_history(source_id, changed_at_utc);

CREATE INDEX IF NOT EXISTS idx_product_status_history_product_changed
    ON product_status_history(source_id, product_id, changed_at_utc);
"""


@dataclass(frozen=True)
class SyncSummary:
    sources_added: int = 0
    sources_reactivated: int = 0
    sources_retired: int = 0
    products_added: int = 0
    products_reactivated: int = 0
    products_retired: int = 0


def initialize_state_db(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path is not None else DEFAULT_STATE_DB
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError(
                f"Unsupported state database schema version: {version}"
            )
        connection.executescript(_SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    finally:
        connection.close()

    return path


def connect_state_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else DEFAULT_STATE_DB
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Operational state database not found: {path}")

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _insert_source_status_history(
    connection: sqlite3.Connection,
    source_id: str,
    from_status: str | None,
    to_status: str,
    reason_code: str,
    changed_at_utc: str,
) -> None:
    connection.execute(
        """
        INSERT INTO source_status_history (
            source_id, from_status, to_status, reason_code, changed_at_utc
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_id, from_status, to_status, reason_code, changed_at_utc),
    )


def _insert_product_status_history(
    connection: sqlite3.Connection,
    source_id: str,
    product_id: str,
    from_status: str | None,
    to_status: str,
    reason_code: str,
    changed_at_utc: str,
) -> None:
    connection.execute(
        """
        INSERT INTO product_status_history (
            source_id, product_id, from_status, to_status, reason_code,
            changed_at_utc
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            product_id,
            from_status,
            to_status,
            reason_code,
            changed_at_utc,
        ),
    )


def _transition_source(
    connection: sqlite3.Connection,
    source_id: str,
    from_status: str,
    to_status: str,
    reason_code: str,
    changed_at_utc: str,
) -> None:
    connection.execute(
        """
        UPDATE source_state
        SET status = ?, next_due_at_utc = NULL, updated_at_utc = ?
        WHERE source_id = ?
        """,
        (to_status, changed_at_utc, source_id),
    )
    _insert_source_status_history(
        connection,
        source_id,
        from_status,
        to_status,
        reason_code,
        changed_at_utc,
    )


def _transition_product(
    connection: sqlite3.Connection,
    source_id: str,
    product_id: str,
    from_status: str,
    to_status: str,
    reason_code: str,
    changed_at_utc: str,
) -> None:
    connection.execute(
        """
        UPDATE product_state
        SET status = ?, next_due_at_utc = NULL, updated_at_utc = ?
        WHERE source_id = ? AND product_id = ?
        """,
        (to_status, changed_at_utc, source_id, product_id),
    )
    _insert_product_status_history(
        connection,
        source_id,
        product_id,
        from_status,
        to_status,
        reason_code,
        changed_at_utc,
    )


def _reactivate_source(
    connection: sqlite3.Connection,
    source_id: str,
    changed_at_utc: str,
) -> None:
    connection.execute(
        """
        UPDATE source_state
        SET status = 'NOT_CONNECTED',
            consecutive_failures = 0,
            last_error_code = NULL,
            last_error_message = NULL,
            next_due_at_utc = NULL,
            updated_at_utc = ?
        WHERE source_id = ?
        """,
        (changed_at_utc, source_id),
    )
    _insert_source_status_history(
        connection,
        source_id,
        "RETIRED",
        "NOT_CONNECTED",
        "REACTIVATED_IN_REGISTRY",
        changed_at_utc,
    )


def _reactivate_product(
    connection: sqlite3.Connection,
    source_id: str,
    product_id: str,
    changed_at_utc: str,
) -> None:
    connection.execute(
        """
        UPDATE product_state
        SET status = 'NOT_CONNECTED',
            consecutive_failures = 0,
            last_error_code = NULL,
            last_error_message = NULL,
            next_due_at_utc = NULL,
            updated_at_utc = ?
        WHERE source_id = ? AND product_id = ?
        """,
        (changed_at_utc, source_id, product_id),
    )
    _insert_product_status_history(
        connection,
        source_id,
        product_id,
        "RETIRED",
        "NOT_CONNECTED",
        "REACTIVATED_IN_REGISTRY",
        changed_at_utc,
    )


def sync_registry_state(
    registry: dict[str, Any],
    db_path: str | Path | None = None,
    now_utc: str | None = None,
) -> SyncSummary:
    sources = registry["sources"]
    source_ids: set[str] = set()
    products_by_source: dict[str, set[str]] = {}
    for source in sources:
        source_id = source["source_id"]
        if source_id in source_ids:
            raise ValueError(f"Duplicate source_id in registry: {source_id}")
        source_ids.add(source_id)

        product_ids = [product["product_id"] for product in source["products"]]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError(f"Duplicate product_id for source: {source_id}")
        products_by_source[source_id] = set(product_ids)

    timestamp = now_utc or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    connection = connect_state_db(db_path)
    counters = {
        "sources_added": 0,
        "sources_reactivated": 0,
        "sources_retired": 0,
        "products_added": 0,
        "products_reactivated": 0,
        "products_retired": 0,
    }

    try:
        connection.execute("BEGIN IMMEDIATE")
        existing_sources = {
            row["source_id"]: row["status"]
            for row in connection.execute(
                "SELECT source_id, status FROM source_state"
            )
        }

        for source in sources:
            source_id = source["source_id"]
            current_source_status = existing_sources.get(source_id)
            if current_source_status is None:
                connection.execute(
                    """
                    INSERT INTO source_state (
                        source_id, status, updated_at_utc
                    )
                    VALUES (?, 'NOT_CONNECTED', ?)
                    """,
                    (source_id, timestamp),
                )
                _insert_source_status_history(
                    connection,
                    source_id,
                    None,
                    "NOT_CONNECTED",
                    "ADDED_TO_REGISTRY",
                    timestamp,
                )
                counters["sources_added"] += 1
            elif current_source_status == "RETIRED":
                _reactivate_source(connection, source_id, timestamp)
                counters["sources_reactivated"] += 1

            existing_products = {
                row["product_id"]: row["status"]
                for row in connection.execute(
                    """
                    SELECT product_id, status
                    FROM product_state
                    WHERE source_id = ?
                    """,
                    (source_id,),
                )
            }
            desired_product_ids = products_by_source[source_id]

            for product in source["products"]:
                product_id = product["product_id"]
                current_product_status = existing_products.get(product_id)
                if current_product_status is None:
                    connection.execute(
                        """
                        INSERT INTO product_state (
                            source_id, product_id, status, updated_at_utc
                        )
                        VALUES (?, ?, 'NOT_CONNECTED', ?)
                        """,
                        (source_id, product_id, timestamp),
                    )
                    _insert_product_status_history(
                        connection,
                        source_id,
                        product_id,
                        None,
                        "NOT_CONNECTED",
                        "ADDED_TO_REGISTRY",
                        timestamp,
                    )
                    counters["products_added"] += 1
                elif current_product_status == "RETIRED":
                    _reactivate_product(
                        connection,
                        source_id,
                        product_id,
                        timestamp,
                    )
                    counters["products_reactivated"] += 1

            for product_id, status in existing_products.items():
                if (
                    product_id not in desired_product_ids
                    and status != "RETIRED"
                ):
                    _transition_product(
                        connection,
                        source_id,
                        product_id,
                        status,
                        "RETIRED",
                        "REMOVED_FROM_REGISTRY",
                        timestamp,
                    )
                    counters["products_retired"] += 1

        for source_id, status in existing_sources.items():
            if source_id in source_ids:
                continue
            if status != "RETIRED":
                _transition_source(
                    connection,
                    source_id,
                    status,
                    "RETIRED",
                    "REMOVED_FROM_REGISTRY",
                    timestamp,
                )
                counters["sources_retired"] += 1

            existing_products = connection.execute(
                """
                SELECT product_id, status
                FROM product_state
                WHERE source_id = ?
                """,
                (source_id,),
            )
            for product_row in existing_products:
                product_status = product_row["status"]
                if product_status != "RETIRED":
                    _transition_product(
                        connection,
                        source_id,
                        product_row["product_id"],
                        product_status,
                        "RETIRED",
                        "SOURCE_REMOVED_FROM_REGISTRY",
                        timestamp,
                    )
                    counters["products_retired"] += 1

        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()

    return SyncSummary(**counters)


if __name__ == "__main__":
    print(initialize_state_db())

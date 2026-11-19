from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import sqlite3
from typing import Any

from eurusd_ai_monitor.models.correction_lifecycle import (
    CorrectionLifecycle,
    LifecycleState,
    TransitionResult,
    TransitionType,
)
from eurusd_ai_monitor.models.impulse import (
    _datetime_to_string,
    _evidence_from_dict,
    _evidence_to_dict,
)
from eurusd_ai_monitor.storage.market_data_store import (
    MarketDataStore,
    _timestamp_from_db,
    _timestamp_to_db,
    _utc_datetime,
    _validate_identifier,
)


class LifecycleStoreStatus(str, Enum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    CHECKPOINTED = "CHECKPOINTED"
    ALREADY_APPLIED = "ALREADY_APPLIED"


class LifecycleStoreError(RuntimeError):
    """Base error for lifecycle persistence failures."""


class LifecycleConcurrencyConflict(LifecycleStoreError):
    """The caller's expected record version is stale."""


class LifecycleRevisionConflict(LifecycleStoreError):
    """The M5 candle revision stream changed after analysis."""


class LifecycleIntegrityError(LifecycleStoreError):
    """Persisted lifecycle state or event history is inconsistent."""


@dataclass(frozen=True)
class LifecycleSaveResult:
    status: LifecycleStoreStatus
    lifecycle_id: str
    state_version: int
    record_version: int
    event_id: str | None = None
    event_sequence: int | None = None


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    event_sequence: int
    transition: TransitionResult
    revision_watermark: int
    created_at_utc: datetime


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _utc_text(value: datetime, field_name: str) -> str:
    return _timestamp_to_db(_utc_datetime(value, field_name))


class LifecycleStore:
    """Atomic persistence adapter for correction lifecycle snapshots and events.

    MarketDataStore owns the database and schema. This class uses its existing
    connection factory and never initializes or migrates the database.
    """

    _ACTIVE_STATES = (
        LifecycleState.CANDIDATE.value,
        LifecycleState.CONFIRMED.value,
        LifecycleState.DEEPENING.value,
    )
    _CANONICALIZATION_VERSION = 1

    def __init__(self, market_data_store: MarketDataStore) -> None:
        if not isinstance(market_data_store, MarketDataStore):
            raise TypeError("market_data_store must be a MarketDataStore")
        self._market_data_store = market_data_store

    @staticmethod
    def _validate_watermark(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("revision_watermark must be a non-negative integer")

    @staticmethod
    def _event_payload(
        result: TransitionResult,
        revision_watermark: int,
    ) -> dict[str, Any]:
        if result.lifecycle is None:
            raise ValueError("a persisted transition must contain a lifecycle")
        return {
            "canonicalization_version": LifecycleStore._CANONICALIZATION_VERSION,
            "lifecycle_id": result.lifecycle.lifecycle_id,
            "transition_type": result.transition_type.value,
            "previous_state": (
                result.previous_state.value if result.previous_state is not None else None
            ),
            "current_state": (
                result.current_state.value if result.current_state is not None else None
            ),
            "occurred_at_utc": _datetime_to_string(result.occurred_at_utc),
            "reason_codes": list(result.reason_codes),
            "evidence_refs": [_evidence_to_dict(ref) for ref in result.evidence_refs],
            "lifecycle_snapshot": result.lifecycle.to_dict(),
            "revision_watermark": revision_watermark,
        }

    @classmethod
    def _event_id(cls, payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return f"sha256:v{cls._CANONICALIZATION_VERSION}:{digest}"

    def save_transition(
        self,
        result: TransitionResult,
        *,
        expected_record_version: int | None,
        revision_watermark: int,
        created_at_utc: datetime,
    ) -> LifecycleSaveResult | None:
        """Persist a transition or progressed NO_TRANSITION checkpoint.

        Returns None for a no-op NO_TRANSITION with no durable snapshot progress.
        """
        if not isinstance(result, TransitionResult):
            raise TypeError("result must be a TransitionResult")
        self._validate_watermark(revision_watermark)
        created_text = _utc_text(created_at_utc, "created_at_utc")
        lifecycle = result.lifecycle
        if lifecycle is None:
            if result.transition_type is TransitionType.NO_TRANSITION:
                return None
            raise ValueError("transition must contain a lifecycle")
        if expected_record_version is not None and (
            isinstance(expected_record_version, bool)
            or not isinstance(expected_record_version, int)
            or expected_record_version <= 0
        ):
            raise ValueError("expected_record_version must be a positive integer or None")

        broker = lifecycle.broker_server
        symbol = lifecycle.symbol
        lifecycle_id = lifecycle.lifecycle_id
        snapshot_json = _canonical_json(lifecycle.to_dict())
        is_event = result.transition_type is not TransitionType.NO_TRANSITION
        payload = self._event_payload(result, revision_watermark) if is_event else None
        event_id = self._event_id(payload) if payload is not None else None
        event_payload_json = _canonical_json(payload) if payload is not None else None

        with closing(self._market_data_store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if event_id is not None:
                    existing_event = connection.execute(
                        """
                        SELECT lifecycle_id, transition_type, previous_state,
                               current_state, occurred_at_utc, reason_codes_json,
                               evidence_refs_json, lifecycle_snapshot_json,
                               revision_watermark
                        FROM pa_lifecycle_events
                        WHERE event_id = ?
                        """,
                        (event_id,),
                    ).fetchone()
                    if existing_event is not None:
                        stored_payload = {
                            "canonicalization_version": self._CANONICALIZATION_VERSION,
                            "lifecycle_id": existing_event["lifecycle_id"],
                            "transition_type": existing_event["transition_type"],
                            "previous_state": existing_event["previous_state"],
                            "current_state": existing_event["current_state"],
                            "occurred_at_utc": _datetime_to_string(
                                _timestamp_from_db(existing_event["occurred_at_utc"])
                            ),
                            "reason_codes": json.loads(existing_event["reason_codes_json"]),
                            "evidence_refs": json.loads(existing_event["evidence_refs_json"]),
                            "lifecycle_snapshot": json.loads(
                                existing_event["lifecycle_snapshot_json"]
                            ),
                            "revision_watermark": int(existing_event["revision_watermark"]),
                        }
                        # Compare the persisted semantic fields. Event IDs are content hashes.
                        if (
                            existing_event["lifecycle_id"] != lifecycle_id
                            or _canonical_json(stored_payload) != event_payload_json
                        ):
                            raise LifecycleIntegrityError(
                                "event ID exists with a different canonical payload"
                            )
                        state_row = connection.execute(
                            """
                            SELECT state_version, record_version
                            FROM pa_lifecycle_state WHERE lifecycle_id = ?
                            """,
                            (lifecycle_id,),
                        ).fetchone()
                        if state_row is None:
                            raise LifecycleIntegrityError(
                                "event exists but its lifecycle snapshot is missing"
                            )
                        connection.commit()
                        sequence_row = connection.execute(
                            "SELECT event_sequence FROM pa_lifecycle_events WHERE event_id = ?",
                            (event_id,),
                        ).fetchone()
                        return LifecycleSaveResult(
                            LifecycleStoreStatus.ALREADY_APPLIED,
                            lifecycle_id,
                            int(state_row["state_version"]),
                            int(state_row["record_version"]),
                            event_id,
                            int(sequence_row["event_sequence"]),
                        )

                current_watermark = self._watermark_on_connection(
                    connection, broker, symbol
                )
                if current_watermark != revision_watermark:
                    raise LifecycleRevisionConflict(
                        "M5 revision watermark changed: "
                        f"analysis={revision_watermark}, current={current_watermark}"
                    )

                current = connection.execute(
                    """
                    SELECT broker_server, symbol, state, state_version, record_version,
                           algorithm_version, parameter_version,
                           last_processed_m5_utc, revision_watermark, snapshot_json
                    FROM pa_lifecycle_state
                    WHERE lifecycle_id = ?
                    """,
                    (lifecycle_id,),
                ).fetchone()

                if current is None:
                    if expected_record_version is not None:
                        raise LifecycleConcurrencyConflict(
                            "lifecycle does not exist at expected record_version"
                        )
                    if result.transition_type is not TransitionType.CREATED:
                        raise LifecycleIntegrityError(
                            "a new lifecycle must be persisted with CREATED"
                        )
                    if result.previous_state is not None or lifecycle.state is not LifecycleState.CANDIDATE:
                        raise LifecycleIntegrityError(
                            "initial lifecycle must transition from None to CANDIDATE"
                        )
                    if lifecycle.state_version != 0:
                        raise LifecycleIntegrityError(
                            "initial lifecycle state_version must be zero"
                        )
                    active = connection.execute(
                        """
                        SELECT lifecycle_id FROM pa_lifecycle_state
                        WHERE broker_server = ? AND symbol = ?
                          AND state IN (?, ?, ?)
                        """,
                        (broker, symbol, *self._ACTIVE_STATES),
                    ).fetchone()
                    if active is not None:
                        raise LifecycleConcurrencyConflict(
                            "another active lifecycle already exists for this stream"
                        )
                    record_version = 1
                    state_version = lifecycle.state_version
                    connection.execute(
                        """
                        INSERT INTO pa_lifecycle_state (
                            lifecycle_id, broker_server, symbol, state,
                            state_version, record_version, algorithm_version,
                            parameter_version, last_processed_m5_utc,
                            revision_watermark, snapshot_json, updated_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            lifecycle_id, broker, symbol, lifecycle.state.value,
                            state_version, record_version, lifecycle.algorithm_version,
                            lifecycle.parameter_version,
                            _timestamp_to_db(lifecycle.last_processed_m5_utc),
                            revision_watermark, snapshot_json, created_text,
                        ),
                    )
                    status = LifecycleStoreStatus.CREATED
                else:
                    if expected_record_version is None:
                        raise LifecycleConcurrencyConflict(
                            "existing lifecycle requires expected_record_version"
                        )
                    stored_record_version = int(current["record_version"])
                    if stored_record_version != expected_record_version:
                        raise LifecycleConcurrencyConflict(
                            f"expected record_version {expected_record_version}, "
                            f"found {stored_record_version}"
                        )
                    if current["broker_server"] != broker or current["symbol"] != symbol:
                        raise LifecycleIntegrityError("lifecycle broker/symbol identity changed")
                    if current["state"] in (
                        LifecycleState.RESOLVED.value,
                        LifecycleState.INVALIDATED.value,
                        LifecycleState.EXPIRED.value,
                    ):
                        raise LifecycleIntegrityError("terminal lifecycle is immutable")
                    if current["algorithm_version"] != lifecycle.algorithm_version or current[
                        "parameter_version"
                    ] != lifecycle.parameter_version:
                        raise LifecycleIntegrityError("lifecycle algorithm/config version changed")
                    previous_state = LifecycleState(current["state"])
                    if result.previous_state is not previous_state:
                        raise LifecycleIntegrityError(
                            "transition previous_state does not match persisted state"
                        )
                    if result.transition_type is TransitionType.NO_TRANSITION:
                        if lifecycle.state is not previous_state:
                            raise LifecycleIntegrityError(
                                "NO_TRANSITION checkpoint cannot change lifecycle state"
                            )
                        if lifecycle.state_version != int(current["state_version"]):
                            raise LifecycleIntegrityError(
                                "checkpoint cannot change state_version"
                            )
                        previous_snapshot = json.loads(current["snapshot_json"])
                        if previous_snapshot == lifecycle.to_dict():
                            connection.commit()
                            return None
                        status = LifecycleStoreStatus.CHECKPOINTED
                    else:
                        if lifecycle.state_version != int(current["state_version"]) + 1:
                            raise LifecycleIntegrityError(
                                "real transition must increment state_version exactly once"
                            )
                        status = LifecycleStoreStatus.UPDATED

                    record_version = stored_record_version + 1
                    state_version = lifecycle.state_version
                    cursor = connection.execute(
                        """
                        UPDATE pa_lifecycle_state
                        SET state = ?, state_version = ?, record_version = ?,
                            last_processed_m5_utc = ?, revision_watermark = ?,
                            snapshot_json = ?, updated_at_utc = ?
                        WHERE lifecycle_id = ? AND record_version = ?
                        """,
                        (
                            lifecycle.state.value, state_version, record_version,
                            _timestamp_to_db(lifecycle.last_processed_m5_utc),
                            revision_watermark, snapshot_json, created_text,
                            lifecycle_id, stored_record_version,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise LifecycleConcurrencyConflict(
                            "lifecycle record changed during optimistic update"
                        )

                event_sequence = None
                if event_id is not None:
                    history = connection.execute(
                        """
                        SELECT COUNT(*) AS event_count,
                               COALESCE(MAX(event_sequence), 0) AS max_sequence
                        FROM pa_lifecycle_events WHERE lifecycle_id = ?
                        """,
                        (lifecycle_id,),
                    ).fetchone()
                    if int(history["event_count"]) != int(history["max_sequence"]):
                        raise LifecycleIntegrityError(
                            "existing lifecycle event sequence is not contiguous"
                        )
                    event_sequence = int(history["max_sequence"]) + 1
                    connection.execute(
                        """
                        INSERT INTO pa_lifecycle_events (
                            event_id, lifecycle_id, event_sequence, transition_type,
                            previous_state, current_state, occurred_at_utc,
                            reason_codes_json, evidence_refs_json,
                            lifecycle_snapshot_json, revision_watermark, created_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id, lifecycle_id, event_sequence,
                            result.transition_type.value,
                            result.previous_state.value if result.previous_state else None,
                            result.current_state.value,
                            _timestamp_to_db(result.occurred_at_utc),
                            _canonical_json(list(result.reason_codes)),
                            _canonical_json([_evidence_to_dict(ref) for ref in result.evidence_refs]),
                            snapshot_json, revision_watermark, created_text,
                        ),
                    )

                connection.commit()
                return LifecycleSaveResult(
                    status, lifecycle_id, state_version, record_version,
                    event_id, event_sequence,
                )
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _watermark_on_connection(
        connection: sqlite3.Connection,
        broker_server: str,
        symbol: str,
    ) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(revision_id), 0) AS watermark
            FROM candle_revisions
            WHERE broker_server = ? AND symbol = ? AND timeframe = 'M5'
            """,
            (broker_server, symbol),
        ).fetchone()
        return int(row["watermark"])

    def get_revision_watermark(self, broker_server: str, symbol: str) -> int:
        _validate_identifier(broker_server, "broker_server")
        _validate_identifier(symbol, "symbol")
        with closing(self._market_data_store._connect()) as connection:
            return self._watermark_on_connection(connection, broker_server, symbol)

    def load_by_id(self, lifecycle_id: str) -> CorrectionLifecycle | None:
        _validate_identifier(lifecycle_id, "lifecycle_id")
        with closing(self._market_data_store._connect()) as connection:
            row = connection.execute(
                "SELECT lifecycle_id, state, broker_server, symbol, snapshot_json FROM pa_lifecycle_state WHERE lifecycle_id = ?",
                (lifecycle_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            lifecycle = CorrectionLifecycle.from_dict(json.loads(row["snapshot_json"]))
            if (
                lifecycle.lifecycle_id != row["lifecycle_id"]
                or lifecycle.state.value != row["state"]
                or lifecycle.broker_server != row["broker_server"]
                or lifecycle.symbol != row["symbol"]
            ):
                raise LifecycleIntegrityError("snapshot identity/state differs from indexed row")
            return lifecycle
        except Exception as exc:
            raise LifecycleIntegrityError(
                f"corrupt lifecycle snapshot for {lifecycle_id}"
            ) from exc

    def load_active(self, broker_server: str, symbol: str) -> CorrectionLifecycle | None:
        _validate_identifier(broker_server, "broker_server")
        _validate_identifier(symbol, "symbol")
        with closing(self._market_data_store._connect()) as connection:
            rows = connection.execute(
                """
                SELECT lifecycle_id, state, broker_server, symbol, snapshot_json
                FROM pa_lifecycle_state
                WHERE broker_server = ? AND symbol = ?
                ORDER BY updated_at_utc DESC
                """,
                (broker_server, symbol),
            ).fetchall()

        active: list[CorrectionLifecycle] = []
        for row in rows:
            try:
                lifecycle = CorrectionLifecycle.from_dict(json.loads(row["snapshot_json"]))
                if (
                    lifecycle.lifecycle_id != row["lifecycle_id"]
                    or lifecycle.state.value != row["state"]
                    or lifecycle.broker_server != row["broker_server"]
                    or lifecycle.symbol != row["symbol"]
                ):
                    raise LifecycleIntegrityError(
                        "snapshot identity/state differs from indexed row"
                    )
            except Exception as exc:
                raise LifecycleIntegrityError(
                    f"corrupt lifecycle snapshot for {row['lifecycle_id']}"
                ) from exc
            if lifecycle.state.value in self._ACTIVE_STATES:
                active.append(lifecycle)

        if len(active) > 1:
            raise LifecycleIntegrityError(
                "multiple active lifecycles exist for one broker/symbol stream"
            )
        return active[0] if active else None

    def get_events(
        self,
        lifecycle_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[LifecycleEvent]:
        _validate_identifier(lifecycle_id, "lifecycle_id")
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        with closing(self._market_data_store._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_sequence, transition_type, previous_state,
                       current_state, occurred_at_utc, reason_codes_json,
                       evidence_refs_json, lifecycle_snapshot_json,
                       revision_watermark, created_at_utc
                FROM pa_lifecycle_events
                WHERE lifecycle_id = ? AND event_sequence > ?
                ORDER BY event_sequence ASC LIMIT ?
                """,
                (lifecycle_id, after_sequence, limit),
            ).fetchall()
        events: list[LifecycleEvent] = []
        expected_sequence = after_sequence + 1
        for row in rows:
            sequence = int(row["event_sequence"])
            if sequence != expected_sequence:
                raise LifecycleIntegrityError(
                    f"event sequence gap: expected {expected_sequence}, found {sequence}"
                )
            expected_sequence += 1
            try:
                lifecycle = CorrectionLifecycle.from_dict(
                    json.loads(row["lifecycle_snapshot_json"])
                )
                evidence = tuple(
                    _evidence_from_dict(item)
                    for item in json.loads(row["evidence_refs_json"])
                )
                transition = TransitionResult(
                    transition_type=TransitionType(row["transition_type"]),
                    previous_state=(
                        LifecycleState(row["previous_state"])
                        if row["previous_state"] is not None else None
                    ),
                    current_state=LifecycleState(row["current_state"]),
                    lifecycle=lifecycle,
                    occurred_at_utc=_timestamp_from_db(row["occurred_at_utc"]),
                    reason_codes=tuple(json.loads(row["reason_codes_json"])),
                    evidence_refs=evidence,
                )
                events.append(
                    LifecycleEvent(
                        event_id=row["event_id"],
                        event_sequence=sequence,
                        transition=transition,
                        revision_watermark=int(row["revision_watermark"]),
                        created_at_utc=_timestamp_from_db(row["created_at_utc"]),
                    )
                )
            except Exception as exc:
                if isinstance(exc, LifecycleIntegrityError):
                    raise
                raise LifecycleIntegrityError(
                    f"corrupt lifecycle event {row['event_id']}"
                ) from exc
        return events

    def get_last_processed(
        self,
        broker_server: str,
        symbol: str,
    ) -> datetime | None:
        lifecycle = self.load_active(broker_server, symbol)
        return lifecycle.last_processed_m5_utc if lifecycle is not None else None

# Phase 3.4 — LifecycleStore Contract

**Status:** Approved design baseline for PR #7  
**Target branch:** `main`  
**Implementation branch:** `phase3.4-lifecycle-store`  
**Scope:** Persistence and deterministic retrieval only. No Runtime integration, lifecycle detection, recovery orchestration, or trade authority.

## 1. Purpose and boundaries

`LifecycleStore` persists immutable `CorrectionLifecycle` snapshots and their `TransitionResult` event history in the existing MarketDataStore SQLite database.

It MUST NOT:
- calculate pivots, trends, impulses, corrections, or lifecycle transitions;
- read MT5, wall-clock time, configuration files, or environment state;
- make BUY/SELL decisions or grant trade authority;
- mutate the RAG database or existing market candle records.

The store receives all timestamps, expected versions, and revision watermarks explicitly from its caller.

## 2. Database ownership

`MarketDataStore` remains the sole owner of database initialization, schema migrations, connections, and transaction policy. `LifecycleStore` is a repository adapter over the same database path and MUST NOT execute `PRAGMA user_version`, migrations, or create parallel databases.

The existing schema v3 tables are used:
- `pa_lifecycle_state`: latest durable snapshot and optimistic concurrency versions;
- `pa_lifecycle_events`: append-only transition history;
- `pa_lifecycle_recovery`: stream-level recovery status (consumed/managed in the later Recovery Manager PR).

The event table's SQLite triggers prohibiting UPDATE and DELETE remain authoritative.

## 3. Public API

The initial API is deliberately narrow:

- `save_transition(result, *, expected_record_version, revision_watermark, created_at_utc)`
  - Persist a real transition or a progressed NO_TRANSITION checkpoint.
  - Return a typed result with status, lifecycle ID, state version, and record version.
- `load_active(broker_server, symbol)`
  - Return the sole active lifecycle, or None; detect impossible multiple-active corruption rather than selecting arbitrarily.
- `load_by_id(lifecycle_id)`
  - Return the validated snapshot or None.
- `get_events(lifecycle_id, *, after_sequence=0, limit=500)`
  - Return events in ascending contiguous sequence order.
- `get_last_processed(broker_server, symbol)`
  - Return the active snapshot's last processed M5 candle open time, if present.

Exact Python signatures and result dataclasses may be refined during implementation, but semantics below are binding.

## 4. Atomic write contract

Every write uses one SQLite connection and one `BEGIN IMMEDIATE` transaction.

For a real transition:
1. Canonicalize and validate the input outside the transaction.
2. Derive a deterministic event ID from canonical transition content and the supplied revision watermark.
3. Begin an immediate transaction.
4. Check whether that event ID already exists. If its canonical stored content matches, return `ALREADY_APPLIED`; if not, raise an integrity conflict.
5. Read current lifecycle row and validate `expected_record_version`.
6. Validate stream identity, legal state progression, and version progression.
7. Insert/update the lifecycle snapshot.
8. Append exactly one event with next sequence number.
9. Commit.

For a progressed `NO_TRANSITION`:
- persist a checkpoint snapshot only when `last_processed_m5_utc`, `age_bars`, evidence/depth, or another persisted snapshot field actually advances;
- do not append an event;
- do not increment `state_version`;
- increment `record_version`.

For a no-op `NO_TRANSITION`, do not write.

Any exception before commit MUST roll back both snapshot and event. The store MUST NOT report success before commit.

## 5. Version semantics

- `state_version` counts actual state transitions only. The initial CANDIDATE snapshot starts at 0; each subsequent real transition increments it by exactly one.
- `record_version` counts every successful durable snapshot write, including checkpoint-only writes. A newly created row starts at 1.
- Existing-row writes require an explicit expected `record_version`; stale writers receive a typed conflict / exception and cannot overwrite newer data.
- Creating a lifecycle requires no existing active lifecycle for the broker/symbol stream. The database partial unique index remains a final guard.

## 6. Idempotency and canonical serialization

Event IDs are deterministic SHA-256 digests over a versioned canonical representation containing:
- lifecycle ID;
- transition type and previous/current state;
- occurrence timestamp;
- ordered reason codes and evidence references;
- complete lifecycle snapshot;
- revision watermark;
- canonicalization schema version.

Canonical JSON uses sorted keys, compact separators, UTF-8, ISO-8601 UTC timestamps, and Decimal values serialized as finite decimal strings (never binary floats).

A repeated event with the same ID and same canonical payload returns `ALREADY_APPLIED`. Same ID with different payload is an integrity error. Event sequence is allocated under the write transaction and is unique and contiguous per lifecycle.

## 7. Revision watermark and M5 consistency

The lifecycle is M5-driven in this phase. The persisted watermark therefore refers explicitly to the M5 revision stream for the same broker and symbol; it MUST NOT silently mix M1 and M5 revision IDs.

The caller supplies the watermark associated with the exact candle snapshot used for analysis. During save, while holding `BEGIN IMMEDIATE`, the store reads the current M5 revision watermark from the same database connection. If it differs from the supplied watermark, the write is rejected as stale and the caller must request reconciliation. The store never silently upgrades the watermark on behalf of stale analysis.

The implementation must use the same database connection for the watermark check and lifecycle write, avoiding a race between checking the revision stream and committing the snapshot.

## 8. Read and integrity contract

- Snapshot JSON is decoded through `CorrectionLifecycle.from_dict`; malformed or invalid snapshots raise a corruption error and are never silently skipped.
- Event JSON is decoded and validated; event history is returned in ascending sequence.
- A sequence gap, duplicate, invalid transition payload, or mismatch between latest event snapshot and state snapshot is reported as integrity corruption for the later Recovery Manager to quarantine.
- Terminal states are never returned as active.
- Read APIs do not modify the database.

## 9. Statuses and failure semantics

Expected write statuses:
- `CREATED`
- `UPDATED`
- `CHECKPOINTED`
- `ALREADY_APPLIED`

Conflicts and failures are exceptions, not success statuses:
- optimistic concurrency conflict;
- stale revision watermark;
- duplicate active lifecycle;
- idempotency payload mismatch;
- invalid lifecycle/event sequence;
- database integrity or serialization corruption.

## 10. Required tests

1. Create candidate snapshot and first event atomically.
2. Persist every legal transition with matching snapshot and event.
3. Inject failure between snapshot write and event append; verify full rollback.
4. Replay identical event; verify no duplicate and stable versions.
5. Reuse an event ID with changed payload; verify integrity failure.
6. Race two writers with the same expected record version; only one may commit.
7. Save a progressed NO_TRANSITION checkpoint without appending an event.
8. No-op NO_TRANSITION produces no database write.
9. Close/reopen database and reconstruct exact lifecycle snapshot.
10. Reject stale M5 revision watermark.
11. Verify event sequences are contiguous and append-only.
12. Detect corrupt JSON, event gaps, and snapshot/event mismatch.
13. Verify terminal lifecycle is not returned by load_active.
14. Verify broker/symbol isolation and one-active-lifecycle constraint.

## 11. Explicit exclusions

This PR does not implement:
- startup recovery or revision replay;
- NORMAL / RECONCILIATION / QUARANTINED policy;
- Runtime wiring or automatic lifecycle processing;
- M1 evidence watermarking;
- trading signals, orders, or execution.

Those remain separate, reviewed stages. `trade_authority` remains `NONE`.

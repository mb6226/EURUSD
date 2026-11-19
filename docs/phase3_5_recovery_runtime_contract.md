# Phase 3.5 — Lifecycle Recovery and Runtime Integration

## Scope

This phase completes the operational path for the persisted Price Action lifecycle:

`MarketContextBuilder → TechnicalEngine → PriceActionCoordinator → LifecycleStore → Runtime Output`

It adds startup recovery validation and wires the runtime into the existing monitor loop. The legacy decision engine remains unchanged and continues to own the current top-level decision. Price Action lifecycle output is additive and has no trade authority.

## Startup recovery

`LifecycleRecoveryManager.recover_stream(broker_server, symbol, config)` performs a fail-closed validation before the stream is processed:

1. Load the persisted lifecycle stream and current M5 revision watermark.
2. Audit every stored lifecycle snapshot and its append-only event chain.
3. For an active lifecycle, compare its stored algorithm and parameter versions with the current StrategyConfig-derived versions.
4. Compare each M5 evidence candle referenced by the active lifecycle with the canonical closed candle in MarketDataStore.
5. Persist the recovery decision in `pa_lifecycle_recovery`.

Recovery statuses:

- `NORMAL`: the stream is consistent and may be processed.
- `RECONCILIATION`: an M5 candle revision has occurred since the active lifecycle checkpoint. Processing is blocked until a separately approved replay/reconciliation workflow exists.
- `QUARANTINED`: stored snapshots, event history, versions, or evidence provenance failed integrity checks. Processing is blocked.

A missing recovery record is treated as `RECONCILIATION`, never as NORMAL.

## Runtime integration

The monitor creates one MarketDataStore and shares it with LifecycleStore and LifecycleRecoveryManager. On the first snapshot for a broker/symbol stream, startup recovery runs once. Each snapshot is then passed to PriceActionRuntime.

The published payload now contains `price_action_lifecycle`, including runtime status, transition, lifecycle identity/state, persistence versions, recovery details, reason codes, and the explicit `trade_authority: NONE` boundary.

The legacy `decision`, `direction`, and `trade_execution` fields are not derived from this lifecycle output in this phase. No order placement or management is introduced.

## Revision policy

If a revision is detected during startup or races with runtime persistence, the recovery record is durably moved to `RECONCILIATION`. The lifecycle snapshot and event history are not silently rewritten. No automatic replay, supersession, or historical reprocessing is performed.

## Tests added

- Empty stream initializes to NORMAL and persists the result.
- Valid active lifecycle and event chain recover to NORMAL.
- M5 revision requires reconciliation without mutating the lifecycle.
- Parameter-version mismatch quarantines the stream.
- Missing evidence candle quarantines the stream.
- Missing startup recovery state fails closed.

The test suite must be run locally against the branch before merge. This repository has no configured CI workflow, and this phase does not claim a live MT5 runtime test.

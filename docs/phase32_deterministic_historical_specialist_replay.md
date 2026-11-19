# Phase 32 — Deterministic Historical Specialist Re-Execution & Scenario Replay

## North Star

Advance the comprehensive EURUSD intelligence system's historical research loop: reconstruct what was knowable at each historical instant, deterministically rerun eligible specialists from those inputs, and reassess the complete central scenario envelope without lookahead or fabricated domain coverage.

## Implementation

`DeterministicHistoricalSpecialistReplayEngine` composes Phase 31 reconstruction with deterministic specialist execution.

For every archived evaluation timestamp it:

1. Independently reconstructs M1 and M5 candles using Phase 31's read-only, point-in-time rules.
2. Builds an immutable `MarketSnapshot` from the reconstructed candles only. Missing timeframes and stale latest bars invalidate snapshot quality.
3. Re-executes the currently injected Technical, Market Regime, Quantitative Statistics and Liquidity/Microstructure engines.
4. Re-executes Macro Fundamentals, Policy Rate Differential, Intermarket and Positioning/Sentiment only when all specialist engines and a read-only point-in-time observation store are explicitly supplied. The existing shared runtime adapter retains the product/source contracts and timestamp gates.
5. Sends newly computed specialist reports plus reconstructed News and Calendar coverage states to `CentralScenarioIntelligenceEngine`.
6. Reads immutable monitor JSONL cycle timestamps through a dedicated adapter; archived specialist reports are not required or used as fallback.
7. Reports each point's candle coverage, specialist execution status, central scenario output, rejected replay points and explicit un-replayed domains.

Each recomputed report carries its current algorithm/parameter version where the specialist provides one. Replay never reads archived future specialist reports as a fallback. A missing source stays missing.

## Domain coverage and limits

| Domain | Phase 32 behavior |
|---|---|
| Technical structure | Recomputed from reconstructed closed M5 candles |
| Market regime | Recomputed from reconstructed M1/M5 candles and recomputed technical structure |
| Quantitative statistics | Recomputed from reconstructed M1/M5 candles |
| Liquidity/microstructure | Recomputed from reconstructed candles; spread remains unknown unless separately normalized historical spread evidence exists |
| Macro fundamentals | Recomputed only with configured specialist and point-in-time observation store |
| Policy differential | Recomputed only with configured specialist and point-in-time observation store |
| Intermarket | Recomputed only with configured specialist and point-in-time observation store |
| Positioning/sentiment | Recomputed only with configured specialist and point-in-time observation store |
| Price Action lifecycle | Not replayed: current lifecycle coordinator/state persistence is stateful; no isolated historical event-replay contract is introduced here |
| News semantics | Evidence is reconstructed; semantic impact specialist is not rerun because historical model/feature versions are not pinned |
| Macro-calendar impact | Event records are reconstructed; no versioned historical impact specialist is available |
| Fusion | Not recomputed as a replacement directional authority; central scenario synthesis consumes the eligible specialist reports directly |

The implementation uses currently injected deterministic algorithms. It does not claim to reproduce the exact historical code/model version that existed at the original evaluation time. A future immutable algorithm/feature registry and archived feature snapshots are required for exact historical-version parity.

## Point-in-time and safety controls

- M1 and M5 are reconstructed separately at the original timestamp; no current snapshot is substituted.
- Phase 31 candle revision rollback, closed-bar availability checks, and source publication/retrieval/effective-time gates remain authoritative.
- Snapshot quality is invalid when either timeframe is absent or its latest closed bar exceeds the existing M1/M5 freshness limits.
- An invalid snapshot blocks every specialist re-execution (including configured fundamental specialists); all are explicitly marked BLOCKED_QUALITY_GATE, and the central directional state remains unresolved.
- Fundamental observations are read only through a store opened in read-only mode.
- Specialist failures are isolated and returned as explicit unavailable reports.
- Stateful Price Action lifecycle persistence is not invoked or mutated.
- No source DB, monitor log, RAG/knowledge store, configuration or lifecycle state is written.
- No BUY/SELL, entry/exit, SL/TP, position sizing, risk setting, order execution or strategy promotion is produced.

## Acceptance

- Deterministic unit tests cover M1/M5 reconstruction orchestration, specialist re-execution, central scenario reassessment, invalid/future replay points, missing timeframe quality gates, and candle identity/value preservation.
- Run focused Phase 32 tests, full repository regression, compile checks and `git diff --check` on the exact PR head before merge.
- A replay with unavailable specialists remains explicitly partial; a processed point is not proof of complete domain coverage.

## Next dependencies

1. Add an immutable algorithm/parameter registry and feature-snapshot provenance so a replay can select the exact specialist version available at a historical timestamp.
2. Define isolated, append-only Price Action lifecycle event replay before recomputing that stateful specialist.
3. Preserve every news fetch/unchanged refresh and calendar source-health version, then version the corresponding semantic impact models.
4. Produce real-data coverage manifests and out-of-sample scenario evaluation before any uncertainty calibration.

## Non-goals

No live fetch/backfill, archive repair, database mutation, model training, probability calibration, source reliability weighting, strategy optimization, realized trading P&L claim, live signal activation or execution change.

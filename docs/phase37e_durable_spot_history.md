# Phase 37E ? Durable Spot History

## North Star contribution

This phase strengthens the canonical multi-domain evidence foundation for the whole EURUSD intelligence system. Durable spot history is a shared input for regime, quantitative, session, cross-domain, scenario, and historical replay work; it is not a Price Action-only feature.

## Repository findings

- An MT5 read-only connector already exposed UTC `copy_rates_range` access.
- An independent SQLite market store already held current candle projections, append-only correction records, and resumable bounded backfill checkpoints.
- The existing rolling M1/M5 CSVs were not a long-term archive. At inspection, the market database contained 776 candle projections, zero correction rows and zero backfill checkpoints; this does not establish one-year coverage.
- MT5 bar timestamps are UTC. OHLC chart basis must be taken from symbol chart metadata; it must not be assumed to be Bid. If metadata cannot be read, the basis is recorded as UNKNOWN.

## Deliverables

- Market store schema v4 adds `candle_ingestion_runs` and `candle_versions`.
- Every non-empty ingestion batch receives a run ID, UTC observation/as-of times, row count, normalized-batch SHA-256 and provenance metadata.
- Every newly observed distinct candle version is retained in an append-only version ledger. Re-fetching an unchanged current version is idempotent; a correction or a return to an earlier value after an intervening correction becomes a new version.
- SQLite triggers reject UPDATE/DELETE on both run and version ledgers. Existing `candles` remains the query-efficient latest projection; existing `candle_revisions` remains available for correction/recovery consumers.
- MT5 adapter calls label their source method (`copy_rates_from_pos` / `copy_rates_range`), symbol, broker server, timeframe/range and UTC time basis. The MT5 connector reports chart mode, digits, point, tick size and terminal/package versions when available.
- Existing bounded chunking, checkpoint resume, duplicate validation, OHLC validation and closed-candle gating are retained.

## Historical integrity limits

- This phase does not infer historical broker-local offsets or apply DST shifts. MT5 Unix/bar timestamps are handled as UTC; broker-local session labels require a separate verified mapping.
- `spread` in the MT5 rates structure is retained as the provider's bar spread field; it is not treated as a full historical bid/ask tick stream.
- The version ledger stores normalized candle versions and batch fingerprints, not the original binary MT5 transport response. It does not claim raw-tick reconstruction.
- Existing pre-v4 candles are not retroactively assigned fabricated versions or provenance. The schema migration creates the ledger for subsequent ingestions only.
- MT5 only returns history available in the terminal/chart history and subject to its Max bars in chart setting. Coverage must be measured; a completed request range is not proof of a complete calendar year.
- Gaps are not silently classified as market closures. The existing backfill path remains UNKNOWN on unclassified gaps until a reliable trading-calendar/session model is introduced.

## Operational boundary

No live historical broker request was made in this phase. No external provider was activated, no registry or auto-fetch setting changed, no monitor restart occurred, and no production market database was migrated while the existing monitor was running. The new schema is applied on the next controlled store initialization. No orders, risk settings, Vision, or RAG/knowledge data were changed.

## Validation

Focused tests cover schema migration, immutable versions, idempotent repeated ingestion, correction versioning, provenance persistence, and explicit UNKNOWN price-basis behavior when connector metadata is unavailable. Full-suite acceptance is recorded only after the final regression run.


## Operational activation completed in Phase51

The initial schema-v3 production archive was migrated to v4 after a verified backup and controlled monitor stop. Its 1,180 legacy candles at migration time remain unversioned. The monitor was restarted with the v4 adapter and new M1/M5 candle versions are now being recorded with actual observed/as-of timestamps and MT5 source provenance. A real-data Phase45 smoke replay generated forecast records; no target outcomes had matured at that evaluation cutoff. One-year coverage and full OOS replay remain future requirements.

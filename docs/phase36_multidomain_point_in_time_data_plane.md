# Phase 36 — Multi-Domain Point-in-Time Data Plane

## North Star

Advance the comprehensive EURUSD market-intelligence system's canonical data plane so macro policy, economic fundamentals, intermarket, positioning/sentiment, and broker spot-reference observations share one registry-driven, auditable historical read boundary. This is infrastructure for central multi-domain scenario intelligence and point-in-time validation, not a standalone trading specialist.

## Repository gap

The repository already had:
- a validated source/product registry;
- typed source adapter contracts and explicit manual ingestion;
- an append-only SQLite observation store with effective/publication/retrieval timestamps and revision history;
- a point-in-time reconstruction engine that accepted manually assembled source/product requests.

The missing integration was a single registry-driven boundary that discovers every enabled product, groups products by market domain, issues one batched as-of read, and reports coverage gaps without creating empty stores or silently omitting unpopulated domains.

## Deliverable

`source_registry/data_plane.py` adds `PointInTimeDataPlane`:
- derives five domain groups from registered source category/topics: monetary policy, macro fundamentals, intermarket, positioning/sentiment, and spot FX;
- creates the complete enabled source/product request map for Phase 31/32 reconstruction;
- performs one batched `get_many_as_of` read for an explicit timezone-aware UTC cutoff;
- reports per-product/domain status, observation counts, effective-time coverage, and overall coverage ratio;
- excludes disabled sources and preserves missing products as explicit gaps;
- requires a read-only observation store; `from_paths` opens an existing schema-valid DB read-only and never creates an empty operational database.

## Integration path

Validated `source_registry/registry.json` → `PointInTimeDataPlane.build_observation_requests()` → Phase 31/32 reconstruction's `observation_requests` argument; or `read_as_of(timestamp)` for a single unified multi-domain evidence snapshot → central research/replay consumers.

The Phase 31/32 JSONL replay runtime now accepts the data-plane object directly and derives the enabled source/product request map automatically; it records whether requests came from the registry-driven plane or an explicit caller. Supplying both paths is rejected to prevent ambiguous coverage. The existing `SourceObservationIngestion` remains the only explicit persistence path. Adapters remain injected by the caller; no provider is guessed or automatically activated.

## Safety and point-in-time semantics

- Every read requires a timezone-aware cutoff normalized to UTC.
- The existing observation store enforces effective, publication, and retrieval timestamps no later than the cutoff and excludes unknown publication time by default.
- A source/product with no eligible records is reported as MISSING, not replaced with a current value.
- A missing observation database is UNAVAILABLE and is not initialized as a side effect.
- Data plane is read-only. No source fetch, scheduler, external refresh, registry/state DB mutation, calendar/news/market DB mutation, or RAG/knowledge mutation.
- No specialist vote, scenario direction, probability, strategy, risk, BUY/SELL or order-execution behavior changes.

## Acceptance

- Registry grouping includes all enabled products across the five domains and excludes disabled products.
- A single batched as-of read returns per-product and per-domain coverage.
- Future-published, future-effective, or not-yet-retrieved records remain excluded by the existing strict store contract.
- Missing store is explicit and never created by the read-only loader.
- A writable store is rejected at the data-plane boundary.
- Focused tests, full regression, compile checks, and diff validation pass locally.

## Current data reality at implementation start

The registry contains 9 sources and 17 products; all are enabled but `auto_fetch=false`. No operational point-in-time observation DB or source-state DB exists at the configured source-registry paths. Existing market, calendar, and news databases are separate stores and are not migrated or modified by this phase. Thus this phase connects and audits the shared read contract but does not claim populated macro/intermarket/positioning history. External data acquisition/activation remains a separate explicitly approved step.

## Next strategic step

Populate the approved source products through controlled, provenance-complete ingestion only after explicit source acquisition approval; then measure historical coverage by timestamp and domain before deterministic multi-domain scenario replay and out-of-sample evaluation.

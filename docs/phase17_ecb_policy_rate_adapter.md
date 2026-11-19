# Phase 17 — ECB Policy-Rate Adapter and End-to-End Persistence

## North Star capability advanced

Gate 1 — canonical multi-domain data foundation. This adds a first concrete EUR (EUR-side) official central-bank policy dataset to the shared data plane. It supports the future macro/fundamental and cross-domain EURUSD intelligence specialists; it is not a technical-analysis or Price Action feature.

## Repository gap

The source registry already declared three official ECB policy-rate products, and Phases 15–16 provided the append-only point-in-time store and controlled adapter-ingestion boundary. The repository did not yet contain a normalizer for the ECB products, so the declared source could not flow through the shared pipeline.

## Deliverable

`source_registry/adapters/ecb.py` adds `ECBPolicyRateAdapter`, bound to exactly one registered product:
- `ECB_DEPOSIT_FACILITY_RATE`
- `ECB_MAIN_REFINANCING_RATE`
- `ECB_MARGINAL_LENDING_RATE`

It accepts extracted source records through an injected provider, validates date/rate/publication fields, uses Decimal values, preserves effective and publication timestamps separately, rejects duplicates/conflicts, and returns chronologically ordered typed observations.

## End-to-end integration

A deterministic integration test loads the actual validated registry, injects the ECB adapter into Phase 16's `SourceObservationIngestion`, stamps retrieval time, persists through Phase 15's `PointInTimeObservationStore`, and verifies the point-in-time row.

## Acceptance criteria

- All three registered ECB policy-rate product IDs are supported, each by a product-bound adapter instance.
- Wrong source/product, malformed records, invalid decimal rates, naive publication timestamps, duplicate dates, and conflicting values fail closed.
- Effective date, publication time, and retrieval time remain distinct.
- Empty full-history results are errors; empty incremental results are valid.
- Adapter tests and end-to-end ingestion/store test pass, as does the full unittest regression suite, on the exact PR head SHA.

## Explicit non-goals and safety

- No HTTP client, HTML scraper, browser automation, scheduler, retry worker, or automatic source activation.
- No fabricated historical records and no claim that the provider has already been connected to a live official feed. The caller must supply extracted records.
- No modifications to the registry, source-state database, existing calendar/news/MT5 stores, or RAG/knowledge database.
- No interpretation of rate decisions, policy surprises, EURUSD direction, strategy, risk, BUY/SELL authority, or order execution.

# Phase 19 — Federal Reserve Target-Range Adapter and End-to-End Persistence

## North Star capability advanced

Gate 1 — canonical multi-domain data foundation, supporting Gate 2 macro/fundamental specialist coverage. This adds the USD-side official central-bank policy instrument alongside Phase 17's EUR-side ECB series. It is a data capability, not a Price Action or trading feature.

## Repository gap addressed

The validated source registry already declares `FED_FOMC_POLICY/FED_TARGET_RANGE`, and Phases 15–16 provide a point-in-time observation store and controlled ingestion boundary. The repository contained an initial Fed normalizer but lacked dedicated acceptance coverage and an end-to-end persistence test.

## Deliverable

`source_registry/adapters/fed.py` provides `FedAdapter`, bound to the registered FOMC target-range product. It accepts extracted official records through an injected provider and preserves lower and upper target bounds as `DecimalRange`. It never substitutes a midpoint or represents the target range as a single scalar rate.

This phase adds focused validation for source/product identity, required bounds, finite Decimal values, ordered range bounds, effective date, timezone-aware optional publication timestamp, optional source record identity, duplicate/conflicting effective dates, and empty full-history responses.

## End-to-end integration

A deterministic integration test loads the validated source registry, injects the Fed adapter into Phase 16 `SourceObservationIngestion`, stamps retrieval time, persists through Phase 15 `PointInTimeObservationStore`, and verifies the exact range and point-in-time timestamps.

Together with Phase 17, the shared data plane now has official EUR scalar policy-rate observations and the USD federal-funds target range. This is prerequisite data for a later point-in-time policy-differential/fundamental specialist; no differential or currency-strength inference is made here.

## Acceptance criteria

- The registered `FED_TARGET_RANGE` product is supported.
- The target range is preserved exactly as Decimal low/high bounds.
- Invalid, reversed, duplicate, conflicting or malformed records fail closed.
- Publication, effective and retrieval timestamps remain distinct.
- End-to-end registry → adapter → ingestion → SQLite point-in-time persistence passes.
- Focused Fed adapter/integration tests and the full regression suite pass on the exact PR head SHA.

## Explicit non-goals and safety

- No HTTP client, HTML scraper, browser automation, scheduler, retries, or automatic source activation.
- No fabricated historical records or claim that the provider is connected to a live official feed.
- No midpoint conversion, policy-rate differential, policy surprise, yield-curve interpretation, macro conclusion, EURUSD directional bias, signal, strategy, risk change, BUY/SELL, MT5 order placement, or execution.
- No mutation of registry operational state, existing source databases, or RAG/knowledge databases.

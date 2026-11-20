# Phase 38 ? Unified Historical Data Plane

## Objective

Provide one deterministic, domain-aware, point-in-time historical snapshot for EURUSD research, with consistent evidence provenance and a quality-gated analytics projection. The platform remains multi-domain: spot FX, monetary policy, macro fundamentals, intermarket and positioning/sentiment are not collapsed into a price-action-only view.

## Implemented

- `PointInTimeDataPlane.read_unified_as_of(as_of_utc)` builds a single strict system-knowledge snapshot across all enabled Registry products.
- A single timezone-aware cutoff is applied to effective, publication and retrieval timestamps through the existing strict observation-store APIs. The public-availability reconstruction mode remains separate and is never implicitly substituted.
- The result preserves the complete strict-read evidence in `evidence_domains` and provides a separate `analytics_domains` projection.
- Phase 37G quality assessment is applied per product. Products failing unit, timestamp, numeric, freshness or availability checks are quarantined from the analytics projection; source evidence is not deleted, rewritten, repaired or imputed.
- Per-product revision summaries are carried with the quality report. Append-only versions and as-of semantics are preserved.
- Spot FX candles are joined from the separate market archive through a read-only interface. Only closed, versioned candles with strict observed/as-of cutoffs, UTC bar-time provenance, known BID/LAST price basis and valid OHLC are eligible. Legacy candle rows without the Phase37E version ledger are reported but never promoted.
- A deterministic SHA-256 snapshot identity binds the cutoff, Registry contract, observation identities/versions/payloads/timestamps and available spot candle version evidence.
- The read path is read-only, makes no network calls, and does not create a missing observation database.

## Explicit limitations

- This phase does not assert full historical coverage. Current operational observations remain sparse; empty products are blocked from analytics eligibility. The live market archive is still schema v3 and therefore its 1,047 legacy candles are not PIT-promotable until a controlled v4 migration/ingestion path is scheduled.
- No normalized canonical cross-domain feature table or resampling/interpolation is introduced. Original product units and frequencies remain intact; downstream transforms must be explicit and versioned.
- The quality gate is exposed at the unified data-plane boundary, but existing live Fusion/decision paths are not rewired in this phase.
- Reconstructed public-availability replay remains a distinct mode requiring per-observation attestation. Strict system-knowledge mode is the default.
- No forecast/scenario evaluation or trading-performance claim is made.

## Validation

Tests cover single-cutoff strict reads, quality-gated quarantine with preserved evidence, future publication/retrieval exclusion, revision history and deltas, deterministic registry-bound snapshot hashes, timezone-aware cutoff enforcement, missing-store behavior and schema-compliant numeric ranges. Acceptance: 44 focused regression tests and the full 658-test suite passed; compileall, registry validation, SQLite integrity and `git diff --check` passed. A read-only operational snapshot at 2026-11-20 02:00 UTC found 153 observations across the three CFTC positioning products; all three passed the current quality gate, while 20 other registered products had no PIT-eligible observations.

## Operational boundaries

No external fetch, provider activation, credential access, production DB migration, monitor restart, live order, risk-setting, Vision or RAG mutation. No commit or merge unless separately approved by the repository acceptance policy.

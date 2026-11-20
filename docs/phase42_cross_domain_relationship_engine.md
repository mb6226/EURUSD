# Phase 42 ? Cross-Domain Relationship Engine

## Objective
Build a strict point-in-time descriptive relationship layer across EURUSD market domains. This complements (rather than replaces) the existing live Intermarket Intelligence specialist. The new engine consumes the Phase 38 unified historical data plane and never fetches data or changes source records.

## Implementation
- Added `eurusd_ai_monitor/engines/cross_domain_relationship_engine.py` (`cross-domain-relationships-v1`).
- Accepts only `STRICT_SYSTEM_KNOWLEDGE` snapshots with a snapshot SHA-256.
- Consumes only products marked `ELIGIBLE` in `analytics_domains`; quarantined, stale, missing, malformed, future-dated, and unsupported-unit series are excluded with explicit reason codes.
- Requires timezone-aware effective, publication, and retrieval timestamps; enforces publication/retrieval/as-of cutoffs and source/product identity.
- Computes unit-aware changes: percent changes for price/index measures, basis-point changes for annualized yields, and percentage-point changes for labor/positioning percentages.
- Aligns changes only on exact common UTC timestamps, compares only distinct domains, and uses bounded Pearson correlation after a configurable minimum sample threshold.
- Exposes sample window, aligned count, measure units, change method, evidence hashes, and descriptive association strength.
- No forward-fill, interpolation, synthetic timestamps, causal claims, forecasting, directional vote, probability, trade signal, or execution authority.

## Existing specialist boundary
`IntermarketIntelligenceEngine` remains intact for its existing EURUSD-vs-driver analysis. Phase 42 is a broader PIT cross-domain layer over all quality-eligible products. No Fusion or central-scenario rewiring is performed in this phase.

## Production evidence
The current strict unified snapshot contains three quality-eligible products, all three from the CFTC EURO FX positioning domain. The spot archive remains schema v3 with legacy candles lacking eligible point-in-time provenance; other macro, policy, and intermarket products are not quality-eligible. Consequently there are zero distinct-domain candidate pairs and the production result is correctly `INSUFFICIENT_EVIDENCE`. This is not evidence that cross-domain relationships do not exist; it is a statement that the current eligible archive cannot establish them.

## Validation
Focused tests: 11 passed. Full repository suite: 704 passed. `compileall` and `git diff --check` passed. Production snapshot and SQLite integrity were checked read-only; all source registry auto-fetch flags remain false. Full acceptance details are in `reports/phase42_cross_domain_relationship_engine_report.json`.

## Safety
No network requests, provider activation, registry changes, DB writes/migrations, monitor restart, Fusion wiring, live orders, risk-setting changes, or RAG mutation. No commit or merge.

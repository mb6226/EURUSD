# Phase 21 — Cross-Atlantic Macro Fundamentals

## North Star capability

Gate 2 — Macro/Fundamental Intelligence, built on the Phase 15–16 point-in-time observation store and controlled source-ingestion path. This phase broadens fundamental coverage beyond policy rates; it is not a Price Action or trading-strategy feature.

## Repository gap addressed

Before this phase, the source registry contained ECB and Federal Reserve policy-rate products only. `fundamental_engine.py` remained a placeholder. The repository had no normalized official monthly inflation/unemployment series or deterministic cross-Atlantic macro assessment.

## Deliverables

### Official monthly series contracts

The registry now includes two official primary publishers, with all products enabled for explicit manual ingestion and `auto_fetch=false`:

- `US_BLS_MACRO`
  - `US_CPI_ALL_ITEMS_INDEX` — CPI all-items index, unit `index_1982_84_100`.
  - `US_UNEMPLOYMENT_RATE` — civilian unemployment rate, unit `percent_of_labor_force`.
- `EUROSTAT_MACRO`
  - `EA_HICP_ALL_ITEMS_INDEX` — euro-area HICP all-items index, unit `index_2015_100` (Eurostat `prc_hicp_midx`, all items `CP00`, index unit `I15`, euro-area aggregate).
  - `EA_UNEMPLOYMENT_RATE` — euro-area harmonised unemployment rate, unit `percent_of_labor_force` (Eurostat `une_rt_m`, total sex, ages 15–74, seasonally adjusted, euro-area aggregate).

BLS provider extraction should bind the CPI product to the unadjusted all-items CPI-U series `CUUR0000SA0` and the unemployment product to seasonally adjusted civilian unemployment series `LNS14000000`. Provider extraction must preserve the exact reference month and the actual official release timestamp; the adapter does not infer release times from a generic calendar rule.

`OfficialMacroSeriesAdapter` normalizes provider-extracted records. The transport/parser is injected; the adapter does not make HTTP requests or scrape either provider. Each record must include a `YYYY-MM` reference period, a finite decimal value, and a timezone-aware actual publication timestamp. The effective timestamp is normalized to the first day of the reference month at 00:00 UTC. The canonical source-record identity is always product plus reference month, even if a provider's own row identifier changes between vintages; this lets Phase 15 append revisions as new versions.

The adapter accepts only the four declared source/product pairs, rejects duplicate months, malformed periods, invalid numbers, missing/naive publication timestamps, and publication timestamps preceding the reference month. Incremental empty responses are allowed; empty full-history responses fail closed.

### Cross-Atlantic macro specialist

`MacroFundamentalsEngine` consumes as-of observations from the canonical store and produces two independent dimensions:

1. **Inflation:** year-over-year percentage change in US CPI and euro-area HICP for the latest common reference month with exact 12-month baselines; it also reports the US-minus-euro-area difference in percentage points.
2. **Unemployment:** US-minus-euro-area unemployment-rate difference for the latest common reference month.

The engine selects the latest revision known at the requested cutoff, excludes future-effective, future-published, and future-retrieved observations, requires current observations to satisfy the configured freshness limit, and never interpolates a missing month. Overall status is AVAILABLE, PARTIAL, or UNAVAILABLE; individual dimensions can be AVAILABLE, STALE, or UNAVAILABLE.

### Point-in-time ingestion hardening

The shared `SourceObservationIngestion` boundary now rejects any observation whose publication timestamp is later than its retrieval timestamp. Without this invariant, a future-published value accidentally present in a provider response could become visible at a later as-of cutoff despite having been retrieved before release. A regression test protects this look-ahead boundary.

## Integration path

Validated registry → explicitly injected BLS/Eurostat extracted-record providers → `OfficialMacroSeriesAdapter` → `SourceObservationIngestion` → append-only Phase 15 SQLite store → strict `get_as_of` reads → `MacroFundamentalsEngine`.

The end-to-end integration test exercises all four products using synthetic, explicitly timestamped records and a temporary database. It proves the contract and data path; it does not prove live provider connectivity or validate a real historical backfill.

## Interpretation limits

- US CPI and euro-area HICP are distinct statistical measures and baskets. Their difference is a qualified cross-region comparison, not a perfectly harmonized inflation measure.
- US civilian unemployment and Eurostat's harmonised euro-area unemployment use different statistical definitions. The gap is contextual, not a like-for-like labor-market score.
- No market consensus, analyst forecast, macro surprise, GDP, wage, PMI, policy-path expectation, or real-time release parser is included.
- No directional EURUSD forecast or probability is produced. A higher inflation or unemployment reading is not mechanically translated into a currency vote.
- Publication timestamps must come from the source's actual release metadata or another verified publication record. Retrieval time must never be substituted for publication time.

## Acceptance criteria

- Registry validates with both official sources and all four monthly products.
- Adapter normalizes exact Decimal values, UTC reference-month timestamps, publication timestamps, and stable period identities.
- Invalid/duplicate records, missing publication timestamps, invalid values, and invalid source/product identities fail closed.
- Point-in-time store preserves revisions and provenance for all four series.
- As-of engine excludes future publication/retrieval/effective records and selects the latest revision known at cutoff.
- Inflation uses the latest common reference month and exact 12-month baseline; no interpolation or synthetic baseline.
- Unemployment uses the latest common month and enforces freshness.
- Partial/missing/stale evidence remains explicit.
- Focused macro adapter, engine, integration, ingestion, and full regression tests pass on the exact PR head SHA.

## Explicit non-goals and safety

- No automatic HTTP fetching, scraping, scheduler, provider activation, credentials, or historical backfill.
- No consensus or surprise values; no fabricated estimates.
- No GDP, wages, PMI, retail sales, industrial production, or policy-path analysis in this phase.
- No runtime main-loop wiring until real source providers, release metadata, and operational freshness are validated.
- No mutation of existing calendar/news/MT5/RAG/knowledge databases.
- No central directional vote, strategy change, BUY/SELL authority, risk change, or MT5 execution.

# Phase 37 — Controlled Multi-Domain Source Acquisition & Historical Ingestion

## North Star

Build the provenance-preserving acquisition boundary for the comprehensive EURUSD intelligence system. This is a data-plane and historical-evidence phase, not a trading strategy or an additional directional specialist.

## Implemented in this phase

### 1. Source-specific acquisition readiness plan

`source_registry/acquisition_plan.py` creates a deterministic plan from the validated source registry. It maps every registered source/product to an explicit acquisition mode, point-in-time readiness requirement, publication-time evidence requirement, and known historical limitation.

The plan covers all 9 registered sources and 17 products across monetary policy, macro fundamentals, intermarket, positioning/sentiment, and spot FX. Unknown sources fail closed as `BLOCKED_UNMAPPED_SOURCE`. It does not inspect credentials, make HTTP requests, enable auto-fetch, initialize a database, or mutate registry state.

### 2. Immutable raw-response archive

`source_registry/raw_archive.py` introduces `RawSnapshotArchive`, an explicit append-only SQLite archive for exact provider response bytes captured before normalization. Each snapshot stores:
- source/product identity and HTTPS source URL;
- local retrieval timestamp in UTC;
- HTTP status and content type;
- ETag / Last-Modified and response headers;
- request metadata;
- exact payload bytes, byte count, and SHA-256 digest.

The archive enforces enabled source/product allowlisting when created through `from_registry`, accepts successful HTTP 200 payloads only, rejects empty/oversized payloads, is idempotent for identical snapshots, appends later revisions as new snapshots, and blocks UPDATE/DELETE operations. URL query credentials and sensitive metadata/header values are redacted before persistence.

### 3. Existing normalized ingestion remains authoritative

Raw snapshots are not automatically converted into observations. The existing typed adapters and `SourceObservationIngestion` remain responsible for validation, publication-time checks, local retrieval-time stamping, and append-only normalized observation persistence. This separation preserves the original provider evidence and avoids manufacturing publication timestamps.

## Source readiness findings

| Source | Products | Acquisition mode | Point-in-time constraint |
|---|---:|---|---|
| Federal Reserve FOMC | 1 | Official HTML / statement snapshots | Effective date is not publication timestamp; capture original statement release time |
| ECB policy rates | 3 | Official decision release snapshots | Join effective rate to original ECB decision publication timestamp |
| BLS | 2 | Official API + release calendar | Preserve original release values and exact calendar/press-release time; latest API values alone can be revised |
| Eurostat | 2 | Official API snapshots | Latest-version API only; forward snapshots cannot reconstruct lost historical vintages |
| FRED | 3 | FRED / ALFRED API | API key required; ALFRED vintage dates provide date-level, not necessarily intraday, timing |
| ECB intermarket | 1 | ECB SDMX API | Resolve exact flow/key and verify revision/history semantics before ingestion |
| LBMA | 1 | Access / licensing review | No automated acquisition until licensing and data-access rights are confirmed |
| Broker spot | 1 | Local broker export | Preserve broker/server timezone, DST, symbol, bid/ask basis, timeframe and raw file hash |
| CFTC TFF | 3 | CFTC Public Reporting API + release schedule | Tuesday/report date differs from publication timestamp; holiday and announced cadence changes must be handled |

## Important official-source constraints verified

- Eurostat states that its APIs are free, datasets are updated twice daily, and the database exposes the latest dataset version without historical versioning. This source can support forward snapshot capture, but a current response cannot recreate a past point-in-time vintage.
- FRED API documentation requires an API key. ALFRED exposes real-time periods and series vintage dates, but those are date-level knowledge boundaries and should not be silently promoted to exact intraday release timestamps.
- BLS publishes release schedules with reference month, release date and release time; these should be joined to the corresponding release record, not guessed from the observation period.
- CFTC's standard COT schedule specifies 3:30 p.m. Eastern and holiday delays. A separate October 2026 announcement described a planned move toward twice-weekly publication by the end of 2026; the adapter's Tuesday-only assumption must therefore be revalidated against the active TFF dataset and release calendar before live ingestion.
- ECB provides an official SDMX REST service. Exact flow, key, and revision behavior still need product-level validation.

## Safety and current execution result

- No external network request was made by this phase's local implementation.
- No credentials were read or stored.
- No source `auto_fetch` flag was changed.
- No operational observation or raw-archive database was created in the live repository.
- No existing market, calendar, news, RAG, or source-state database was modified.
- No monitor restart or forced refresh was performed.
- Vision remains disabled; alert-only mode and execution/risk settings are unchanged.

The raw archive is created only when a caller explicitly instantiates it with a path and validated registry. This phase adds the capability and readiness contract; it does not claim that historical macro/intermarket/positioning observations have already been downloaded or ingested.

## Acceptance

- Plan covers the canonical registry without network or database side effects.
- Unknown sources fail closed.
- Raw payload bytes are preserved and hash-verifiable.
- Identical snapshots are idempotent; later payload revisions append.
- Raw archive rejects disabled/unregistered products, non-HTTPS URLs, non-200 responses, empty/oversized payloads, and naive retrieval timestamps.
- Secret-like values are redacted from stored URL query strings, headers and request metadata.
- UPDATE/DELETE against raw snapshots is blocked.
- Focused tests, full regression, compile checks and Git diff validation pass.

## Official documentation references

- BLS Public Data API v2: https://www.bls.gov/developers/api_signature_v2.htm
- BLS CPI release schedule: https://www.bls.gov/schedule/news_release/cpi.htm
- Eurostat API overview and versioning: https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction
- FRED API / API key: https://fred.stlouisfed.org/docs/api/fred/
- FRED real-time periods: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
- FRED vintage dates: https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html
- ECB SDMX API: https://data.ecb.europa.eu/help/api/overview
- CFTC COT release schedule: https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm
- CFTC October 2026 publication-cadence announcement: https://www.cftc.gov/PressRoom/PressReleases/9316-26

## Next

Phase 37B is recorded in phase37b_official_provider_adapters_and_first_ingestion.md. The next subphase is to implement an explicit, evidence-attested public-source-availability replay path for verified historical backfills, while preserving the existing strict system-knowledge as-of mode. Then close BLS release-archive access and continue FRED/ALFRED and ECB SDMX mappings. Latest-only or date-grained sources must remain explicitly labeled so they cannot silently contaminate intraday point-in-time replay.


## Phase 37B update — Official provider adapters and first ingestion

Phase 37B has completed a first controlled acquisition vertical slice. The CFTC TFF Futures-Only provider acquires the CME EURO FX contract, archives raw dataset/calendar/special-announcement evidence, and joins all 51 report dates to official publication timestamps. Three positioning products have been normalized and persisted (153 observations). The BLS CPI provider and raw API archive are implemented, but BLS schedule/archive HTTP requests returned 403 locally; no BLS observations were persisted.

The new local databases are source_registry/operational/raw_snapshots.sqlite and source_registry/operational/observations.sqlite. Historical source publication time and local retrieval time remain distinct. Because the current strict as-of store requires both to precede the replay cutoff, a separate attested public-source-availability replay mode is a prerequisite for historical replay of backfilled observations. See phase37b_official_provider_adapters_and_first_ingestion.md.

The next subphase should close the public-availability attestation/replay boundary, then continue BLS release-archive access and the FRED/ECB provider mappings. Do not activate auto-fetch or alter live execution boundaries.

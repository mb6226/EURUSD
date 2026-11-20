# Phase 37D ? Official Provider Expansion

## Objective

Expand official provider coverage for macro and intermarket research while preserving raw provenance, revision metadata, and point-in-time boundaries. This phase adds provider capabilities only; it does not activate scheduled fetching or backfill production observations.

## Implemented

### BLS CPI
- Updated the CPI provider to the official BLS Public Data API v2 endpoint and canonical `www.bls.gov` calendar/archive hosts instead of the legacy mirror.
- Existing CPI acceptance rule remains strict: current API value must match the original release archive value, and the original embargo timestamp must match the official release calendar.
- The adapter remains CPI-U unadjusted all-items (`CUUR0000SA0`). No employment/unemployment series was promoted because an equivalent original-release value and publication-time parser has not yet been validated.

### FRED / ALFRED
- Added `source_registry/providers/fred.py` (`FREDALFREDVintageProvider`).
- Explicitly supplied 32-character API key; no environment-variable lookup or secret discovery.
- Requests `output_type=2` and preserves `realtime_start` / `realtime_end` vintage intervals for registered DGS10, DTWEXBGS and SP500 products.
- Raw response is archived with a safe URL (API key redacted) and request metadata.
- Vintage intervals are date-grained. Output is explicitly `pit_observation_ready=false`; no intraday publication timestamp is fabricated and no normalized observation is persisted.

### ECB SDMX
- Added `source_registry/providers/ecb_sdmx.py` (`ECBSdmxHistoricalProvider`).
- Requires caller-supplied exact flow reference and series key; does not guess a series key.
- Requests `includeHistory=true`, archives the exact CSV response, and preserves SDMX attributes and duplicate-period revision order.
- ECB observation period and revision history do not prove exact public release time. Output is explicitly not PIT-ready and is not persisted as normalized observations.

## Explicitly not performed

- No live provider requests or historical ingestion in Phase37D.
- No FRED key read, searched, or requested.
- No ECB flow/key discovery request.
- No registry changes, source enablement, `auto_fetch` changes, scheduler activation, or production DB writes.
- No BLS unemployment parser or LBMA acquisition: the former needs original release validation; the latter still requires licensing review.
- No monitor restart, live order execution, risk-setting changes, or RAG mutation.

## Evidence and limitations

- FRED/ALFRED exposes real-time periods and vintage dates; these provide date-level historical knowledge boundaries, not automatically an exact intraday release timestamp.
- ECB SDMX supports `includeHistory=true` to retrieve prior versions; raw history is preserved but publication-time semantics remain a separate proof requirement.
- BLS CPI remains the only BLS series with an implemented original-release value comparison and embargo-time parser in this provider set.

## Acceptance

Focused provider tests validate vintage preservation, key redaction, explicit ECB metadata configuration, revision attribute retention, and no false PIT promotion. Full repository tests, compileall, diff check, DB integrity, registry auto-fetch flags, monitor status and market CSV freshness are recorded in the Phase 37D completion report.

## Phase completion verification

- Focused tests: 36 passed.
- Full repository suite: 628 passed.
- `compileall`: passed; `git diff --check`: passed.
- Registry schema/semantic validation passed; 9 registered sources and all product auto-fetch flags remain false.
- Existing observation and raw-snapshot SQLite integrity checks passed.
- No provider network calls and no production observations added.
- Report: `reports/phase37d_provider_expansion_report.json`.

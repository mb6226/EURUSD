# Phase 35 — Official Calendar Feed Identity and Timezone Hardening

## North Star capability advanced
Improve the reliability and point-in-time integrity of official macro-event context consumed by the central multi-domain EURUSD scenario engine. Calendar events remain contextual risk evidence; they are not directional votes or trade instructions.

## Observed repository/runtime gap
The existing calendar database recorded three source failures during the 2026-11-19 refresh:
- BLS iCalendar parsing rejected the legacy TZID label `US-Eastern`, despite the event timezone being unambiguous.
- ECB event identity used only year/month/meeting kind. Distinct same-month meeting dates could collide.
- FOMC event identity used only year/month. Distinct same-month event dates could collide.

The previous failures are visible in `macro_source_state`; existing successfully stored BEA events were retained.

## Changes
- Added a narrowly scoped `US-Eastern` to `America/New_York` timezone conversion alias. The original TZID remains preserved in event metadata; unknown timezones still fail closed.
- Changed ECB event IDs to include the exact scheduled date and meeting kind.
- Changed FOMC event IDs to include the exact scheduled decision date.
- Added regression tests for legacy TZID conversion and unique same-month ECB/FOMC event identities.

## Validation
- Calendar engine tests: 17 passed.
- Full unittest suite: 582 passed.
- `compileall`: passed.
- `git diff --check`: passed.

## Runtime and data boundaries
- No calendar/news refresh was forced as part of this phase; no new external fetch was initiated.
- The already-running monitor continues to collect M1/M5 CSV data with Vision disabled. Its in-memory calendar parser remains the pre-change version until a controlled restart.
- Existing calendar/news databases were not edited or backfilled.
- The point-in-time observation database is still absent. Macro, policy-rate, intermarket and positioning specialists therefore remain explicitly unavailable; no observations were fabricated.
- Current M1/M5 CSVs are short rolling monitoring exports, not a one-year historical archive. Historical scenario scoring remains blocked until adequate historical candles and point-in-time multi-domain observations are available.
- Alert-only mode and all execution/risk boundaries remain unchanged.

## Next strategic work
Continue Gate 1 and Gate 2 data-plane readiness: verify source adapters and source/product coverage, establish a controlled point-in-time ingestion path, and obtain an approved historical EURUSD dataset. Then resume point-in-time reconstruction and central-scenario out-of-sample evaluation. Do not activate additional external fetching without separate approval.

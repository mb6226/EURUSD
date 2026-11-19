# Phase 4 — Macro & Economic Calendar Intelligence

## Scope and authority

Phase 4 adds a deterministic, provenance-preserving event calendar for EURUSD macro context. It ingests official publication schedules from the U.S. Bureau of Labor Statistics (BLS), the U.S. Bureau of Economic Analysis (BEA), and the European Central Bank (ECB).

The calendar is context-only:
- `trade_authority: NONE` and `decision_authority: CONTEXT_ONLY` are explicit in the monitor payload.
- It does not generate BUY/SELL, change the legacy evaluator, or place/manage orders.
- It does not change the MarketDataStore schema, Price Action lifecycle tables, source-registry operational database, or RAG/knowledge databases.
- Calendar data is stored in its own SQLite file: `eurusd_ai_monitor/data/calendar/macro_calendar.sqlite`.

## Official sources

| Source | Format | Coverage | Time handling |
|---|---|---|---|
| BLS | Official iCalendar feed | U.S. labor, CPI, PPI and other BLS releases | `TZID` is honored; floating local times use `America/New_York` |
| BEA | Official machine-readable JSON | GDP, Personal Income and Outlays, trade and other BEA releases | Offset-aware timestamps are converted to UTC; naive timestamps are rejected |
| ECB | Official Governing Council calendar | EUR Governing Council and monetary-policy meeting dates | Date-only events remain date-only; the engine does not invent a time |

Canonical source URLs are held in `calendar_sources.json`. Refresh cadence and stale thresholds are source-specific and configurable. The built-in transport uses Python's standard library, HTTPS, a bounded response size and a finite timeout. No paid API or additional runtime dependency is required.

## Event contract

Each immutable `MacroEvent` includes:
- stable event identity derived from source ID and source event ID;
- source name, canonical/event URL and source event identifier;
- title, description, category and EUR/USD currency relevance;
- deterministic impact tier (`HIGH` / `MEDIUM` / `LOW` / `UNKNOWN`) plus the exact rule that matched;
- source-local scheduled date and optional UTC instant, preserving source timezone;
- source status (`SCHEDULED` / `TENTATIVE` / `CANCELLED` / `UNKNOWN`);
- optional actual, forecast, previous and result unit fields;
- source update and retrieval timestamps.

The current official schedule feeds do not provide consensus forecasts or all released actual/previous values. Those fields therefore remain `null` until a separately validated result-data source is implemented. A past scheduled time is not treated as proof that an actual value has been published.

Impact tiers are transparent title-keyword rules in configuration, not an AI opinion or a claim that the market must react. Unmatched titles are `UNKNOWN`, never silently promoted to `LOW`.

## Persistence, revisions and failure policy

- `macro_events` stores the current canonical event representation.
- `macro_event_revisions` stores append-only before/after payloads when a source changes an event.
- Repeated unchanged fetches update last-seen metadata but do not create semantic revisions.
- Stable IDs deduplicate repeated records; conflicting duplicates in one response fail validation.
- Events missing from a later feed are not deleted or silently cancelled. Only an explicit source cancellation changes event status.
- `macro_source_state` records last attempt, last success, event count and error details.
- Failed refreshes preserve previously accepted events and the last successful timestamp. The published context marks the source `FAILED` or `STALE`.
- The event database is separate from market and RAG storage.

## Runtime integration

The monitor checks source refresh intervals and builds a configurable upcoming-event window (default 72 hours). The `macro_calendar` object is included in the alert JSON alongside market context and Price Action lifecycle output.

The context reports:
- source health and stale source IDs;
- upcoming events filtered to EUR/USD;
- event count and high-impact count;
- minutes to release only when an exact UTC release instant is supplied;
- explicit context-only/no-trade-authority markers.

Calendar refresh failures are isolated and do not crash the market monitor or silently turn missing calendar information into neutral evidence. Phase 4 does not yet use event proximity to veto or authorize a trade; any such risk policy belongs in the later reviewed decision-fusion phase.

## Validation

Tests use deterministic fixtures and injected fetchers. They do not make network requests. Coverage includes:
- event validation and serialization;
- BLS-style iCalendar timezone, all-day, status and escaping behavior;
- BEA JSON parsing, offset validation and duplicate normalization;
- ECB date-only calendar parsing;
- stable persistence, idempotent refresh and append-only revisions;
- source failure/staleness while preserving last accepted events;
- EUR/USD filtering, impact transparency and context authority markers.

No live MT5 run or live official-source fetch is claimed by the unit tests. Live source availability and page/feed structure should be checked during the user's local acceptance run.

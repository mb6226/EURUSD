# Phase 41 — Session & Time Intelligence

## Objective

Add a deterministic temporal context layer to the Phase 38 strict unified point-in-time data plane. The engine identifies reference financial-centre session windows, local clock values, UTC offsets, DST state, London/New York overlap, and descriptive session coverage when eligible historical EURUSD candles exist.

## Implementation

- New `SessionTimeIntelligenceEngine` accepts only `STRICT_SYSTEM_KNOWLEDGE` snapshots.
- IANA `ZoneInfo` conversions cover Sydney, Tokyo, London, and New York. UTC instants are converted into each local zone, so DST transitions are not approximated with fixed offsets.
- Reference windows are explicit local clock windows: Sydney 08:00–17:00, Tokyo 09:00–18:00, London 08:00–17:00, and New York 08:00–17:00.
- The engine reports active reference windows and the London/New York overlap without treating these windows as exchange hours, broker availability, or a trading edge.
- M1/M5 session coverage is counted only for a single quality-eligible EURUSD stream with strict candle open/close, observed-at, and as-of timestamps. Invalid/future rows block that timeframe.
- Coverage counts are descriptive only. No volatility, liquidity, return, win-rate, or profitability conclusions are derived from session counts.
- Optional calendar event context requires exact timezone-aware scheduled timestamps plus publication and retrieval timestamps at or before the snapshot cutoff. Cancelled/unverified events are excluded; date-only events remain date-only.
- Weekend output is only a UTC calendar-day flag. Broker-specific weekly FX open/close, holidays, and DST exceptions remain unknown until supported by verified broker calendars.

## Relationship to the overall system

Phase 41 supplies common temporal annotations for later cross-domain relationship analysis (Phase 42), central scenario intelligence (Phase 43), and multi-horizon forecasting (Phase 44). It does not create a standalone session strategy or change the existing assessment-only session risk gate.

## Current production limitation

The current production spot archive is still schema v3 without the Phase 37E candle version ledger. Legacy M1/M5 candles are not promoted into strict PIT analytics. Therefore session-time context can be computed at the snapshot cutoff, but historical session coverage remains unavailable and no intraday session edge is claimed.

The existing macro calendar engine is a separate live context store and is not silently treated as strict historical PIT calendar evidence. Calendar event integration remains an explicit input until a point-in-time calendar evidence path is established.

## Safety

- No external data acquisition or provider activation.
- No database migration or mutation.
- No monitor restart.
- No Fusion or live runtime wiring.
- No risk-setting changes, RAG mutation, or order execution.

## Tests

Offline tests cover standard/daylight offsets, session overlap, Sydney/Tokyo labels, weekend limitation, missing historical spot data, eligible session coverage, invalid/future candles, strict replay mode, publication/retrieval cutoffs, date-only events, and cancelled events.


## Acceptance results

- Focused session/time plus existing session-risk regression tests: 26 passed.
- Full repository suite: 693 tests passed.
- `compileall` and `git diff --check` passed.
- Read-only production snapshot: 9 registered sources, 23 enabled products, 3 quality-eligible observation products; spot archive schema v3, 1,071 legacy candles, 0 versioned candles, 2 registered EURUSD streams and 0 analytics-eligible streams at the final production snapshot.
- Production session-time result: `INSUFFICIENT_EVIDENCE` for historical session coverage, as required by the provenance gate.
- SQLite integrity checks passed for observation, raw-snapshot and market databases. Registry source-level `auto_fetch` remains false.

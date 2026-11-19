# Phase 9 — Setup Observation & Outcome Intelligence

## Purpose

Phase 9 adds a durable, research-only observation record for Phase 7 confirmed setups that pass the Phase 8 session/risk eligibility gate. It measures price excursions; it does not model a filled order or a trade.

## Contract

- Identity is `lifecycle_id:retest_candle_id`, matching the Phase 8 reservation key.
- The reference price is the close of the confirmed M1 retest candle.
- Observation begins with the first closed M1 candle whose open time is at or after the retest close timestamp. The retest candle itself is excluded.
- Only closed M1 candles from the same broker and symbol are accepted.
- London ends at 12:00 Europe/London; New York ends at 12:00 America/New_York. IANA zones handle DST.
- An observation starts only when Phase 8 returns `RESEARCH_ELIGIBLE`. A blocked or outside-session setup does not start an observation.
- An active observation continues after the session gate closes and completes at that session's local 12:00 boundary.
- UP favorable excursion uses candle high and adverse excursion uses candle low. DOWN uses candle low for favorable and candle high for adverse. Excursions are measured in pips from the retest close and floored at zero.
- MFE/MAE timestamps identify the closing time of the M1 candle that established the extreme. Intrabar order is unknown and is not inferred.
- Processed candle OHLC evidence is immutable. A changed OHLC for an already processed candle marks the observation `DATA_CONFLICT`; it is not silently recalculated.
- Repeated polling is idempotent. Observation rows and per-candle evidence are stored in a separate `setup_observations.sqlite3` database.

## Statuses

- `WAITING_FOR_SESSION_ELIGIBILITY`: no observation has started.
- `ACTIVE`: observing closed M1 candles.
- `COMPLETED`: session boundary reached.
- `DATA_CONFLICT`: previously processed candle or immutable setup reference changed.

## Explicit non-goals

No entry price, pending order, position, SL/TP hit, realized/unrealized P/L, BUY/SELL instruction, MT5 order call, strategy mutation, or automatic learning is produced. `MFE` and `MAE` are price excursions from a reference close, not trade returns. The Phase 8 risk reservation remains a research eligibility reservation only.

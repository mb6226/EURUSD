# Phase 45 — Point-in-Time Historical Forecast Replay

## Purpose

Phase 45 replays the Phase 44 baseline forecast at historical system-knowledge cutoffs. It is the bridge between a forecast implementation and a measurable historical evaluation; it does not itself establish predictive skill.

## Replay contract

- The market archive must be opened read-only and must expose the immutable Phase 37E candle version ledger (schema v4).
- Only EURUSD M5 candle versions with verified MT5 source identity, BID/LAST price basis, UTC bar-time basis, closed-bar state, valid OHLC and a consistent price basis across the forecast window are eligible.
- A forecast cutoff is the first system-knowledge timestamp at which a closed candle version is actually observed and its as_of_utc is known. The cutoff is never backdated to the candle's market timestamp.
- For each cutoff, the replay incrementally exposes only candle versions with observed_at_utc <= cutoff, as_of_utc <= cutoff, and candle close no later than cutoff. Later corrections cannot rewrite earlier forecast inputs.
- Phase 44 is called unchanged for each cutoff. Each available forecast is retained separately for 15-minute, 1-hour and 4-hour horizons.
- A target outcome is resolved only from the first verified closed target-candle version observed after its close and no later than the explicit evaluation cutoff. Later revisions do not replace that first outcome version.
- Forecast snapshot hashes bind the cutoff and exact visible candle version IDs/value hashes. Replay identity binds the source-history hash and all replay parameters.
- Historical central-scenario reports are not reconstructed or fabricated. They may be joined only if independently archived with matching historical cutoffs in a future phase.

## Persistence

A separate research database, eurusd_ai_monitor/data/research/forecast_replay.sqlite, stores completed replay runs and per-horizon forecast/outcome records. It is separate from the market archive and has append-only update/delete guards. Repeated persistence of the same replay ID is idempotent. The command-line runner uses a read-only connection to the market archive and writes to the research ledger only when a completed replay exists.

## Production preflight (2026-11-20)

The current market archive is schema v3 with 1,132 legacy candles and no candle_versions or candle_ingestion_runs tables. Therefore Phase 45 correctly returns BLOCKED / CANDLE_VERSION_LEDGER_UNAVAILABLE. The old candles are not promoted, retroactively timestamped or treated as point-in-time evidence. No production archive migration, backfill, MT5 request, provider activation, monitor restart, strategy/risk change, live order, or RAG mutation was performed.

## Metrics and limitations

Per horizon, the replay reports forecast count, outcome availability, directional accuracy, mean absolute error and mean signed error. Probability metrics remain unavailable because Phase 44 emits no calibrated probabilities. These are descriptive baseline metrics only, not profitability or trading-performance evidence.

## Next

Phase 46 — Scenario Evaluation Framework should evaluate archived central multi-domain scenarios and baseline forecasts with explicit horizon matching, outcome definitions, coverage accounting, benchmark comparisons and separation of in-sample from out-of-sample periods. Phase 47–49 then address forecast error analysis, uncertainty calibration and walk-forward validation.


## Phase51 operational recheck

The production market archive is now schema v4 after a verified backup-first migration. Newly observed M1/M5 versions are accumulating with actual system-knowledge timestamps. A bounded, non-persisted replay smoke test over the first v4 window generated 2 forecast cutoffs and 6 baseline forecast records from real MT5 versioned data; no target outcomes had matured. The official Phase45 report is now REPLAY_WINDOW_REQUIRED, not CANDLE_VERSION_LEDGER_UNAVAILABLE. A full replay must specify a valid window and wait for 15M/1H/4H target outcomes to mature.


## Downstream full-record access

The compact Phase45 report intentionally does not inline every forecast row. The append-only forecast replay ledger stores the full records, and ForecastReplayLedger.load_run(replay_id) now exposes a read-only, full-fidelity replay object for Phase47/48/49/50. The downstream runners use this exact replay ID and fail closed if full ledger records cannot be loaded; they never evaluate the small report preview as a complete sample.

# Phase 44 — Multi-Horizon Forecasting

## Purpose

Phase 44 adds a transparent multi-horizon baseline forecast over the Phase 38 unified historical data plane and Phase 43 central scenario output. It extends the existing scenario/replay architecture; it does not create a Price Action-only trading system or claim validated predictive skill.

## Forecast contract

- Input must be one STRICT_SYSTEM_KNOWLEDGE unified snapshot.
- Price input is limited to a quality-eligible, versioned, closed EURUSD M5 stream with verified source, BID/LAST price basis, UTC bar-time basis, contiguous candles and observed/as-of timestamps no later than the snapshot cutoff. The latest closed bar must be no more than 15 minutes old at the cutoff.
- Three separate horizons: 15 minutes (3 M5 bars), 1 hour (12 bars), and 4 hours (48 bars).
- Baseline expected movement = median of the latest 12 close-to-close M5 returns multiplied by horizon bars.
- Historical dispersion = sample standard deviation of bounded lookback returns, scaled by square root of horizon bars.
- One- and two-dispersion bands are descriptive only, not calibrated prediction intervals.
- Central scenario state, hypotheses, domain coverage and evidence dependency map are attached for comparison. They do not override or modify the independent baseline forecast.
- Missing, ambiguous, stale/unverified, non-contiguous, future/forming or reconstructed-public-availability inputs fail closed.

## Current production limitation

The production spot archive was last verified as legacy schema v3 with 1,049 unversioned candles and no provenance ledger. Those candles are not eligible for strict PIT forecasting. The production assessment must therefore return INSUFFICIENT_EVIDENCE for all horizons until a controlled v4 migration and new versioned candle ingestion provide verified lineage. Phase 44 does not perform that migration or ingestion.

The Phase 43 production data plane had three quality-eligible CFTC positioning products but no eligible EURUSD spot stream. CFTC positioning is retained as domain context and is never substituted for price returns.

## Validation and boundaries

- Outputs carry algorithm version, snapshot/registry hashes, candle version IDs, sample window, cutoff and method.
- Numeric probabilities and calibrated confidence remain null.
- No live monitor rewiring/restart, provider activation, network access, database migration/write, strategy/risk change, order placement, or RAG mutation.
- Forecast skill must be measured in Phase 45 point-in-time replay and Phases 46–49 out-of-sample evaluation, error analysis, calibration and walk-forward validation.
- No commit or merge is performed by this phase.

## Next

Phase 45 — Point-in-Time Historical Replay should capture timestamped Phase 44 forecasts and evaluate each horizon only against subsequent, strictly later closed candle versions. Preserve revision history and never relabel current forecasts as historical outputs.

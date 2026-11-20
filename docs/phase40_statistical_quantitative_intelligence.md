# Phase 40 — Statistical & Quantitative Intelligence

## Objective

Add a point-in-time quantitative research layer over the Phase 38 unified historical data plane. Preserve existing live MarketSnapshot-based descriptive specialist; do not mistake rolling/live snapshots for historical PIT evidence.

## Implementation

- New `PointInTimeQuantitativeStatisticsEngine` consumes only `STRICT_SYSTEM_KNOWLEDGE` unified snapshots.
- Accepts EURUSD M1/M5 streams only when the data plane marks them PASS and analytics-eligible.
- Independently validates closed-bar cutoff, observed/as-of timestamps, monotonic contiguous cadence, OHLC bounds, source identity, BID/LAST price basis, UTC bar basis, and immutable candle version IDs.
- Configurable bounded lookback and minimum sample thresholds.
- Per timeframe computes close-to-close pip return distribution (mean, median, sample standard deviation, min/max, nearest-rank quantiles, positive/negative/zero frequencies).
- Computes realized volatility, mean absolute return, upside/downside semideviation, empirical 95/99% historical VaR and expected shortfall, close-to-close maximum drawdown, true-range statistics, lag-1 return autocorrelation and sign persistence.
- M1 and M5 remain separate; no pooling or independence assumption.
- One eligible timeframe yields PARTIAL; no eligible timeframe yields INSUFFICIENT_EVIDENCE.
- Reports snapshot and registry hashes, stream and candle version provenance, and explicit interpretation limits.
- No forecasts, calibrated probabilities, strategy performance claims, trading signals, or execution authority.

## Relationship to existing engines

- Existing `QuantitativeMarketStatisticsEngine` remains a separate live `MarketSnapshot` descriptive specialist.
- Existing `StatisticalOutcomeEvaluator` remains a separate read-only MFE/MAE evaluator for completed historical observation records.
- Phase 40 adds a strict PIT spot-statistics path; it does not merge incomparable samples or silently upgrade older datasets.

## Current production state

Current spot archive remains schema v3 with no candle version ledger and is marked `PROVENANCE_UNAVAILABLE`. The 3 eligible CFTC positioning products are not price returns and are not substituted into this engine. Expected production output is `INSUFFICIENT_EVIDENCE`.

## Safety

No external data acquisition, provider activation, database migration, monitor restart, RAG mutation, Fusion rewiring, risk-setting change, or order execution.

## Acceptance

Offline regression tests cover descriptive metrics, empirical tail-risk summaries, missing streams, strict replay mode, future timestamps, history gaps, unverified price basis, and invalid configuration.

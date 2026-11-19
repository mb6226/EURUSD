# Phase 30 — Historical Dataset Integrity & Walk-Forward Validation

## North Star

Strengthen the central intelligence research loop: Phase 28 creates multi-domain scenarios; Phase 29 measures their later outcomes; Phase 30 checks whether the historical market archive is trustworthy enough and creates chronological, embargoed partitions for honest out-of-sample evaluation. This remains multi-domain market intelligence, not a specialist-specific or trading-strategy project.

## Implementation

### Read-only historical dataset audit

`HistoricalDatasetValidationEngine.audit` inspects the existing `MarketDataStore` for one broker, symbol, timeframe and explicit half-open UTC interval.

It reports:
- expected timeframe slots and observed closed candles;
- coverage ratio and missing candle ranges, including leading/trailing missing slots;
- duplicate/unaligned timestamp checks;
- revision watermark, scan completeness, revision-event count and distinct revised candles;
- existing OHLC integrity guarantees and their limitation (rejected ingestion attempts are not archived).

The audit is read-only. It does not repair, backfill, rewrite or migrate market data. If the revision scan reaches its configured limit, status degrades rather than claiming completeness.

Coverage is a wall-clock continuity diagnostic, not an exchange/session-aware completeness score. FX weekends, holidays, broker maintenance and provider outages are not distinguished automatically; inspect the requested window and interpret missing intervals accordingly.

### Chronological walk-forward partitioning

`walk_forward_split` creates ordered train, validation and test partitions from timestamped archived scenario reports. It never shuffles observations. A purge/embargo equal to the maximum configured forecast horizon is applied at train→validation and validation→test boundaries, removing reports whose forward outcome windows could overlap the next partition.

Fractions and minimum sample counts are explicit parameters. Reports with missing, malformed or timezone-naive timestamps are excluded and counted. The result exposes source report indices, time boundaries, sample counts and purged counts.

This is a single chronological holdout split, not rolling multi-fold walk-forward validation. The caller must ensure every evaluated horizon is no longer than `max_horizon_bars`, and must not tune model/threshold choices against the final test partition.

## Point-in-time and interpretation limits

- This phase audits current canonical candles and revision metadata; it does not reconstruct full first-seen candle values as-of every historical forecast.
- Phase 29 conservatively excludes candles with post-forecast revisions. Full as-of version reconstruction remains a future data-store capability.
- Scenario reports must have been archived at their original evaluation times; historical reports are never fabricated or backdated.
- Scenario archives and upstream macro/news/intermarket/positioning/specialist evidence require separate coverage and provenance audits before claiming complete multi-domain historical replay.
- No performance metric is valid unless the market archive audit, scenario archive coverage, and point-in-time source provenance are adequate for the selected interval.

## Acceptance and boundaries

- Deterministic tests for full/missing candle coverage, revision history, revision scan limits, timestamp alignment, chronological ordering, embargo purging, invalid timestamps and undersized partitions.
- Read-only operation against the existing store; no database writes.
- No provider fetching, backfill, archive mutation, model training, probability calibration, source reliability weights, strategy optimization, Fusion vote changes, risk changes, BUY/SELL enablement or order execution.
- Metrics remain scenario classification outcomes, not trading profitability or realized P/L.

## Remaining research gaps

1. Full as-of candle version reconstruction, rather than exclusion-only revision handling.
2. Scenario archive manifest and retention/coverage auditing.
3. Point-in-time provenance completeness for all specialist inputs, including macro, policy, intermarket, positioning, liquidity, news and sentiment.
4. Repeated rolling-origin walk-forward folds and regime-stratified reporting.
5. Calibration and uncertainty estimation only after adequate, representative out-of-sample samples exist.

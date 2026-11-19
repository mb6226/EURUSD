# Phase 12 — Regime-Conditioned Outcome Intelligence

## Purpose

Phase 12 adds a descriptive research layer that compares completed Phase 9 MFE/MAE observations across the market regime and volatility state that existed when each setup was confirmed.

## Point-in-time attribution

- Regime context is captured exactly once when a new eligible Phase 9 observation is created.
- Context includes the Phase 11 algorithm version, regime, volatility state, M5 trend direction, M1 alignment, selected features, M5 candle IDs, and M5 window end.
- The M5 evidence window must end at or before the M1 retest confirmation timestamp. A later M5 window is rejected as `TEMPORAL_ALIGNMENT_FAILED`.
- Regime context is stored in a separate `observation_regime_context` table with database triggers preventing UPDATE and DELETE.
- Existing observations without setup-time context are never backfilled using later market data. They remain unclassified.
- Context unavailable at setup time is explicitly recorded and excluded from conditioned cohorts.

## Statistical cohorts

Only completed Phase 9 observations with nonzero immutable M1 evidence, consistent candle counts, and valid immutable setup-time regime context are included.

Descriptive MFE/MAE groups are provided by:
- regime;
- volatility state;
- regime × volatility;
- session × regime;
- direction × regime;
- session × direction × regime;
- M1 alignment.

Each group includes sample size, sample-quality label, and mean, nearest-rank median, p25, p75, minimum, and maximum MFE/MAE. Minimum sample size is a reporting convention, not a significance test.

## Runtime ordering

The runtime computes Phase 11 regime intelligence before advancing Phase 9 observation tracking. The exact report is passed into the tracker at the setup observation boundary. The Phase 12 evaluator reads the observation database in SQLite read-only mode and publishes `regime_conditioned_outcome_evaluation`.

## Explicit limits and non-authorities

- This is descriptive segmentation, not a backtest, causal analysis, forecast, or profitability claim.
- MFE/MAE remain independent price excursions from the retest close, not actual trade returns.
- Intrabar ordering, fills, spread/slippage, and actual SL/TP outcomes remain unknown.
- Missing or temporally invalid context is excluded, never inferred later.
- No optimization, automatic learning, strategy mutation, signal, entry, order, or MT5 execution is introduced.
- Phase 10 aggregate statistics remain unchanged.
- Reports carry `decision_authority=ASSESSMENT_ONLY`, `trade_authority=NONE`, and `order_execution=DISABLED`.

## Acceptance coverage

Focused tests cover setup-time regime segmentation, volatility cohorts, immutable context, temporal leakage rejection, no backfill, active observation exclusion, read-only evaluation, missing database handling, and absence of trade authority.

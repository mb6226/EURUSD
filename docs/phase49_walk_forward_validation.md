# Phase 49 — Walk-Forward Validation

## Purpose

Evaluate whether the fixed Phase44 EURUSD baseline and fold-local uncertainty intervals remain stable across successive chronological out-of-sample windows. This is validation, not model fitting or a claim of predictive skill.

## Protocol

- Input must be a COMPLETE Phase45 EURUSD M5 strict system-knowledge replay with all six PIT integrity flags true.
- Validate completed forecasts only. Missing outcomes are excluded, never imputed. Each forecast and target must retain its immutable snapshot/anchor/target provenance.
- Evaluate 15M, 1H and 4H separately.
- Default rolling protocol: at least 100 training outcomes, a 30-outcome non-overlapping test window, up to 500 latest eligible training outcomes, and at least two folds.
- At every fold boundary, purge any training record whose target candle close is later than the first test forecast cutoff. Thus all training labels are actually available at the test start.
- Fit fold-local normalized absolute-error interval multipliers from training records only, for 80%, 90% and 95% target coverage; evaluate coverage and width only on the next untouched test block.
- Report per-fold MAE, RMSE, signed bias, directional agreement, descriptive baseline band coverage, fitted interval coverage/width, and aggregate/fold-to-fold descriptive stability.

## Fail-closed behavior

- A missing/incomplete replay, missing integrity flags, unsupported stream, invalid provenance, duplicate forecasts or malformed dispersion/bands cannot be promoted to validation.
- A horizon needs at least two complete chronological folds. Overall status is AVAILABLE only when all three horizons qualify, PARTIAL when some qualify, and BLOCKED when none qualify.
- Training and test horizons are never pooled. No forecast cutoff may cross a fold boundary.

## Limitations

- Phase44 is a fixed baseline. No model parameters or strategy rules are optimized in this phase.
- Repeated anchors and overlapping target windows create serial dependence; sample counts are not independent trials.
- Fold stability is descriptive and does not guarantee future performance or stationarity.
- Fold-local interval multipliers are research-only and are not applied to Phase44 or live monitoring.
- No probabilities, calibrated confidence, trading performance, execution costs or profitability are inferred.
- Current production remains BLOCKED because Phase45 cannot replay legacy schema-v3 candles without the immutable candle-version ledger. Synthetic fixtures validate implementation only.

## Safety boundaries

No provider activation, network fetch, credential access, production DB mutation, monitor restart, RAG mutation, risk/order change, live forecast rewiring, commit or merge.


## Phase51 operational recheck

After v4 archive activation, Phase49 was re-run against the refreshed Phase45 report and remains BLOCKED because no complete scored replay is available yet. Versioned M1/M5 evidence is now accumulating; walk-forward folds will remain unavailable until sufficient completed target outcomes exist.

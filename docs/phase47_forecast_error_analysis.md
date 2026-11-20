# Phase 47 — Forecast Error Analysis

## Purpose

Phase47 adds descriptive error diagnostics over completed Phase45 point-in-time replay records. It does not retrain or select models, alter Phase44, or claim predictive skill.

## Metrics (separate by 15M / 1H / 4H)

- Directional accuracy including neutral and separately for non-neutral forecasts; confusion matrix and breakdown by forecast direction.
- MAE, RMSE, signed bias (actual minus forecast), median absolute error, P90/P95 absolute error.
- Forecast-vs-realized mean movement and mean absolute movement.
- Error by forecast dispersion tercile. These are sample-relative uncertainty strata, not market regime labels.
- Sample count, outcome coverage and configured minimum-sample flag.

## Point-in-time contract

Only COMPLETE Phase45 reports with M5 EURUSD identity and all six replay integrity flags true are accepted. Each scored record needs forecast identity, cutoff snapshot hash, anchor version, target version, finite expected/actual movement and supported direction labels. Missing outcomes are counted, never imputed. Duplicate IDs and invalid horizons are rejected with reason codes.

## Attribution boundaries

Current Phase45 records do not include contemporaneous Phase39 regime labels or all raw feature inputs. Consequently regime attribution and causal feature attribution are explicitly unavailable; the engine does not infer market regime retrospectively. Dispersion terciles are descriptive bins only. Probability metrics remain unavailable because Phase44 emits no calibrated probabilities.

## Production readiness

The Phase45 production preflight is BLOCKED by the schema-v3 spot archive lacking the immutable candle-version ledger. Therefore there is no completed production replay to analyze. Phase47's production result is BLOCKED / NO_COMPLETED_PIT_REPLAY, with no production error metrics. Synthetic unit fixtures test calculations only and are never presented as market performance.

## Safety

No changes to live forecast generation, Fusion/decision authority, trading risk, order execution, source activation, production database, monitor processes or RAG. No automatic model adjustment based on descriptive sample metrics.

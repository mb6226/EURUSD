# Phase 50 — Cross-Domain Attribution

## Objective

Describe how out-of-sample EURUSD forecast errors vary across contemporaneously observed cross-domain market states. This is an evidence-attribution research layer, not causal attribution, feature importance, a directional vote or a model-selection mechanism.

## Input contract

- Requires a COMPLETE Phase45 EURUSD M5 strict system-knowledge replay and all six Phase45 point-in-time integrity flags.
- Each completed forecast must retain its forecast ID, replay ID, forecast cutoff, target close, forecast snapshot hash, anchor/target version IDs and realized move.
- Each forecast record must carry a contemporaneous `domain_context` map. Every feature is bound to that forecast's exact snapshot hash and carries a separate context snapshot hash, evaluated/as-of/available timestamps, status, state, source-lineage IDs and evidence references.
- Every context timestamp must be no later than the forecast cutoff. Future, mismatched, unhashed or unprovenanced context is rejected, never repaired or inferred.
- Missing/unavailable domain states are counted as coverage gaps; they are never imputed.

## Domains and dependency controls

Spot FX, macro fundamentals, monetary policy, intermarket, positioning/sentiment, news/events, market regime, session/time, liquidity/microstructure and derived cross-domain relationships are handled independently as conditional state dimensions.

Shared price-derived lineage, macro/policy lineage and derived relationship lineage are explicitly grouped. Multiple views of the same underlying evidence do not count as independent confirmations. Cross-domain relationship outputs remain derived context, not independent causal drivers.

## Analysis

For each horizon (15M, 1H, 4H) separately:
- Establish a horizon-wide descriptive baseline (MAE, RMSE, signed error and directional agreement).
- Stratify completed forecasts by each available domain state.
- For sufficiently populated states, report sample count, MAE, RMSE, signed bias, directional agreement and deltas versus the horizon baseline.
- Default minimum is 30 observations per state. Smaller groups remain visible as insufficient and are not scored or ranked.
- No horizons are pooled and no missing outcomes/context are imputed.

## Interpretation boundaries

Conditional differences are associations only. They do not establish causality, incremental predictive contribution, feature importance or model performance improvement. Serial dependence, overlapping forecast horizons, selection effects and unmeasured confounding remain. No model training/tuning, probabilities, calibrated confidence, trading P/L or live decision authority is introduced.

## Current production limitation

Phase45 production replay remains BLOCKED because the market archive is schema v3 and lacks the immutable candle-version ledger. Existing replay records also explicitly state that historical scenario context was not supplied at their cutoffs. Consequently production attribution emits no metrics. Synthetic fixtures test the implementation only.

## Safety

Read-only production preflight. No provider activation, external fetch, credential access, database mutation, monitor restart, RAG mutation, risk/order changes, live decision wiring, commit or merge.


## Phase51 integration

Phase50 attribution is consumed by Phase51 only when it shares the exact Phase45 replay ID and source-history hash with Phase49. A per-horizon attribution state must have at least 100 completed contemporaneous records before it can contribute to research readiness. It never triggers automatic model tuning or promotion.


## Phase51 operational recheck

After v4 archive activation, Phase50 was re-run against the refreshed Phase45 report and remains BLOCKED because the official replay is awaiting a defined replay window and matured target outcomes. The real-data smoke replay still has no outcomes and historical per-cutoff domain context is not yet archived, so no production attribution metrics are emitted.

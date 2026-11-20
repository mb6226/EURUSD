# Phase 46 — Scenario Evaluation Framework

## Purpose

Phase46 adds a strict evaluation contract for qualitative central scenarios emitted by Phase43. It is separate from Phase44 numeric baseline forecast replay and does not infer trading performance.

## Evaluation rules

- Only a Phase43 report archived no later than its issue timestamp is eligible. The canonical report SHA-256 must match.
- Broker, symbol, issue timestamp and explicitly declared horizon must match exactly. No nearest-time join or implicit 15-minute/1-hour/4-hour horizon is allowed.
- The report must contain exactly one LEADING_HYPOTHESIS and a contemporaneous scenario_evaluation_spec declaring horizon, supported outcome classifier and invalidation-rules version.
- Outcomes must be independently supplied, closed-bar classifications with exact window boundaries, UTC time basis, known price basis, source candle-version IDs, evidence SHA-256, and observed/as-of timestamps no later than the evaluation cutoff.
- Unresolved, conflicted, degraded, unarchived, un-horizoned or unverifiable records are excluded with reason codes.
- Reports are never reconstructed from current Phase43 logic or current market state.

## Separation from Phase44/45

Phase44/45 evaluates numeric baseline price forecasts over 15m, 1h and 4h using strict candle-version replay. Phase46 evaluates a Phase43 categorical leading hypothesis only when Phase43 itself declared an evaluation horizon and invalidation-rule version at issuance. Phase44 forecast outcomes cannot be silently reused as scenario outcomes unless a separate exact-match outcome record satisfies the Phase46 contract.

## Current production readiness

- Phase43 currently emits qualitative conditional hypotheses but does not declare a horizon-specific scenario_evaluation_spec.
- No verified contemporaneous Phase43 scenario archive is configured or proven available.
- Phase45 production replay is separately blocked because the market archive remains schema v3 without an immutable candle-version ledger.
- Therefore the current Phase46 production status is NO_ARCHIVED_SCENARIOS; no accuracy figure is reported and no scenario is scored.
- The framework is available for future compliant archives. Live monitor wiring and archive capture are not introduced in this phase.

## Safety and interpretation

Scenario match rate is categorical research evidence only. It is not a probability, calibrated confidence, trading win rate, expectancy, P/L, or proof of predictive skill. No Fusion/decision authority, risk setting, order execution, provider activation, production database mutation, or monitor restart is part of this phase.

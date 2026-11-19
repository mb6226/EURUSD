# Phase 7 — Rejection, Pullback and Setup Assessment Contract

## Scope
Phase 7 adds a deterministic M1 pattern evaluator downstream of the existing M5 correction lifecycle. It does not replace TechnicalEngine, ImpulseDetector, CorrectionDetector, LifecycleStateMachine, LifecycleStore, or FusionEngine.

## Direction authority
M5 lifecycle trend direction is authoritative. M1 candles may confirm or fail a rejection/pullback but may never change the trend direction.

## Rejection
Only closed M1 candles at or after the confirmed correction timestamp are eligible. For an UP trend, the candle must touch/penetrate the correction extreme, close above that level and above its open, have a lower-wick/body ratio at least `min_wick_body_ratio`, and close location at least `bullish_close_location_min`. DOWN is the mirror image using the upper wick and `bearish_close_location_max`.

## Pullback
The trigger is the rejection candle high for UP and low for DOWN. A later closed M1 candle must close beyond the trigger (breakout). A still later candle must retest within `pullback_tolerance_pips` and close back on the trend side. Retest confirmation timestamp is exactly its candle close.

## Fail-closed behavior
Missing lifecycle, unconfirmed correction, no M1 data, malformed ordering, duplicate timestamps, wrong timeframe, and open candles cannot create a confirmed pattern. No next-bar entry price, SL/TP, order, or trade permission is created. Every assessment has `decision_authority=ASSESSMENT_ONLY`, `trade_authority=NONE`, and `entry_eligibility=BLOCKED`.

## Baseline parameters
The existing config values (wick/body 1.5, bullish close location 0.70, bearish close location 0.30, pullback tolerance 2 pips) are experimental, not statistically validated. Phase 7 does not enable live signals.

## Important limitation
This implementation is a pattern-stage evaluator, not a profitability claim. It does not yet establish session eligibility, one-setup-per-session enforcement, spread/slippage feasibility, entry gap policy, or historical performance. Those remain separate acceptance criteria before any future strategy activation.

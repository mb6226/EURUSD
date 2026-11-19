# Phase 28 — Central Multi-Domain Scenario Intelligence

## North Star capability

Advance capability 11 in the Master System Architecture: synthesize the live EURUSD cycle into explainable alternative market scenarios while preserving the boundary between directional price evidence and contextual macro/market evidence.

## Runtime integration

CentralScenarioIntelligenceEngine is invoked once per monitoring cycle after the current specialists and Research Intelligence report have been assembled. Its runtime adapter binds:
- Technical structure, confirmed Price Action lifecycle, and market-regime assessment
- Fusion assessment as an integrity/context summary, not a second directional vote
- Macro fundamentals, policy-rate differential, intermarket, CFTC positioning, quantitative statistics, and liquidity/microstructure
- Macro calendar and news/event context
- Setup/session gates and historical descriptive outcome reports

The engine publishes central_scenario_intelligence in the cycle payload.

## Direction and scenario contract

- Directional description is limited to technical structure, confirmed Price Action lifecycle, and market-regime state.
- These price-derived inputs share broker price data. Their agreement is a consistency check, not independent votes or additive evidence weight.
- Conflicting UP/DOWN inputs produce CONFLICTED; a directional structure alongside a ranging regime produces MIXED; neither is averaged into a direction.
- Three qualitative hypotheses are always emitted: EURUSD up continuation, EURUSD down continuation, and range/transition.
- Scenario labels are LEADING_HYPOTHESIS, ALTERNATIVE, UNRESOLVED, UNRESOLVED_CONFLICT, or NOT_ESTABLISHED; no numeric probability or calibrated confidence is emitted.
- Policy spreads, inflation/unemployment gaps, intermarket correlations, positioning, quantitative distributions, liquidity proxies, calendar and news are context only. They do not cast EURUSD directional votes.
- Explicit price-vs-policy and price-vs-regime tensions are described without claiming causality.
- Setup/session eligibility and historical MFE/MAE/outcome reports remain downstream gates or descriptive context; they cannot upgrade or vote on scenarios.

## Evidence integrity

- Every source must have a timezone-aware evaluation timestamp no later than the current cycle and within the configured report-age limit.
- Explicit broker/symbol identity mismatches, missing/future timestamps, stale reports, and unavailable sources remain visible and cannot contribute evidence.
- Specialist status, evaluation timestamp, reason codes, and available source/candle provenance references are retained in the domain ledger.
- Missing context is not imputed. No fabricated values, interpolation, or provider fetches are introduced.

## Acceptance

- Unit tests cover aligned, opposing, mixed trend/range, range-only, missing, stale, future-dated and identity-mismatched evidence.
- Tests prove context-only domains cannot create directional votes, stale context cannot create a cross-domain tension, and historical outcomes/setup gates cannot vote.
- Tests verify evidence reference preservation, cycle-to-engine source binding, no probabilities, and no execution parameters.
- The complete repository regression suite passes on the exact PR head.

## Non-goals and remaining gaps

- No calibrated probability, confidence score, source reliability weighting, causal macro model, scenario backtest/replay, or automated learning is claimed.
- No support/resistance price levels, entry/exit, stop/target, position sizing, or risk instruction is generated.
- No Fusion directional-vote changes, strategy changes, BUY/SELL enablement, or MT5 order execution.
- No automatic external data fetch, observation-store write, or RAG/knowledge database mutation.
- This is the first deterministic scenario-synthesis vertical slice, not completion of the full central brain described in the North Star.

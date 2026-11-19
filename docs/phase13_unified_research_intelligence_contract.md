# Phase 13 — Unified Research Intelligence Contract

## Purpose

Phase 13 introduces a deterministic, read-only synthesis layer over the specialist outputs already produced by Phases 6–12. It creates one coherent research-cycle report so an operator can understand the current market context, setup lifecycle, session gate, and the quality/coverage of historical outcome evidence without manually reconciling several independent payloads.

This is an aggregation and integrity layer, not a new directional specialist, strategy, backtest, optimizer, learner, or execution component.

## Existing authorities remain unchanged

The following responsibilities remain with their existing components:

- Phase 6 Fusion: validates the availability, freshness, and directional agreement of technical and price-action evidence; macro and news remain context-only.
- Phase 7 Setup Pattern: evaluates rejection, breakout, and pullback-retest lifecycle stages.
- Phase 8 Session Eligibility: applies the existing session and research-risk reservation gate.
- Phase 9 Observation Tracker: stores immutable M1 price-excursion evidence.
- Phase 10 Statistical Evaluator: reports aggregate descriptive MFE/MAE distributions.
- Phase 11 Market Regime Engine: classifies M5 structure/volatility and context-only M1 alignment.
- Phase 12 Regime-Conditioned Evaluator: reports descriptive MFE/MAE cohorts using immutable setup-time regime context.

Phase 13 must not recalculate, override, or reinterpret these specialist decisions. In particular, Fusion's `READY_FOR_RULES` is not a trade-ready state, Phase 8 eligibility is a research reservation only, and MFE/MAE are not realized trade results.

## Proposed component

Add a pure `ResearchIntelligenceEngine` with an immutable input contract and immutable output model. It receives already-built payloads from the current runtime cycle:

1. cycle identity: broker server, symbol, and timezone-aware evaluation timestamp;
2. `fusion_assessment`;
3. `market_regime_intelligence`;
4. `price_action_lifecycle`;
5. `setup_assessment`;
6. `session_eligibility`;
7. `setup_outcome_observation`;
8. `statistical_outcome_evaluation`;
9. `regime_conditioned_outcome_evaluation`.

The engine performs no I/O, database access, network access, clock reads, or mutation. The caller supplies every input explicitly. Identical inputs must produce identical output.

## Output contract

Publish one `research_intelligence` object containing:

- `status`: `COHERENT`, `PARTIAL`, `BLOCKED`, or `DEGRADED`;
- `evaluated_at_utc`, `broker_server`, and `symbol`;
- `current_context`: normalized references to the current fusion, regime, lifecycle, setup, and session states;
- `historical_outcome_context`: normalized Phase 9–12 observation coverage and descriptive-statistics availability, explicitly marked historical/descriptive;
- `source_manifest`: one entry per required input with source name, normalized status, source evaluation timestamp when present, and reason codes;
- `reason_codes`: deterministic, deduplicated reasons explaining missing, stale, future-dated, blocked, or degraded inputs;
- explicit interpretation and authority flags.

The output must not duplicate large specialist payloads or recompute their metrics. It should retain concise state references and provenance sufficient to locate the original payloads in the same published cycle.

## Coherence rules

- All timestamps must be timezone-aware and normalized to UTC.
- Current-cycle inputs must not be future-dated relative to the supplied cycle timestamp.
- Current-cycle specialist evidence must satisfy an explicit freshness limit (initial default: 300 seconds, configurable and validated); stale or future evidence is never silently treated as neutral.
- Historical outcome reports are a separate evidence class. Their cohort observations may be old by design; freshness applies to when the report was evaluated, not to the age of its underlying historical observations.
- Missing or unavailable sources produce an incomplete/partial research view; malformed, contradictory, or temporally invalid source metadata must be surfaced with reason codes and must not be repaired by inference.
- A blocked setup or session gate is reported as such, not converted into a favorable/negative directional vote.
- Phase 10 and Phase 12 statistics are descriptive context only. They cannot vote on direction, upgrade setup status, or grant eligibility.
- Phase 9 active observations remain active observations; Phase 13 must not infer completion or outcomes.

## Status semantics

- `COHERENT`: all required current-cycle sources are present, valid, and fresh; historical reports may legitimately indicate insufficient sample size without making current-cycle context incoherent.
- `PARTIAL`: one or more non-critical research sources are unavailable or missing, while the available current context remains internally valid.
- `BLOCKED`: a required current-context gate explicitly reports a blocked state, or critical directional/context evidence is unavailable such that no coherent current assessment can be formed.
- `DEGRADED`: malformed data, future timestamps, contradictory identity/timestamps, or an internal aggregation error prevents a trustworthy synthesis.

Status is descriptive only. It is not an entry signal, execution permission, or trade authorization.

## Runtime integration

The runtime will build `research_intelligence` only after the existing Phase 6–12 payloads for that cycle have been constructed. It will publish the new object alongside, not instead of, the original specialist payloads. If aggregation raises an exception, the runtime publishes a minimal `DEGRADED` report with a stable reason code and continues the existing alert-only/WAIT path.

No existing output schema, evaluator, persistence table, risk ledger, or RAG store is modified by the aggregation layer.

## Explicit non-authorities

Phase 13 does not:
- issue BUY/SELL, entry, exit, or trade recommendations;
- change the legacy `WAIT` decision or Fusion output;
- grant trade authority, entry eligibility, order authority, or MT5 access;
- reserve or release risk, alter session gates, or modify SL/TP;
- infer fills, spread/slippage, realized P/L, win rate, expectancy, or actual SL/TP hits;
- optimize thresholds, train models, perform automatic learning, or mutate strategy configuration;
- write to Phase 9 observation databases, Phase 8 risk databases, or RAG/knowledge stores.

Every output must include `decision_authority=ASSESSMENT_ONLY`, `trade_authority=NONE`, and `order_execution=DISABLED`.

## Implementation sequence

1. Implement immutable models and the pure aggregation engine.
2. Add unit tests for deterministic output, missing sources, stale/future timestamps, identity mismatches, blocked gates, descriptive-only outcome reports, and authority invariants.
3. Integrate the engine into the runtime after all existing specialist outputs are available.
4. Add runtime tests for successful publication and fail-closed degradation.
5. Run focused tests and the full project suite before opening a code-bearing PR for local acceptance.

This document defines the contract only. It does not claim that Phase 13 implementation or live runtime acceptance is complete.

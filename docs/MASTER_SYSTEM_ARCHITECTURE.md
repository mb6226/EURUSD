# EURUSD AI — Master System Architecture & North Star

## 1. Product identity

This repository is intended to become a comprehensive EURUSD market-intelligence system: an evidence-grounded, multi-domain analytical brain that observes the currency pair and its drivers, builds and tests explanations, evaluates uncertainty, tracks outcomes, and improves through controlled research.

It is **not** a Price Action bot, indicator bundle, single-strategy robot, or LLM that guesses the next candle. Price Action is one specialist domain among many.

The system's long-term output is a transparent market-state and scenario assessment, including uncertainty, conflicting evidence, invalidation conditions, and (only after separately validated and authorized) strategy-specific setup/risk assessments. Live order execution remains disabled unless explicitly approved in a separate decision.

## 2. North Star capabilities

The following are product-level capability domains. They are not claims that the current repository already implements them.

1. **Data foundation and data quality** — broker ticks/bars, historical archives, timestamps, spreads, session calendars, corporate/economic calendars, source provenance, revisions, missing-data detection, and point-in-time correctness.
2. **Price and market-state intelligence** — multi-timeframe OHLCV, trend/structure, volatility, ranges, gaps, momentum, market phases, and regime transitions.
3. **Technical-analysis intelligence** — indicators, levels, patterns, multi-timeframe relationships, and independently testable technical features.
4. **Price-action intelligence** — impulses, corrections, rejection, breakouts, pullbacks, lifecycle states, and candle-level evidence. This domain must never dominate the product architecture.
5. **Quantitative/statistical intelligence** — distributions, conditional probabilities, event studies, wave/sequence statistics, volatility models, hypothesis tests, uncertainty estimates, and robust out-of-sample validation.
6. **Macro/fundamental intelligence** — ECB/Fed policy, rate differentials, inflation, labor, growth, fiscal conditions, central-bank communication, releases versus consensus/previous values, revisions, and macro surprises.
7. **News/geopolitical intelligence** — official and reputable news, event classification, entity/currency impact, source reliability, novelty, time decay, and explicit uncertainty. Headlines are not automatically directional evidence.
8. **Intermarket intelligence** — DXY and constituent currencies, US/German yields and yield spreads, rates futures where accessible, equity risk proxies, gold, energy, and empirically tested lead/lag/correlation relationships.
9. **Positioning/sentiment intelligence** — CFTC positioning, options-implied information and risk reversals where licensed/free data permits, futures positioning, and carefully qualified sentiment proxies.
10. **Liquidity/microstructure intelligence** — bid/ask spread, tick activity, session liquidity proxies, volatility around events, order-book/depth only where genuinely available, and execution-cost modeling. Never pretend OTC spot FX has a consolidated order book.
11. **Cross-domain central intelligence** — shared cycle context, specialist orchestration, evidence normalization, conflict detection, source weighting by demonstrated reliability, scenario synthesis, and calibrated uncertainty. No naive majority vote.
12. **Memory and knowledge** — versioned market observations, event/outcome memory, reviewed domain knowledge, retrieval with citations/provenance, and separation of static knowledge from time-sensitive market facts.
13. **Research and learning laboratory** — hypothesis registry, experiment definitions, reproducible datasets, baselines, walk-forward testing, leakage controls, ablation, model evaluation, drift detection, and human-reviewed promotion. No automatic production strategy/config changes.
14. **Decision, risk and execution boundary** — explainable scenario/setup assessment, invalidation, risk constraints, and eventually separately authorized execution adapters. Analytical authority and execution authority must remain distinct.
15. **Operations and observability** — health, freshness, latency, lineage, failure states, logs, metrics, reproducibility, model/data versions, and operator-facing explanations.

## 3. Target architecture

### A. Ingestion and canonical data plane
Connectors acquire data. Source adapters validate transport and schema. Canonical models normalize time, units, identity, and provenance. Immutable/raw evidence is retained where appropriate; derived data records its source lineage.

### B. Domain specialist plane
Each domain specialist consumes explicit, point-in-time inputs and publishes a versioned, typed assessment with status/reason codes, evaluation and source timestamps, instrument identity, evidence references, methodology/version, uncertainty, limitations, and an explicit authority declaration.

A placeholder, disconnected provider, stale source, or missing evidence must be reported as unavailable/degraded—not represented as a completed specialist.

### C. Central orchestration and synthesis
The central layer decides which specialists are applicable for the current question/regime, checks freshness and lineage, detects contradictions, separates facts from interpretations, and produces multiple scenarios with supporting and opposing evidence. It must not manufacture missing data or convert context-only sources into directional votes.

### D. Memory, research and learning
Persist observations and research artifacts with reproducibility metadata. Research may propose new features/models/rules, but production promotion requires out-of-sample evidence, regression tests, review, and versioned approval.

### E. Decision and execution boundary
Market understanding, strategy eligibility, risk approval, and order execution are separate layers. The current project remains alert-only/WAIT. No live order placement, order management, or risk-setting change is introduced by architecture work.

## 4. Non-negotiable engineering principles

- Point-in-time correctness; no look-ahead or future leakage.
- Closed-bar rules must be explicit per timeframe and specialist.
- Missing/stale/contradictory evidence is visible and fail-closed.
- Every meaningful conclusion is traceable to data, source, timestamp, and algorithm/model version.
- Deterministic components are preferred for deterministic calculations; ML/LLM is used only where it adds measurable value.
- LLM/RAG text is not a substitute for verified market data or a standalone trade authority.
- Historical descriptive MFE/MAE is not realized trade P&L or proof of profitability.
- No single specialist (including Price Action) owns the central decision.
- Avoid over-engineering: implement the smallest vertical slice that closes a real capability gap and integrates end-to-end.
- Free/official sources and local compute are preferred; licensing, availability, and operational cost must be documented.
- Existing legacy WAIT/decision behavior is preserved until a replacement is independently validated and explicitly approved.
- RAG/knowledge databases are not migrated, reset, or mutated without separate explicit approval.
- Live trading stays disabled without separate explicit approval.

## 5. Roadmap sequence and exit gates

The roadmap is capability-driven, not a chain of arbitrary numbered engines.

### Gate 0 — Product contract and repository truth
Maintain this North Star, a capability audit, dependency map, source-of-truth register, and prioritized gap list. Distinguish implemented, scaffolded, disconnected, and absent capabilities.

### Gate 1 — Reliable canonical data plane
Expand beyond the current M1/M5 broker feed: historical data/replay, tick/spread quality, robust time/session handling, point-in-time macro/news/event data, and source health. Exit with reproducible replay and data-quality tests.

### Gate 2 — Domain specialist coverage
Build real quantitative/statistical, macro/fundamental, intermarket, positioning/sentiment, liquidity, and news-analysis capabilities. Keep technical, Price Action, and regime specialists independent. Every specialist needs real sources/data, explicit contracts, tests, and limitations.

### Gate 3 — Central intelligence v2
Add applicability-aware orchestration, evidence conflict analysis, scenario generation, uncertainty calibration, and explainable synthesis. Exit with replayable end-to-end cycles across multiple market regimes.

### Gate 4 — Memory and research laboratory
Versioned observations, knowledge provenance, experiment/hypothesis tracking, feature-store discipline, reproducible backtests, walk-forward validation, ablations, and drift monitoring. No automatic promotion.

### Gate 5 — Decision and risk validation
Validate candidate setups against realistic spread, slippage, execution assumptions, session limits, and out-of-sample results. Preserve alert-only operation until explicit authorization.

### Gate 6 — Operational readiness
End-to-end monitoring, recovery, deployment/runbooks, data/source health, auditability, and operator reporting. Live execution remains a separate optional project requiring explicit approval.

## 6. Phase/PR alignment rule

Before starting any phase, record: (1) North Star capability advanced; (2) concrete repository gap; (3) dependencies/interfaces; (4) integration path; (5) measurable acceptance criteria; and (6) explicit non-goals.

A phase that only adds a standalone engine without a consumer, data contract, tests, and integration path is not meaningful progress.

## 7. Current status

See `REPOSITORY_CAPABILITY_AUDIT.md` for the current evidence-based inventory. This architecture describes the intended destination, not current completeness.

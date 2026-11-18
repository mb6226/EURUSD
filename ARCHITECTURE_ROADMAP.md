# EURUSD AI — Intelligent Market Brain Roadmap

## Mission
Build a specialist AI system combining market data, macroeconomic context, news, technical structure, price action, statistical research, evidence and evaluated experience. It should explain observations, supporting evidence, invalidation and uncertainty.

**Safety baseline:** alert-only; no order placement or execution. LLM output alone is never a trade signal. Alert eligibility must be controlled by deterministic checks and versioned configuration.

## Existing components (initial GitHub audit)
- MT5 connector: connection, ticks, M1/M5 candles, ranged historical retrieval, screenshot paths.
- MarketDataStore: durable candles, closed-candle queries, revision tracking, backfill checkpoints.
- MT5 market adapter: connector-to-store adapter and historical backfill.
- TechnicalEngine: confirmed M5 swing structure, trend classification, protected swing break, point-in-time analysis; no entries.
- Price-action models and StrategyConfig: typed evidence/setup models and versioned parameters.
- Price-action engine: provisional range summary only; full setup logic is not implemented.
- Decision engine: conservative/WAIT path; live signal generation disabled.
- Vision engine: screenshot freshness/availability only; actual vision interpretation is not connected.
- Signal manager: alert payload logging.
- knowledge_v2: document extraction, chunking, local embeddings/Ollama, SQLite/FTS + semantic retrieval and answer generation.
- source_registry: source definitions, schemas, validation, state DB, manager and initial Fed/ECB adapters.
- tests: market store, MT5 adapter, price-action models, technical engine, strategy config and source registry.

## Target architecture

### 1. Data foundation
**Market Data Gateway:** MT5 ticks and closed candles (M1/M5, later higher timeframes); history/replay; broker/time normalization; symbol mapping; data gaps, spread, freshness and revisions. Analysis must not consume unclosed candles where closed bars are required.

**Economic & Event Data:** calendar events (time, currency, impact, actual/forecast/previous/revisions); Fed/ECB policy, speeches and minutes; macro series (inflation, labor, growth, surveys, yields, expectations); news and geopolitical events with source timestamps, duplicate handling, reliability and impact labels. Track source provenance, cadence, rate limits, permitted usage and health.

### 2. Specialist engines
Each engine produces a structured, versioned report with timestamp, evidence IDs, quality/confidence and explicit unknowns. Engines do not overwrite each other's conclusions.
- **Technical Brain:** multi-timeframe structure, swings, trend/range/transition, protected levels, breaks, volatility.
- **Price Action Brain:** impulse/correction, rejection, pullback, setup lifecycle, invalidation and entry eligibility; deterministic rules first.
- **Macro Brain:** US/EU policy divergence, rate expectations, growth, inflation, labor and yield differentials; conditional interpretation.
- **News Brain:** extraction, deduplication, EURUSD relevance, surprise versus consensus, reliability and decay.
- **Calendar/Event Risk Brain:** event windows and scheduled/unscheduled uncertainty.
- **Session Brain:** London, New York and overlap; timezone/DST and session statistics.
- **Statistical Brain:** volatility regimes, distributions, conditional frequencies, waves and evidence-based pattern research.
- **Vision Brain (optional):** visual observations corroborated with OHLC; cannot override structured price data.

### 3. Intelligence and evidence
- **MarketContextBuilder:** point-in-time context assembled from validated data; track stale/missing data; preserve snapshots.
- **Evidence/Provenance:** link claims to source/data, observed time, method/version and quality; distinguish facts, derived metrics, hypotheses and interpretations; retain disagreements.
- **RAG:** curated educational and official policy material with source references. RAG explains/retrieves; it does not authorize trade decisions.

### 4. Decision & risk
- **Intelligence Fusion:** transparent engine agreement/conflict, completeness and confidence; preserve disagreements.
- **Setup State Machine:** watch → forming → qualified → invalidated/expired → outcome tracking; deterministic transitions and logs.
- **Decision Engine:** WAIT by default; alert eligibility only when mandatory rules and quality gates pass.
- **Risk Gate:** session, event risk, spread, volatility, gap, stop-distance, sizing assumptions, session limits and invalidation.
- **Alert Output:** structured and readable; setup/direction only if eligible, entry conditions, invalidation, SL/TP assumptions, evidence, confidence, and why WAIT was selected.

### 5. Memory and learning
Separate versioned stores:
- **Knowledge memory:** reviewed educational material, manuals and official policy.
- **Market memory:** snapshots, regimes, events, waves and observations.
- **Experience memory:** setup/decision lifecycle, hypothetical outcome and labels.
- **Strategy memory:** configurations, assumptions, validation and test results.

Learning process: record immutable evidence/outcomes → formulate hypotheses → chronological testing without look-ahead → train/validation/test or walk-forward → realistic spread/slippage assumptions → baselines, sample size, uncertainty and robustness → version proposed changes and require approval before production-alert changes.

### 6. Research lab / autonomous research
Historical replay, parameter sensitivity, ablation, regime/session/event analysis and pattern discovery with anti-overfitting controls. Research agent proposes experiments, not production changes. Scheduled work must have bounded scope, permissions, resource limits, logs and review.

### 7. Observability
Health checks for MT5, sources, Ollama, databases and storage; structured logs/run IDs; stale data, missing candles, failed ingestion, parser drift and database error alerts; retry/rate-limit/checkpoint policies; graceful degradation to WAIT.

## Phased roadmap
0. **Architecture & contracts:** schemas, evidence/provenance, time/freshness/confidence semantics, module boundaries.
1. **Market data integration:** wire existing MT5 adapter/store into monitor/context builder; persist/validate M1/M5, tick/spread, source identity and revisions; integration/replay tests; diagnostic-only.
2. **Technical intelligence:** higher timeframe context, M1 trigger observations, regime/volatility; point-in-time/evidence/revision tests.
3. **Price Action lifecycle:** Trend → Correction → Rejection → Pullback as explicit state machine; expiry, invalidation, entry-gap policy, session logic; parameters remain unvalidated and alerts disabled until evaluation gates.
4. **Macro/calendar:** reliable official-source ingestion, fixtures, freshness and error states; calendar and policy context.
5. **News intelligence:** source-aware ingestion, deduplication, extraction, relevance/impact and source-drift monitoring.
6. **Fusion & risk:** transparent synthesis, conflict reporting, WAIT-first gates and alert explanations.
7. **Outcome tracking:** hypothetical setup lifecycle, explicit fill/SL/TP rules, metrics and uncertainty.
8. **Backtest/research lab:** realistic replay, walk-forward, sensitivity, experiment registry and leakage prevention.
9. **Learning/autonomous research:** evidence-driven hypotheses, bounded experiments, reproducible validation and human approval; no self-modifying production rules.
10. **Dashboard/briefing:** regime, technical evidence, macro/news calendar, health, setup states, invalidation and daily report, all traceable.

## Non-negotiable rules
1. No live execution.
2. WAIT is the default.
3. No LLM-only trade decisions.
4. No look-ahead; use only information available at evaluation time.
5. Closed candles where the contract requires them.
6. Every setup hypothesis traceable to data, evidence, quality, config and algorithm versions.
7. Missing/stale data is not silently neutral.
8. No automatic strategy change from one outcome.
9. Changes stay isolated on branches, tested and reviewed before merging.
10. Small, focused increments; no broad rewrites.

## Immediate next task
Phase 0: formalize module contracts and produce a file-by-file gap audit. First implementation after this is Phase 1 only: connect existing MT5/store to runtime and context builder, with signals disabled.

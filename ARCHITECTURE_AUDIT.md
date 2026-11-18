# EURUSD AI — File-by-File Architecture Audit & Gap Map

**Audit scope:** read-only inspection of repository `main` as of 2026-11-18.  
**Audit branch:** `audit/module-gap-map`  
**Status:** assessment only. No runtime code, configuration, operational databases, or test files changed.

Related roadmap: `ARCHITECTURE_ROADMAP.md` on branch `architecture/market-brain-roadmap`.

## 1. Executive summary

The repository is not an empty starter. It has several meaningful, tested foundations (market-data persistence and synchronization, a deterministic M5 structure engine, typed Price Action/setup/outcome contracts, configuration validation, a source-registry framework, and a local RAG pipeline). The principal gap is that these pieces are not assembled into a coherent runtime intelligence pipeline.

The current `main.py` still uses the original MT5-to-CSV polling path and provisional range comparison. It does **not** use the newer market-data store/adapter, typed MarketContext, TechnicalEngine, Source Registry, or RAG. Decision output is deliberately `WAIT`; live signal eligibility and execution are disabled.

## 2. Module inventory and status

| Area / files | Status | Evidence and gap |
|---|---|---|
| Runtime: `eurusd_ai_monitor/main.py` | **Exists, basic** | Polls MT5, writes M1/M5 CSV snapshots, calls provisional PA summary, screenshot freshness check and WAIT decision. No durable context orchestration. |
| MT5 connector: `engines/mt5_engine.py` | **Implemented foundation** | Connect, tick, bar retrieval, range retrieval, broker metadata, screenshot path. Requires runtime error handling, data freshness/clock validation and gateway integration. |
| Price-action heuristic: `engines/price_action_engine.py` | **Prototype only** | Range comparison across two windows. Not swing-based Trend → Correction → Rejection → Pullback; not a setup lifecycle. |
| Decision: `engines/decision_engine.py` | **Safety stub** | Always WAIT. Checks M1/M5 status, spread warning and screenshot status, then records reasons. No fusion/risk logic. |
| Vision: `engines/vision_engine.py`, screenshot EA | **Capture/validation only** | Validates image availability/freshness. No image model, structured visual evidence or vision provider. Vision config is disabled. |
| Technical structure: `engines/technical_engine.py` | **Implemented, isolated** | Deterministic confirmed M5 pivots, HH/HL vs LH/LL structure, protected-swing break, versioned parameters and closed-candle constraints. No setup/entry decisions. |
| Price-action contracts: `models/price_action.py` | **Strong contracts, no full engine** | Typed evidence, context, trend, correction, rejection, pullback, setup, eligibility, outcome and serialization. Models do not constitute a detection algorithm. |
| Strategy config: `strategy_config.py`, JSON | **Implemented validation** | Strict config, decimal validation, digest/version; baseline experimental, parameters not validated, live signals disabled, entry gap policy unset. |
| Market store: `storage/market_data_store.py` | **Implemented** | SQLite candles, exact decimals, closed-candle query, revisions, backfill checkpoints. Not called by the current monitor runtime. |
| MT5 market adapter: `storage/mt5_market_adapter.py` | **Implemented, tested** | Closed-bar sync, bounded backfill, validation, checkpointing and resume behavior. Not integrated into runtime. |
| Alerts: `alerts/signal_manager.py` | **Basic** | JSONL payload logging; not a lifecycle-aware alert manager or deduplication/state tracker. |
| News: `engines/news_engine.py` | **Missing/provider-free** | Placeholder module; no ingestion, normalization, impact scoring, freshness or provenance pipeline. |
| Calendar: `engines/calendar_engine.py` | **Missing/provider-free** | Placeholder; no event ingestion, timezone normalization, impact windows or risk gating. |
| Fundamentals/macro: `engines/fundamental_engine.py` | **Missing/provider-free** | Placeholder in runtime package; source registry has groundwork but no runtime macro specialist. |
| Statistics: `engines/statistical_engine.py` | **Missing** | Placeholder; no volatility, distributions, regimes, probabilities, wave/return statistics or validated models. |
| Learning: `learning/feedback_engine.py`, `model_evaluator.py`, `performance_analyzer.py` | **Missing** | All three are short placeholders. No outcomes store, labels, calibration, metrics or controlled learning. |
| Memory: `memory/` | **Reserved** | README and empty history directory only; no implemented market/setup/experience memory. |
| RAG: `knowledge_v2/` | **Implemented standalone** | Local Ollama embedding/generation, ingestion, chunking, SQLite/FTS, lexical/semantic retrieval and answer generation. Not connected to runtime decision/context. Must remain explanatory, not signal authority. |
| Source registry: `source_registry/` | **Framework implemented; coverage partial** | Schema/registry validation, lifecycle state DB, idempotent sync, fetch-result contracts, Fed adapter and fixture HTML parser. No runtime orchestrator/source scheduler, broad provider coverage, or market-brain integration. Registry includes source definitions, but configured sources are not equivalent to live adapters. |
| Tests: `tests/` | **Meaningful but scoped** | Tests cover market store, MT5 adapter, technical engine, model/config contracts, registry state/validation, Fed parser/adapter. No end-to-end runtime test or tests for the placeholder news/calendar/macro/statistics/learning modules, integration fusion, event risk, outcome lifecycle or backtesting. |
| Backtest/research | **Not implemented in runtime repo** | No walk-forward framework, execution simulation, experiment tracking or hypothesis-validation loop identified in the tree. |
| Observability/health | **Basic** | Console errors and JSONL signal logs exist. No unified health status, source freshness dashboard, structured run IDs or graceful subsystem degradation. |

## 3. Existing test coverage (by suite)

- Market store: schema, exact values, idempotent upsert, forming vs closed bars, revisions, time filters, checkpointing, invalid data and integrity.
- MT5 adapter: M1/M5 sync, closed candles, atomic behavior, validation, idempotency, bounded backfill and checkpoint recovery.
- Technical engine: pivot confirmation, future-data exclusion, structure classification, protected breaks, ties/plateaus, data validation and versioning.
- Models/config: serialization, evidence references, setup eligibility, entry gap policy, strict config validation and parameter digest.
- Source Registry: schema/semantic validation, lifecycle state, idempotency/rollback, Fed adapter/parser and adapter contracts.

**Audit caveat:** these are code-level coverage findings. No tests were executed as part of this read-only remote audit, so this document does not claim a fresh green test run.

## 4. Integration blockers (highest priority)

1. **Two separate market-data paths:** monitor reads directly from MT5 and CSV; market adapter/store are separate.
2. **No canonical runtime context:** no builder to assemble time-aligned, closed M1/M5 candles, tick/spread, session/time, source-health and evidence.
3. **Specialists are absent or disconnected:** technical engine is isolated; PA, macro, news, calendar and statistics engines are placeholders/prototypes.
4. **No evidence-first result contract across specialists:** output needs source IDs, timestamps, freshness, confidence/quality and invalidation.
5. **No fusion/risk state machine:** no transparent consensus/conflict logic, event/spread/session gates, or setup lifecycle.
6. **No outcome pipeline:** alerts are logged, but setups are not tracked to expiry/invalidation/TP/SL outcome for evaluation.
7. **No controlled research/learning loop:** no backtest/walk-forward, calibration, drift checks or human-approved parameter experiments.

## 5. Recommended build sequence

### Phase 0 — Audit and contracts
- Freeze this gap map.
- Define canonical time, candle, data-quality, evidence, specialist-output and failure contracts.
- Create a minimal testable runtime composition plan.

### Phase 1 — Market-data foundation integration
- Make `MarketDataStore` + `MT5MarketDataAdapter` the canonical runtime data path.
- Add runtime sync, explicit broker/symbol identity, closed-bar requirements, timestamp/freshness checks and data-health result.
- Introduce `MarketContextBuilder` that consumes stored candles and tick and produces a validated context snapshot.
- Preserve CSV as optional diagnostics only, not a parallel source of truth.
- Do not change strategy logic or enable signals.

### Phase 2 — Technical specialist
- Integrate the existing `TechnicalEngine` into context/runtime.
- Emit a versioned evidence-bearing specialist result with structure, confirmed pivots, protected levels, timestamp and quality.
- Add runtime integration tests.

### Phase 3 — Price Action setup lifecycle
- Implement deterministic Trend → Correction → Rejection → Pullback → Entry-state logic using the existing typed contracts.
- Define gap policy, expiry, invalidation, closed-bar/next-open semantics and state transitions before coding.
- Keep eligibility disabled until test/replay review.

### Phase 4 — Event/calendar and macro data
- Expand Source Registry adapter/provider coverage for approved free official sources.
- Add scheduling, freshness, timezone, normalization, provenance and graceful failure.
- Build calendar-risk and macro specialists; missing/stale inputs must not silently mean neutral.

### Phase 5 — News intelligence
- Free-source ingestion with deduplication, event timestamps, source credibility/provenance, currency/topic classification and EUR/USD relevance.
- Keep article text untrusted; no direct signal authority.

### Phase 6 — Statistical specialist
- Implement descriptive, testable volatility/regime/range/wave/retracement measures and evaluate each against chronological datasets.
- No predictive claims without out-of-sample validation.

### Phase 7 — Evidence fusion and risk gates
- Transparent specialist aggregation with disagreements visible.
- Deterministic session/spread/event/data-quality gates.
- WAIT by default. Alert-only. No orders.

### Phase 8 — Outcomes and performance
- Track each setup through invalidation/expiry and simulated outcomes.
- Record costs, spread assumptions, timestamps and strategy versions.
- Build metrics and reporting.

### Phase 9 — Research/backtesting
- Reproducible chronological replay, train/validation/test and walk-forward.
- Experiment registry, hypothesis checks, sensitivity, leakage safeguards.
- Human approval for any parameter changes.

### Phase 10 — Learning/briefing interface
- Calibrated evaluation and controlled memory updates.
- Health dashboard, evidence-linked daily briefing and reasons for WAIT.
- No automatic strategy mutation or trade execution.

## 6. Safety and engineering rules

- Alert-only; execution stays absent/disabled.
- WAIT is the default and missing data is never interpreted as neutral.
- LLM/RAG outputs may explain and contextualize but do not authorize a setup.
- Use closed candles for decisions and preserve strict chronological evaluation.
- Every conclusion must be traceable to evidence, timestamps, source and model/config version.
- Tests accompany each integration. No broad rewrites or unrelated changes.
- Use a branch and review before merging to `main`.

## 7. First implementation ticket

**Phase 1 / Ticket 1: MarketData runtime integration — no signal logic.**

Deliverables:
1. Runtime dependency wiring for store, adapter and context builder.
2. Safe sync cycle and failure status.
3. Context snapshot validation for M1/M5 and tick/spread.
4. Tests using fake MT5 connector and temporary SQLite DB.
5. Keep current decision engine returning WAIT.
6. No live provider fetch beyond MT5 and no execution functionality.

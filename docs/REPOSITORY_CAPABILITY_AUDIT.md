# Repository Capability Audit — 2026-11-19

## Scope and method

Audited the `main` branch at commit `ac2f42cd12d74b39d39cb4f9bafad88cb0658ea2`, including the repository tree (147 tracked files), `eurusd_ai_monitor/README.md`, runtime integration in `main.py`, representative engine implementations, learning/memory packages, configuration, knowledge-v2 integration notes, and Phase 13 architecture contracts.

This is a repository/code audit, not a claim of successful local runtime, broker connectivity, profitability, or complete external-source coverage. The open Phase 14 PR is tracked separately and is not part of this main-branch baseline.

## Executive finding

The repository is a useful alert-only monitoring and evidence/research foundation, but it is **not yet a comprehensive EURUSD AI**. The implementation is disproportionately mature in the technical/Price Action lifecycle and research integrity/observation path. Several domains central to a broad EURUSD intelligence system are still placeholders or disconnected.

The package README explicitly states:
- general fundamental analysis, statistical research, and learning modules remain scaffolds;
- actual vision-model interpretation is not connected;
- the full user Trend → Correction → Rejection → Pullback rules are not coded as a complete user strategy;
- BUY/SELL signal generation and order execution are disabled and the rules engine returns WAIT.

## Evidence-based inventory

| Capability | Observed repository evidence | Audit status |
|---|---|---|
| MT5 spot data | `mt5_engine.py`, `mt5_market_adapter.py`, `market_context_builder.py`, `market_data_store.py`; M1/M5 context | Implemented foundation; broader tick/history/replay coverage still needs audit |
| Technical analysis | `technical_engine.py`, tests and runtime integration | Implemented specialist foundation |
| Price Action | impulse/correction detectors, lifecycle state machine/coordinator/runtime, setup pattern engine | Relatively mature specialist; must remain one domain only |
| Market regime | `market_regime_engine.py` and tests | Implemented descriptive specialist |
| Macro calendar | `calendar_engine.py`, official-source adapters/config, SQLite store, tests | Calendar/event ingestion implemented; not full macro/fundamental interpretation |
| News ingestion | `news_engine.py`, source config, SQLite store, tests | Official RSS/Atom ingestion; context-only, not full semantic/news-impact intelligence |
| Fundamental intelligence | `fundamental_engine.py` contains only a placeholder docstring | Placeholder / absent implementation |
| General statistical intelligence | `statistical_engine.py` contains only a placeholder docstring | Placeholder / absent implementation |
| Outcome statistics | `statistical_outcome_evaluator.py`, regime-conditioned evaluator | Implemented descriptive MFE/MAE analysis; not a general quantitative research brain or realized trade performance |
| Fusion | `fusion_engine.py`, runtime integration | Implemented evidence fusion with bounded authority; not yet a full central intelligence orchestrator |
| Unified research synthesis | Phase 13 research engine/runtime/source envelopes | Implemented read-only synthesis of existing specialist outputs |
| Evidence lineage | Phase 14 PR #24, not in audited main | Proposed/open; awaiting local acceptance |
| Vision | `vision_engine.py` validates image presence/dimensions only; says vision analysis NOT_CONNECTED | Provider/model disconnected |
| Intermarket | No dedicated specialist/connector evident in audited engine/storage tree | Not implemented as a domain |
| Positioning/sentiment/options | No dedicated specialist/source/store evident in audited tree | Not implemented as a domain |
| Liquidity/microstructure | Spread is available from MT5 tick; no comprehensive depth/order-flow/liquidity specialist evident | Partial raw inputs; specialist absent |
| Learning | `feedback_engine.py`, `model_evaluator.py`, `performance_analyzer.py` are placeholders | Placeholder / no active learning |
| Memory | memory README says market_memory.db and trade_memory.db are not created; folders are placeholders | Not implemented |
| Knowledge/RAG | separate `knowledge_v2` package with Ollama/retrieval/ingestion; integration notes say add-on, not wired into v1 main | Exists separately; runtime integration and governance not complete |
| Source registry | separate `source_registry` package with adapters, schemas, manager, state DB and tests | Implemented foundation; integration into all domain pipelines must be assessed |
| Backtesting/replay | historical range retrieval and data folders exist; no comprehensive strategy/backtest/research harness is evident in audited tree | Major gap; must be designed and validated |
| Central intelligence | Phase 13 is deterministic read-only aggregation of Phase 6–12 payloads | Foundation only; no applicability-aware multi-domain reasoning/scenario brain |
| Decision/execution | legacy decision path and signal manager; README states WAIT-only and execution disabled | Safe alert-only boundary; do not enable as part of this roadmap |

## Runtime integration observations

`main.py` imports and orchestrates MT5, market context, technical, Price Action, macro calendar, news, Fusion, setup/session eligibility, outcome tracking, market regime, and research intelligence. The inspected runtime does not import or execute the fundamental/statistical placeholder modules, vision interpretation, learning placeholders, or knowledge-v2 RAG package.

The current Fusion specialists visible in the runtime include technical, Price Action, macro calendar, and news. Macro/news are explicitly context-only. Phase 13 consumes current specialist and historical descriptive outcome payloads; its contract explicitly says it is not a new directional specialist, backtest, optimizer, or learner.

## Architectural risks / gaps

1. **Domain imbalance:** Price Action lifecycle and its downstream setup/outcome workflow are much more developed than macro, quantitative, intermarket, sentiment, and liquidity intelligence.
2. **False completeness risk:** filenames for fundamental/statistical/vision/learning components exist but do not imply functional implementations.
3. **RAG isolation:** knowledge-v2 exists as a separate add-on; its notes explicitly say it is not integrated into v1 main.
4. **Research gap:** descriptive MFE/MAE cohorts are useful but are not a general backtesting, hypothesis-testing, model-training, or strategy-evaluation platform.
5. **Central brain gap:** current Phase 13 synthesis checks coherence/provenance/authority; it does not yet perform broad cross-domain scenario reasoning.
6. **Data breadth gap:** current runtime centers on broker M1/M5 spot candles plus calendar/news feeds. It does not yet demonstrate a point-in-time multi-asset macro/intermarket/positioning data plane.
7. **Operational evidence gap:** repository code and unit tests do not prove the local MT5-connected runtime or real-time external feeds are operational.

## Priority gap order

The next roadmap should not add more Price Action features by default. Recommended capability order:

1. Complete Gate 0 documentation and dependency/source inventory; keep Phase 14 PR #24 separately awaiting local tests.
2. Design the canonical point-in-time data plane and source registry integration so every specialist can consume consistent, provenance-rich observations.
3. Implement the missing **Quantitative/Statistical Intelligence** domain (general market statistics, not only setup MFE/MAE), because it unlocks objective measurement across every other specialist.
4. Implement full **Macro/Fundamental Intelligence** on top of the existing calendar/news source foundations.
5. Add **Intermarket Intelligence** with explicit instrument mapping, timestamp alignment, and empirical relationship validation.
6. Add **Liquidity/Microstructure** and **Positioning/Sentiment** only to the extent reliable, legally usable data is available; label proxies honestly.
7. Integrate knowledge/RAG as a cited research assistant, never a directional authority.
8. Build the next-generation central orchestrator only after specialist outputs are broad, typed, and evidence-grounded.
9. Build reproducible backtesting, walk-forward evaluation, learning, and controlled research promotion.
10. Only then consider a separate decision/risk validation program. Live execution remains disabled.

## Guardrails

- Do not change strategy parameters or claim profitability from descriptive MFE/MAE.
- Do not enable BUY/SELL or MT5 order placement.
- Do not mutate RAG/knowledge databases.
- Do not silently treat placeholder modules as available specialists.
- Do not make Price Action the default next phase merely because it is the most mature area.
- Every future phase must cite this audit and the Master Architecture, identify its North Star capability, and define end-to-end acceptance.

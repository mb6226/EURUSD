# Repository Capability Audit — 2026-11-19

## Scope and method

Audited the repository's main branch at pre-Phase-14 commit `ac2f42cd12d74b39d39cb4f9bafad88cb0658ea2`, including the repository tree (147 tracked files), package README, runtime integration in `main.py`, representative engines, learning/memory packages, configuration, knowledge-v2 integration notes, and Phase 13 contracts. Phase 14 was subsequently accepted locally (11 focused suites: 135/135; full suite: 351/351 on Python 3.14.10) and merged to main as `14d852577101640ce92206b310026ea1bf21b667`. The Phase 14 change adds evidence lineage; it does not change the domain capability findings below.

This is a repository/code audit, not proof of live broker connectivity, profitability, or complete external-source coverage.

## Executive finding

The repository is a useful alert-only monitoring and evidence/research foundation, but it is **not yet a comprehensive EURUSD AI**. Technical/Price Action lifecycle and research integrity/observation are more mature than several other domains. Multiple capabilities central to broad EURUSD intelligence remain placeholders, disconnected, or absent.

The package README's original scaffold statements predate Phases 18–22: deterministic quantitative market statistics, a policy-rate differential specialist, cross-Atlantic inflation/unemployment analysis, and an initial intermarket relationship specialist now exist. They remain bounded foundations rather than complete production domains. Actual vision-model interpretation is not connected; the complete user Trend → Correction → Rejection → Pullback strategy is not implemented; and BUY/SELL signal generation/order execution remain disabled with WAIT behavior.

## Evidence-based inventory

| Capability | Observed repository evidence | Audit status |
|---|---|---|
| MT5 spot data | `mt5_engine.py`, `mt5_market_adapter.py`, `market_context_builder.py`, `market_data_store.py`; M1/M5 context | Implemented foundation; broader tick/history/replay coverage still needs audit |
| Technical analysis | `technical_engine.py`, tests and runtime integration | Implemented specialist foundation |
| Price Action | impulse/correction detectors, lifecycle state machine/coordinator/runtime, setup pattern engine | Relatively mature specialist; one domain only |
| Market regime | `market_regime_engine.py` and tests | Implemented descriptive specialist |
| Macro calendar | `calendar_engine.py`, official-source adapters/config, SQLite store, tests | Calendar/event ingestion implemented; not full macro/fundamental interpretation |
| News ingestion | `news_engine.py`, source config, SQLite store, tests | Official RSS/Atom ingestion; context-only, not full semantic/news-impact intelligence |
| Fundamental intelligence | Phase 20 policy-rate differential specialist; Phase 21 BLS/Eurostat monthly CPI/HICP and unemployment products plus `MacroFundamentalsEngine` | Initial point-in-time specialist coverage implemented; no full release-surprise, growth, wage, fiscal, or policy-expectations model; not runtime-wired |
| General statistical intelligence | `quantitative_market_statistics_engine.py` (Phase 18) computes deterministic M1/M5 return, range, true-range and efficiency distributions; existing `statistical_outcome_evaluator.py` remains setup-MFE/MAE-only | Initial descriptive specialist implemented; event studies, wave/sequence statistics, conditional models and uncertainty research remain absent. Research synthesis accepts the specialist as optional; live runtime invocation is not yet wired |
| Outcome statistics | `statistical_outcome_evaluator.py`, regime-conditioned evaluator | Descriptive MFE/MAE only; not a general quantitative brain or realized trade performance |
| Fusion | `fusion_engine.py`, runtime integration | Evidence fusion with bounded authority; not a complete central intelligence orchestrator |
| Unified research synthesis | Phase 13 research engine/runtime/source envelopes | Read-only synthesis of existing specialist outputs |
| Evidence lineage | Phase 14 merged at `14d852577101640ce92206b310026ea1bf21b667` | Per-cycle M1/M5 candle-reference traceability and validation; not broader multi-source lineage for every future domain |
| Vision | `vision_engine.py` validates image presence/dimensions; vision analysis is NOT_CONNECTED | Provider/model disconnected |
| Intermarket | Phase 22 `IntermarketSeriesAdapter`, six logical products across FRED/ECB/LBMA/broker source families, and `IntermarketIntelligenceEngine` with exact-time return/change correlations and lead/lag diagnostics | Initial deterministic foundation implemented and tested with synthetic end-to-end ingestion; provider series IDs, legal availability, real data history, and runtime wiring remain unverified/unimplemented |
| Positioning/sentiment/options | Phase 23 CFTC TFF Futures-Only CME EURO FX adapter and PositioningSentimentIntelligenceEngine; Dealer, Asset Manager, Leveraged Money net positioning as % of open interest | Initial weekly futures-positioning proxy; no spot-wide positioning, options risk reversals, retail sentiment, or live provider/runtime wiring |
| Liquidity/microstructure | Phase 24 `LiquidityMicrostructureEngine` computes M1/M5 broker-feed spread (only when explicitly normalized), tick-activity, candle-range and body/range proxies from closed candles; optional Research Intelligence contract | Initial deterministic research foundation implemented; no Level 2/order-book provider, runtime wiring, automatic sampling, or consolidated FX liquidity claim |
| Learning | `feedback_engine.py`, `model_evaluator.py`, `performance_analyzer.py` are placeholders | Placeholder / no active learning |
| Memory | memory README says market_memory.db and trade_memory.db are not created; folders are placeholders | Not implemented |
| Knowledge/RAG | separate `knowledge_v2` package; integration notes say add-on, not wired into v1 main | Exists separately; runtime integration/governance incomplete |
| Source registry | `source_registry` package with validated registry, typed adapters, controlled ingestion, append-only point-in-time store, and Phase 20–23 policy/macro/intermarket/positioning products | Shared manual ingestion and as-of foundations integrated for these specialists; automatic provider operations remain disabled |
| Backtesting/replay | historical range retrieval and data folders exist; no comprehensive strategy/backtest/research harness evident in audited tree | Major gap |
| Central intelligence | Phase 13 deterministic read-only aggregation of Phase 6–12 payloads | Foundation only; no applicability-aware multi-domain scenario brain |
| Decision/execution | legacy decision path and signal manager; README says WAIT-only and execution disabled | Safe alert-only boundary; do not enable as part of this roadmap |

## Runtime integration observations

The inspected `main.py` orchestrates MT5, market context, technical, Price Action, macro calendar, news, Fusion, setup/session eligibility, outcome tracking, market regime, and research intelligence. The monitoring loop does not yet invoke the Phase 18 quantitative, Phase 20 policy differential, Phase 21 macro fundamentals, Phase 22 intermarket, Phase 23 positioning, or Phase 24 liquidity/microstructure specialists automatically. Vision interpretation, learning placeholders, and knowledge-v2 RAG also remain disconnected. These new specialists expose deterministic, testable contracts and source/store integration, but are not yet live runtime participants.

Current Fusion specialists include technical, Price Action, macro calendar, and news. Macro/news are context-only. The Phase 20–23 specialist outputs are not yet wired into Fusion or the monitoring runtime. Phase 13 synthesizes current specialist and historical descriptive outcome payloads; its contract says it is not a directional specialist, backtest, optimizer, or learner. Phase 14 adds evidence-lineage validation to the cycle, not missing specialist domains.

## Architectural risks / gaps

1. **Domain imbalance:** Price Action lifecycle and downstream setup/outcome workflow are more developed than macro, quantitative, intermarket, sentiment, and liquidity intelligence.
2. **False completeness risk:** the new quantitative, macro, and intermarket engines are bounded initial specialists; they do not imply complete domain coverage or operational provider connectivity.
3. **RAG isolation:** knowledge-v2 exists as a separate add-on; notes say it is not integrated into v1 main.
4. **Research gap:** descriptive MFE/MAE cohorts are not a general backtesting, hypothesis-testing, model-training, or strategy-evaluation platform.
5. **Central brain gap:** current Phase 13 synthesis checks coherence/provenance/authority; it does not yet perform broad cross-domain scenario reasoning.
6. **Data breadth gap:** the point-in-time store and logical macro/intermarket product contracts now exist, but no real multi-asset provider history or live operational data plane has been demonstrated; positioning/sentiment now has an initial CFTC futures-only proxy; options/retail sentiment and live provider coverage remain absent. Phase 24 adds broker-specific liquidity proxies only; no order-book depth or live runtime integration.
7. **Operational evidence gap:** repository code/unit tests do not prove local MT5-connected runtime or real-time external feeds are operational.

## Priority gap order

1. Maintain this product North Star, capability audit, dependency map, and source-of-truth register.
2. Design and implement the canonical point-in-time data plane and source-registry integration so every specialist consumes consistent, provenance-rich observations.
3. Extend Phase 18 quantitative foundations with event studies, wave/sequence statistics, conditional distributions and uncertainty estimates; connect the specialist to the monitoring runtime only after explicit data/freshness integration and acceptance.
4. Implement full **Macro/Fundamental Intelligence** using existing calendar/news foundations and additional reliable point-in-time sources.
5. Extend Phase 22 by verifying provider-specific series IDs, publication/availability metadata, licensing, calendar alignment, and real historical samples; then validate relationship stability and out-of-sample behavior before runtime wiring.
6. Extend Phase 23 with verified CFTC ingestion metadata and research validation; add options/retail sentiment only where reliable, legally usable data exists. Add **Liquidity/Microstructure** with the same source discipline.
7. Integrate knowledge/RAG as a cited research assistant, never a directional authority.
8. Build the next-generation central orchestrator after specialist outputs are broad, typed, and evidence-grounded.
9. Build reproducible backtesting, walk-forward evaluation, learning, and controlled research promotion.
10. Only then consider a separate decision/risk validation program. Live execution remains disabled.

## Guardrails

- Do not change strategy parameters or claim profitability from descriptive MFE/MAE.
- Do not enable BUY/SELL or MT5 order placement.
- Do not mutate RAG/knowledge databases.
- Do not silently treat placeholder modules as available specialists.
- Do not make Price Action the default next phase merely because it is the most mature area.
- Every future phase must cite the Master Architecture, identify its North Star capability, and define end-to-end acceptance.

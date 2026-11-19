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
| Fundamental intelligence | Phase 20 policy-rate differential; Phase 21 BLS/Eurostat CPI/HICP and unemployment; Phase 27 read-only runtime bridge | Initial point-in-time specialist coverage is runtime-wired to manually ingested observations; no full release-surprise, growth, wage, fiscal, or policy-expectations model; no automated provider population |
| General statistical intelligence | `quantitative_market_statistics_engine.py` (Phase 18) computes deterministic M1/M5 return, range, true-range and efficiency distributions; Phase 26 invokes it each cycle from the validated `MarketSnapshot`; existing `statistical_outcome_evaluator.py` remains setup-MFE/MAE-only | Initial descriptive specialist implemented and runtime-wired; event studies, wave/sequence statistics, conditional models and uncertainty research remain absent |
| Outcome statistics | `statistical_outcome_evaluator.py`, regime-conditioned evaluator | Descriptive MFE/MAE only; not a general quantitative brain or realized trade performance |
| Fusion | `fusion_engine.py`, runtime integration | Evidence fusion with bounded authority; not a complete central intelligence orchestrator |
| Unified research synthesis | Phase 13 research engine/runtime/source envelopes | Read-only synthesis of existing specialist outputs |
| Evidence lineage | Phase 14 merged at `14d852577101640ce92206b310026ea1bf21b667` | Per-cycle M1/M5 candle-reference traceability and validation; not broader multi-source lineage for every future domain |
| Vision | `vision_engine.py` validates image presence/dimensions; vision analysis is NOT_CONNECTED | Provider/model disconnected |
| Intermarket | Phase 22 six logical FRED/ECB/LBMA/broker products and exact-time correlation engine; Phase 27 read-only runtime bridge | Initial deterministic foundation is runtime-wired to manually ingested observations; provider series IDs, legal availability, and real data history remain unverified; descriptive analysis only |
| Positioning/sentiment/options | Phase 23 CFTC TFF Futures-Only CME EURO FX proxy; Phase 27 read-only runtime bridge | Initial weekly futures-positioning proxy is runtime-wired to manually ingested observations; no spot-wide positioning, options risk reversals, retail sentiment, or automated provider population |
| Liquidity/microstructure | Phase 24 `LiquidityMicrostructureEngine`; Phase 26 supplies current-cycle closed M1/M5 candles for tick-activity, candle-range and body/range proxies | Initial deterministic broker-feed proxy specialist is runtime-wired; per-candle spread remains unavailable until normalized historical spread observations are supplied; no Level 2/order-book provider or consolidated FX liquidity claim |
| Learning | `feedback_engine.py`, `model_evaluator.py`, `performance_analyzer.py` are placeholders | Placeholder / no active learning |
| Memory | memory README says market_memory.db and trade_memory.db are not created; folders are placeholders | Not implemented |
| Knowledge/RAG | separate `knowledge_v2` package; integration notes say add-on, not wired into v1 main | Exists separately; runtime integration/governance incomplete |
| Source registry | Validated registry, typed adapters, controlled ingestion, append-only point-in-time store, and Phase 27 batched read-only runtime access | Shared manual ingestion and as-of foundations are integrated for policy/macro/intermarket/positioning; automatic provider operations remain disabled |
| Backtesting/replay | historical range retrieval and data folders exist; no comprehensive strategy/backtest/research harness evident in audited tree | Major gap |
| Central intelligence | Phase 13 evidence/coherence synthesis; Phase 28 CentralScenarioIntelligenceEngine and live runtime adapter | First deterministic multi-domain scenario vertical slice is runtime-integrated; directional evidence is restricted to correlated price-derived sources; context domains remain non-voting; no probabilities, calibrated confidence, source reliability weights, scenario replay or causal model |
| Decision/execution | legacy decision path and signal manager; README says WAIT-only and execution disabled | Safe alert-only boundary; do not enable as part of this roadmap |

## Runtime integration observations

The monitoring loop orchestrates MT5, market context, technical, Price Action, macro calendar, news, Fusion, setup/session eligibility, outcome tracking, market regime, research intelligence, Phase 26 quantitative/liquidity specialists, and Phase 27 macro/policy/intermarket/positioning specialists. Phase 28 adds central scenario synthesis once per cycle and publishes three qualitative alternative hypotheses with evidence lineage, freshness/identity states and cross-domain tensions. Missing/stale/contradictory evidence remains explicit. Vision interpretation, learning placeholders, and knowledge-v2 RAG remain disconnected.

Current Fusion specialists include technical, Price Action, macro calendar, and news. Phases 26–27 add quantitative, liquidity, macro fundamentals, policy differential, intermarket, and positioning outputs to Research Intelligence only; they do not become Fusion directional votes. Phase 28 consumes these reports in a separate central scenario layer: only technical structure, confirmed Price Action lifecycle, and market-regime state describe direction, while the other domains remain context-only. Historical outcome statistics and setup/session gates do not vote.

## Architectural risks / gaps

1. **Domain imbalance:** Price Action lifecycle and downstream setup/outcome workflow are more developed than macro, quantitative, intermarket, sentiment, and liquidity intelligence.
2. **False completeness risk:** the new quantitative, macro, and intermarket engines are bounded initial specialists; they do not imply complete domain coverage or operational provider connectivity.
3. **RAG isolation:** knowledge-v2 exists as a separate add-on; notes say it is not integrated into v1 main.
4. **Research gap:** descriptive MFE/MAE cohorts are not a general backtesting, hypothesis-testing, model-training, or strategy-evaluation platform.
5. **Central brain gap:** Phase 28 adds the first deterministic live scenario-synthesis vertical slice, but calibrated uncertainty, demonstrated source-reliability weighting, applicability-aware specialist selection, causal cross-domain models, replay/backtesting and active learning remain absent.
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

## Post-Phase 24/25 source-contract clarification

Phase 24 is merged at `f2438f721385df09123f310ee61c9f0465a14737`. Phase 25 closes a specific contract omission: the research synthesis engine already classified liquidity/microstructure as an optional current-cycle source, but the canonical source-envelope builder did not list that source name. The envelope now preserves a supplied liquidity payload, its broker/symbol identity, and its own evaluation timestamp; missing input remains explicitly missing.

This was the Phase 25 state before Phase 26. At that point, the monitoring loop did not invoke the quantitative, macro-fundamental, policy-rate, intermarket, positioning, or liquidity specialists. Phase 26 subsequently connected quantitative statistics and liquidity proxies using only the current cycle snapshot. Macro-fundamental, policy-rate, intermarket, and positioning remain manual/explicit foundations, not live participants.


## Post-Phase 26 runtime integration

Phase 26 adds the first live multi-domain runtime vertical slice. The main monitoring loop now invokes the Phase 18 quantitative market-statistics engine and Phase 24 liquidity/microstructure engine on the current `MarketSnapshot`, then passes both reports through the Phase 25 canonical research source envelope and publishes them in the cycle payload. Each specialist is exception-isolated and fails closed independently.

This does **not** imply full liquidity measurement: per-candle spread remains unknown because the current tick spread is not historical per-candle evidence and raw broker `Candle.spread` is not normalized. The engine still reports available tick-activity and candle-range proxies when its sample/freshness requirements are met, with incomplete status where spread observations are absent.

Macro fundamentals, policy-rate differential, intermarket, and positioning remain explicit missing sources in the live research manifest. Their specialist inputs currently come from manually ingested point-in-time observation sets, and no validated runtime query/selection contract is present. Phase 26 adds no automatic fetching, no Fusion directional votes, no RAG mutation, no risk changes, and no execution authority. WAIT/alert-only behavior is preserved.


## Post-Phase 27 runtime integration

Phase 27 adds a read-only runtime bridge from the existing append-only point-in-time observation store to the Macro Fundamentals, Policy Rate Differential, Intermarket, and Positioning/Sentiment specialists. The bridge performs one batched as-of read per monitoring cycle and passes only observations whose effective, publication, and retrieval timestamps are no later than the cycle cutoff. It does not fetch, refresh, or persist external data.

The four specialist reports are included in the canonical research source envelope and are classified as optional current-cycle context. Missing/unconfigured observations remain explicit in the source manifest; partial coverage remains incomplete; stale or degraded evidence is not silently promoted. The specialists retain their assessment/context-only authority, and none becomes a Fusion directional vote. The observation database is opened read-only only when an existing, schema-valid database is present; the runtime does not create an empty operational database.

This phase does not establish that external data is populated, current, licensed, or operational. It does not add provider automation, RAG access, learning, backtesting, directional scenario synthesis, BUY/SELL behavior, risk changes, or order execution. The comprehensive central scenario brain remains a later capability.



## Post-Phase 29 — Historical central scenario replay

Phase 29 adds `HistoricalScenarioReplayEngine` and a read-only adapter for the existing monitoring JSONL archive. It evaluates archived Phase 28 central scenario reports against later closed M1/M5 candles at explicit bar-count horizons. Outputs include scenario classification accuracy, directional accuracy, confusion matrices, and descriptive forward movement.

The evaluator rejects unresolved/conflicted forecasts, invalid report identity/timestamps, missing anchors, insufficient future bars, discontinuous windows, and candle revisions detected after the scenario timestamp. The replay reads the existing market archive and revision history; it does not rewrite market data or source logs. The adapter consumes the actual central scenario object published by the existing SignalManager.

This is historical outcome evaluation of recorded scenario labels, not a reconstruction of historical central intelligence. It cannot prove all upstream specialist inputs were archived point-in-time. The current market store does not retain a complete queryable as-of version of every candle value; affected samples are conservatively excluded when later revisions are detected. Full candle version reconstruction, historical specialist report manifests, walk-forward partitions, calibration and uncertainty estimates remain open research gaps.

No probability calibration, source reliability weighting, learning, Fusion votes, strategy/risk changes, BUY/SELL enablement, or execution authority is introduced. Metrics are not trade profitability or realized P/L.


## Post-Phase 30 — Historical dataset integrity and chronological holdout

Phase 30 adds `HistoricalDatasetValidationEngine` for read-only integrity audits of broker-specific M1/M5 closed-candle archives. It reports wall-clock slot coverage, missing ranges (including leading/trailing intervals), duplicate/unaligned timestamps, revision watermark/scan completeness, and revision events. It degrades when gaps/revisions exist or the revision scan reaches its configured limit.

The same engine creates chronological train/validation/test partitions for timestamped scenario reports, with an outcome-horizon embargo that purges train and validation samples whose forward windows could cross the next partition boundary. It reports partition times/counts and source report indices; no random shuffle or model fitting is performed.

Limitations: wall-clock coverage is not session-calendar-aware; weekend/holiday/maintenance gaps are not distinguished from missing feed data. The market store still lacks a complete as-of candle-version reader, and the scenario archive/upstream specialist provenance need separate completeness audits. This is a single holdout split, not repeated rolling-origin walk-forward folds. No source fetching, data repair, DB mutation, calibration, learning, strategy/risk change, or order execution is introduced.


## Post-Phase 31 — Point-in-time multi-domain evidence reconstruction

Phase 31 adds `PointInTimeReconstructionEngine` plus a JSONL runtime adapter. It reconstructs broker-specific closed M1/M5 candles as-of a historical instant by reversing later revision deltas and requiring closed-bar availability evidence; reads source-registry observations with publication/retrieval/effective-time cutoffs; rolls back versioned news and macro-calendar event payloads; and reassesses archived specialist reports through the central scenario engine at each historical timestamp.

This is evidence reconstruction and archived-report reassessment, not historical specialist recomputation. The observation store only supplies products that were actually ingested. News unchanged refreshes lack complete append-only versioning and are excluded where prior availability cannot be proven. Candle closure is conservatively inferred from first/last-seen timestamps; dedicated closure events would be stronger. Macro calendar source-health state is mutable and not replayed. No live fetching, DB/log mutation, model training, calibration, source weighting, trading authority or order execution is added.

The reconstructed raw evidence is paired with, but not yet transformed into or injected as, central-engine specialist reports. Central reassessment consumes only archived report objects that pass point-in-time timestamp and identity checks; this phase does not add new directional votes from raw reconstructed observations.


## Post-Phase 32 — Deterministic historical specialist replay

Phase 32 adds DeterministicHistoricalSpecialistReplayEngine. It performs separate Phase 31 M1/M5 as-of reconstructions for each replay timestamp, creates a quality-gated historical MarketSnapshot, recomputes technical structure, market regime, quantitative market statistics and liquidity proxies, and can recompute macro fundamentals, policy differential, intermarket and positioning when all corresponding engines and a read-only point-in-time observation store are configured. It then reassesses the new reports through the central scenario engine.

The result is deliberately partial: Price Action lifecycle state is not replayed; news semantic impact and calendar impact models are not rerun; Fusion is not made a directional substitute. The current algorithm version is used, not a claim of exact historical code/model parity. A versioned algorithm/parameter registry, immutable feature snapshots, append-only lifecycle event replay, complete news fetch-version history and calendar source-health history remain prerequisites for full parity. No source DB, logs, knowledge store, configuration, lifecycle state, risk or execution control is mutated. No calibration, P&L or profitability claim is introduced.

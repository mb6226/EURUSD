# Repository Capability Audit — 2026-11-19

## Scope and method

Audited the repository's main branch at pre-Phase-14 commit `ac2f42cd12d74b39d39cb4f9bafad88cb0658ea2`, including the repository tree (147 tracked files), package README, runtime integration in `main.py`, representative engines, learning/memory packages, configuration, knowledge-v2 integration notes, and Phase 13 contracts. Phase 14 was subsequently accepted locally (11 focused suites: 135/135; full suite: 351/351 on Python 3.14.10) and merged to main as `14d852577101640ce92206b310026ea1bf21b667`. The Phase 14 change adds evidence lineage; it does not change the domain capability findings below.

This is a repository/code audit, not proof of live broker connectivity, profitability, or complete external-source coverage.

## Executive finding

The repository is a useful alert-only monitoring and evidence/research foundation, but it is **not yet a comprehensive EURUSD AI**. Technical/Price Action lifecycle and research integrity/observation are more mature than several other domains. Multiple capabilities central to broad EURUSD intelligence remain placeholders, disconnected, or absent.

The package README's original scaffold statements predate Phases 18–22: deterministic quantitative market statistics, a policy-rate differential specialist, cross-Atlantic inflation/unemployment analysis, and an initial intermarket relationship specialist now exist. They remain bounded foundations rather than complete production domains. Phase 34 now connects a local-only Qwen vision context specialist to MT5 M1/M5 screenshots; its observations are provenance-bound and non-voting. The complete user Trend → Correction → Rejection → Pullback strategy is still not implemented, and BUY/SELL signal generation/order execution remain disabled with WAIT behavior.

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
| Vision | Phase 34 local Ollama qwen2.5vl:7b adapter, screenshot SHA-256 provenance, async latest-frame runtime, optional context-only Fusion specialist | Live M1/M5 local inference verified; qualitative only, CPU-bound (~60–67s/image), not calibrated |
| Intermarket | Phase 22 six logical FRED/ECB/LBMA/broker products and exact-time correlation engine; Phase 27 read-only runtime bridge | Initial deterministic foundation is runtime-wired to manually ingested observations; provider series IDs, legal availability, and real data history remain unverified; descriptive analysis only |
| Positioning/sentiment/options | Phase 23 CFTC TFF Futures-Only CME EURO FX proxy; Phase 27 read-only runtime bridge | Initial weekly futures-positioning proxy is runtime-wired to manually ingested observations; no spot-wide positioning, options risk reversals, retail sentiment, or automated provider population |
| Liquidity/microstructure | Phase 24 `LiquidityMicrostructureEngine`; Phase 26 supplies current-cycle closed M1/M5 candles for tick-activity, candle-range and body/range proxies | Initial deterministic broker-feed proxy specialist is runtime-wired; per-candle spread remains unavailable until normalized historical spread observations are supplied; no Level 2/order-book provider or consolidated FX liquidity claim |
| Learning | `feedback_engine.py`, `model_evaluator.py`, `performance_analyzer.py` are placeholders | Placeholder / no active learning |
| Memory | memory README says market_memory.db and trade_memory.db are not created; folders are placeholders | Not implemented |
| Knowledge/RAG | separate `knowledge_v2` package; integration notes say add-on, not wired into v1 main | Exists separately; runtime integration/governance incomplete |
| Source registry | Validated registry, typed adapters, controlled ingestion, append-only point-in-time store, and Phase 27 batched read-only runtime access | Shared manual ingestion and as-of foundations are integrated for policy/macro/intermarket/positioning; automatic provider operations remain disabled |
| Backtesting/replay | Phases 29-32 add central scenario outcome replay, dataset integrity/chronological embargo, point-in-time evidence reconstruction and deterministic specialist re-execution | Scenario research foundation; no comprehensive strategy backtest or realized trading-performance harness |
| Central intelligence | Phase 13 evidence/coherence synthesis; Phase 28 CentralScenarioIntelligenceEngine and live runtime adapter | First deterministic multi-domain scenario vertical slice is runtime-integrated; directional evidence is restricted to correlated price-derived sources; context domains remain non-voting; scenario replay/reconstruction/specialist re-execution added in Phases 29-32; no probabilities, calibrated confidence, demonstrated source reliability weights or causal model |
| Decision/execution | legacy decision path and signal manager; README says WAIT-only and execution disabled | Safe alert-only boundary; do not enable as part of this roadmap |

## Runtime integration observations

The monitoring loop orchestrates MT5, market context, technical, Price Action, macro calendar, news, Fusion, setup/session eligibility, outcome tracking, market regime, research intelligence, Phase 26 quantitative/liquidity specialists, and Phase 27 macro/policy/intermarket/positioning specialists. Phase 28 adds central scenario synthesis once per cycle and publishes three qualitative alternative hypotheses with evidence lineage, freshness/identity states and cross-domain tensions. Phase 34 adds local-only M1/M5 visual inference as optional context-only Fusion evidence, including explicit disagreement flags. Missing/stale/contradictory evidence remains explicit. Learning placeholders and knowledge-v2 RAG remain disconnected.

Current required Fusion specialists include technical, Price Action, macro calendar, and news; Phase 34 adds visual as an optional context-only specialist. Phases 26–27 add quantitative, liquidity, macro fundamentals, policy differential, intermarket, and positioning outputs to Research Intelligence only; they do not become Fusion directional votes. Phase 28 consumes these reports in a separate central scenario layer: only technical structure, confirmed Price Action lifecycle, and market-regime state describe direction, while the other domains remain context-only. Historical outcome statistics and setup/session gates do not vote.

## Architectural risks / gaps

1. **Domain imbalance:** Price Action lifecycle and downstream setup/outcome workflow are more developed than macro, quantitative, intermarket, sentiment, and liquidity intelligence.
2. **False completeness risk:** the new quantitative, macro, and intermarket engines are bounded initial specialists; they do not imply complete domain coverage or operational provider connectivity.
3. **RAG isolation:** knowledge-v2 exists as a separate add-on; notes say it is not integrated into v1 main.
4. **Research gap:** descriptive MFE/MAE cohorts are not a general backtesting, hypothesis-testing, model-training, or strategy-evaluation platform.
5. **Central brain gap:** Phase 28 adds the first deterministic live scenario-synthesis vertical slice, but calibrated uncertainty, demonstrated source-reliability weighting, applicability-aware specialist selection, causal cross-domain models, replay/backtesting and active learning remain absent.
6. **Data breadth gap:** the point-in-time store and logical macro/intermarket product contracts now exist, but no real multi-asset provider history or live operational data plane has been demonstrated; positioning/sentiment now has an initial CFTC futures-only proxy; options/retail sentiment and live provider coverage remain absent. Phase 24 adds broker-specific liquidity proxies only; no order-book depth or live runtime integration.
7. **Operational evidence gap:** Phase 34 verifies this machine has a Headway MT5 connection, M1/M5 CSV/screenshot refresh and local Qwen vision path. This does not prove all external sources are current/reliable or that every domain has complete operational coverage.

## Priority gap order

1. Maintain this product North Star, capability audit, dependency map, and source-of-truth register.
2. Design and implement the canonical point-in-time data plane and source-registry integration so every specialist consumes consistent, provenance-rich observations.
3. Extend Phase 18 quantitative foundations with event studies, wave/sequence statistics, conditional distributions and uncertainty estimates; connect the specialist to the monitoring runtime only after explicit data/freshness integration and acceptance.
4. Implement full **Macro/Fundamental Intelligence** using existing calendar/news foundations and additional reliable point-in-time sources.
5. Extend Phase 22 by verifying provider-specific series IDs, publication/availability metadata, licensing, calendar alignment, and real historical samples; then validate relationship stability and out-of-sample behavior before runtime wiring.
6. Extend the verified CFTC positioning feed into research validation; complete source-specific BLS/FRED/ECB ingestion and attested public-availability replay; add options/retail sentiment only where reliable, legally usable data exists. Add **Liquidity/Microstructure** with the same source discipline.
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


## Post-Phase 33 ? Specialist execution provenance

Phase 33 adds per-specialist execution provenance to deterministic historical replay: canonical SHA-256 fingerprints for the reconstructed M1/M5 feature snapshot, the Phase 31 evidence bundle, the specialist report payload, and the engine source file when available. Reports also retain engine identity, declared algorithm/parameter versions, evaluation time and provenance scope. Identical replay inputs produce stable feature fingerprints; changed candle features produce different fingerprints.

These fingerprints improve auditability but are not a complete build/dependency manifest or historical algorithm registry. They do not recreate old code, parameter sets, runtime environments or raw fundamental observation snapshots. Exact historical parity remains a separate dependency. No data/RAG mutation, training, calibration, risk change or execution authority is introduced.

## Post-Phase 34 - Local visual evidence specialist

Phase 34 replaces the disconnected screenshot scaffold with a local-only Qwen2.5-VL adapter. The adapter accepts only loopback Ollama endpoints, fingerprints the exact analyzed screenshot, and runs asynchronously with latest-frame-wins scheduling. On this machine, M1 and M5 visual observations completed successfully at roughly 60-67 seconds per image.

Visual evidence is an optional context-only Fusion specialist. It cannot cast UP/DOWN votes or make missing required evidence appear complete. The current live smoke test observed DOWN on both chart timeframes while technical evidence disagreed; Fusion retained an explicit visual/technical disagreement flag. The decision remained WAIT with execution disabled. This single live observation is not model validation or a forecast-performance claim.

Phase 34 also pins the explicit Headway terminal path, records screenshot capture provenance/quality metadata, handles screenshot overwrite races, and keeps visual analysis outside the market polling thread. The runtime currently uses the Starter v1 Python virtual environment because it contains MetaTrader5/pandas; a dedicated environment for the advanced repository remains cleanup. No RAG/knowledge database or risk configuration was changed.

## Next strategic priority after Phase 34

Return to the central intelligence research loop rather than adding more isolated specialists: run point-in-time historical replay of central scenarios across complete available multi-domain evidence, produce measurable out-of-sample scenario/forecast evaluation, then calibrate uncertainty only from those out-of-sample results. Keep descriptive market observations separate from trading performance and preserve the no-lookahead and execution boundaries.


## Phase 36 — Multi-domain point-in-time data-plane status

Implemented locally: `source_registry/data_plane.py` provides a validated-registry-driven, read-only request map and one batched as-of read across five domains (monetary policy, macro fundamentals, intermarket, positioning/sentiment, and spot FX). It returns per-product/domain availability and explicit missing coverage; disabled sources are excluded. A missing PIT DB is not created. Tests cover domain grouping, as-of gating, disabled products, missing DB behavior, and read-only enforcement.

Observed repository state at implementation start: 9 registered sources / 17 products; all enabled, all with `auto_fetch=false`; no configured `source_registry/operational/observations.sqlite` or `state.db`. Existing market, calendar, and news stores are separate. Thus the new data plane is connected to the canonical registry/store contract but the macro/intermarket/positioning observation history remains unpopulated. No external acquisition or refresh was started. Source acquisition/activation requires separate explicit approval.


## Phase 37 — Controlled source acquisition readiness

Added a no-network, registry-driven acquisition plan and append-only raw payload archive. The plan covers 9 sources / 17 products and identifies source-specific PIT requirements and limitations. The raw archive preserves exact HTTPS payload bytes, retrieval timestamp, headers, request metadata and SHA-256 before normalization; it rejects non-allowlisted products, unsuccessful HTTP responses and unsafe payloads, redacts credential-like fields, and prevents UPDATE/DELETE.

No provider fetch was performed and no live raw or normalized database was created. Reasons are source-specific, not generic: Eurostat has latest-version-only API behavior; FRED needs a key and ALFRED vintage dates are date-grained; BLS requires release-calendar joins and original release snapshots; CFTC requires current schedule/cadence validation; LBMA requires rights review; broker spot needs a durable local history. Historical point-in-time availability must be reported honestly per product.


## Phase 37B — First official provider ingestion status

Implemented local provider adapters for BLS CPI-U and CFTC TFF Futures-Only EURO FX. CFTC acquisition is operational: 51 report rows, 51/51 official publication-time joins, and 153 normalized positioning observations across Dealer, Asset Manager and Leveraged Money products. Raw payloads and official release evidence are preserved in the append-only archive. The 2025 CFTC catch-up schedule is handled separately from the 2026 regular calendar; the planned semiweekly transition is not assumed active merely because it was announced.

BLS API payloads are archived, but the local BLS calendar/archive endpoints returned HTTP 403; no CPI observations were persisted. FRED remains credential-gated (no key read), ECB SDMX flow/key resolution remains open, Eurostat is latest-version-only, LBMA requires licensing review, and durable broker spot history remains absent.

Historical PIT caveat: the CFTC source publication timestamps are verified, but local retrieval occurred later. Existing get_as_of semantics require retrieval time as well as publication time to precede the cutoff. A separate attested public-source-availability replay mode is required before these backfilled records can be used at historical cutoffs. The existing system-knowledge cutoff must not be weakened.

Raw archive currently: 30 snapshots / 3,013,170 bytes. Normalized observation store: 153 observations. Registry auto_fetch remains false; monitor was not restarted; Vision remains disabled; no trading, risk, RAG, or execution behavior changed.

## Phase 37C ? Historical availability replay boundary

- Implemented a separate immutable attestation ledger and public-availability read API. Strict system-knowledge reads are unchanged.
- No production observation was attested in this phase: CFTC publication mapping exists, but historical as-released value-vintage proof remains outstanding; BLS acquisition was incomplete; other sources are unverified.
- No source fetching, activation, monitor restart, risk/order changes, or RAG mutation.

## Phase 37D ? Official provider expansion

- Added FRED/ALFRED and ECB SDMX historical-version providers with immutable raw response archival. Updated BLS CPI endpoint to official API v2 and canonical BLS hosts.
- FRED API key is an explicit constructor argument only; no environment lookup. ECB exact flow/key must be supplied by caller.
- FRED date-level vintages and ECB historical revisions are not falsely represented as intraday PIT publication timestamps. No new production observations or external requests were made.


## Phase 37E ? Durable spot history

The MT5 connector already supports read-only UTC range retrieval, and the market store already supports resumable chunk checkpoints plus correction records. Phase 37E adds schema-v4 immutable ingestion-run and candle-version ledgers, normalized-batch SHA-256, and MT5 method/time/chart-basis provenance. If connector symbol metadata is unavailable, price basis is UNKNOWN rather than guessed. Existing pre-v4 rows are not assigned fabricated provenance. The production market DB was inspected read-only (776 candle projections, 0 corrections, 0 backfill checkpoints at inspection); no historical range request or live DB migration was performed while the monitor was running. Therefore, durable one-year spot-history coverage is still NOT VERIFIED.


## Phase 37F ? Multi-domain data coverage

FRED/ALFRED product support now explicitly maps nine daily reference products: DGS2, DGS10, DFII10, DTWEXBGS, SP500, VIXCLS, DCOILWTICO, DCOILBRENTEU and DEXUSEU. ALFRED vintage intervals are retained, but they do not provide verified intraday publication times. A registry-only coverage report maps 23 products across 9 of 11 required intelligence domains; news/geopolitics and options/cross-currency remain unregistered. Precious metals and USD benchmarks are not falsely represented as fully sourced: LBMA gold and ICE DXY access/licensing remain unresolved, while DTWEXBGS is a broad trade-weighted USD basket. No live availability is inferred from registration.


## Phase 37G ? Data quality and revision control

`source_registry/data_quality.py` provides deterministic read-only per-product quality diagnostics for PIT-eligible rows. It validates declared units, finite scalar/range values, required timestamp semantics and chronology, future evidence, duplicate identity and freshness. Freshness thresholds are operational defaults by registry frequency, not calibrated economic limits. `PointInTimeObservationStore.get_revision_history` exposes append-only versions under optional strict as-of filters. The quality report is not yet connected to Fusion; it cannot alter or repair observations.


## Phase 38 ? Unified Historical Data Plane

`PointInTimeDataPlane.read_unified_as_of(as_of_utc)` now returns one strict system-knowledge snapshot across enabled Registry products. It preserves strict-read observations in `evidence_domains` and separately exposes `analytics_domains`, which only contains observations from products that pass Phase 37G quality assessment. Revision summaries and deterministic snapshot hashes are included. Public-availability reconstruction remains separate and attestation-dependent. The live Fusion path is not yet wired to this gate; historical coverage is not implied by the unified interface.


Spot history is integrated as a separate read-only source in the unified plane. The current production market archive is schema v3 with 1,047 legacy candles across Headway-Real EURUSD M1/M5 but no Phase37E candle-version ledger. These rows are explicitly `PROVENANCE_UNAVAILABLE` and are not exposed as PIT analytics. No migration was run.


## Phase 39 — Multi-domain market-regime intelligence

Added `eurusd_ai_monitor.engines.multidomain_market_regime_engine.MultiDomainMarketRegimeEngine` over the Phase 38 unified strict PIT snapshot. It requires quality-eligible closed/versioned EURUSD M5 candles with valid OHLC and strict cutoff timestamps, with a minimum 65-bar window. It reports descriptive structure and volatility dimensions separately from macro, monetary-policy, intermarket and positioning coverage. Missing domains remain explicit; CFTC positioning-only evidence returns `INSUFFICIENT_EVIDENCE / UNKNOWN` rather than a fabricated market regime. The existing Phase 11 live M1/M5 specialist is preserved and not silently replaced. Offline regression tests cover trend/range, partial coverage, positioning-only insufficiency, short history, future timestamps and invalid as-of values. No live Fusion/order wiring, network acquisition, provider activation, DB migration, monitor restart, risk change or RAG mutation.


## Phase 40 — Statistical & quantitative intelligence

Added `eurusd_ai_monitor.engines.point_in_time_quantitative_statistics_engine.PointInTimeQuantitativeStatisticsEngine`, consuming only strict Phase 38 PIT snapshots and PASS/analytics-eligible EURUSD M1/M5 spot streams. It independently validates cutoff timestamps, closed candles, source/provenance, price/time basis, OHLC bounds, version IDs and contiguous cadence. Descriptive outputs include close-to-close pip-return distributions, empirical quantiles, realized volatility, semi-deviation, empirical sample VaR/expected shortfall, close-to-close drawdown, true-range statistics and return dependence measures. Missing streams are not imputed; M1/M5 are not pooled. Existing live quantitative and MFE/MAE specialists remain separate. Current v3 spot archive is quarantined and CFTC is not used as a substitute price series; production output remains insufficient evidence. Regression coverage in `tests/test_point_in_time_quantitative_statistics_engine.py`. No live Fusion/order wiring, acquisition, provider activation, DB migration, monitor restart, risk changes or RAG mutation.


## Phase 41 — Session & Time Intelligence

Added `eurusd_ai_monitor.engines.session_time_intelligence_engine.SessionTimeIntelligenceEngine` over strict Phase 38 snapshots. It provides DST-aware local session clocks for Sydney/Tokyo/London/New York, reference-window overlap labels, and quality-gated descriptive M1/M5 session coverage. Optional calendar events are accepted only with exact scheduled time plus publication/retrieval timestamps visible by the strict cutoff; date-only and cancelled/unverified records are not assigned invented intraday times. The engine explicitly avoids claiming broker open/close schedules or session alpha. Current schema-v3 legacy spot archive remains ineligible, so production historical coverage is insufficient. Tests are in `tests/test_session_time_intelligence_engine.py`. No network acquisition, DB migration/mutation, monitor restart, Fusion wiring, risk change, RAG mutation or order execution.


## Phase 42 ? Cross-Domain Relationship Engine

- Strict point-in-time relationship analysis over Phase 38 unified snapshots; consumes only quality-eligible cross-domain products.
- Exact UTC timestamp alignment; unit-aware percent, basis-point, and percentage-point changes; bounded Pearson association with explicit sample counts and evidence hashes.
- No interpolation/forward-fill, causality claims, forecasts, directional votes, trading authority, or automatic acquisition.
- Current production coverage: three eligible CFTC positioning series within one domain, no eligible cross-domain pairs; status `INSUFFICIENT_EVIDENCE`.
- Existing Intermarket specialist remains separate; no Fusion wiring in Phase 42.


## Phase 43 ? Central Multi-Domain Scenario Intelligence

- Central scenario engine upgraded to v1.1.0; accepts Phase39?42 PIT reports or derives them from one strict unified historical snapshot.
- New dependency map explicitly groups shared broker-price, CFTC, intermarket, macro/policy/calendar, news, and outcome-research lineage; no correlated views count as independent votes.
- PIT regime/statistics, session/time and cross-domain relationships remain context-only; missing and insufficient evidence remain visible.
- Scenario hypotheses are qualitative and conditional; numeric probability and calibrated confidence remain unavailable pending out-of-sample validation.
- Production orchestration check: PARTIAL data plane, four PIT specialists INSUFFICIENT_EVIDENCE, UNRESOLVED direction, LIMITED coverage.
- No active monitor rewiring, execution/risk changes, provider activation, DB migration, or commit/merge.


## Phase 44 — Multi-Horizon Forecasting

Added `MultiHorizonForecastingEngine` and a thin runtime wrapper. The engine consumes one strict Phase 38 PIT snapshot and emits separate 15-minute, 1-hour and 4-hour baseline forecasts from a verified closed EURUSD M5 series. It validates source identity, BID/LAST basis, UTC time basis, version IDs, OHLC integrity, contiguous cadence, observed/as-of cutoffs and a maximum 15-minute age for the latest closed bar. Expected movement uses the latest 12-bar median return; descriptive dispersion scales with square root of horizon. Phase 43 central scenario state and cross-domain coverage are attached for comparison only and cannot override the baseline. Numeric probabilities and calibrated confidence remain null; dispersion bands are explicitly not calibrated intervals. Missing or reconstructed evidence fails closed. Tests are in `tests/test_multi_horizon_forecasting_engine.py`. Current legacy schema-v3 spot history is not eligible, so production forecasts remain insufficient evidence. No live monitor wiring/restart, DB migration/write, provider activation, risk/order change or RAG mutation.


## Phase 45 — Point-in-Time Historical Forecast Replay

Added a strict system-knowledge replay engine that calls the Phase 44 forecast engine unchanged at historical cutoffs. The market archive must be opened read-only and expose the schema-v4 immutable candle-version ledger. Forecast snapshots include only closed M5 versions whose observed_at and as_of timestamps are both no later than the forecast cutoff; cutoffs are never backdated to candle time. A version-history reader was added to MarketDataStore for bounded, read-only access. Replay selects first observed closed candle cutoffs, uses an incremental event timeline, preserves later corrections without rewriting prior snapshots, requires consistent verified BID/LAST price basis, and resolves outcomes from the first verified closed target version after target close. Snapshot hashes bind exact visible versions; deterministic replay IDs bind the source-history hash and replay parameters. A separate append-only research SQLite ledger stores completed runs and per-horizon outcomes; it does not write to the production market archive. Tests cover future-data exclusion, later corrections, deterministic identity, delayed outcomes, read-only enforcement, schema-v3 fail-closed behavior and append-only persistence. Production preflight remains BLOCKED because the live archive is schema v3 with 1,132 legacy candles and no version ledger; no migration/backfill was performed. No provider activation, network acquisition, monitor restart, risk/order change, RAG mutation or commit/merge.


## Phase 46 — Scenario Evaluation Framework

Implemented `eurusd_ai_monitor.engines.scenario_evaluation_engine.ScenarioEvaluationEngine` as a strict categorical evaluator for Phase43 central scenarios. A score requires a contemporaneous archive envelope with canonical report SHA-256 and availability timestamp no later than issue time; exact broker/symbol/issue-cutoff/horizon matching; exactly one leading hypothesis; and an issuance-time scenario_evaluation_spec containing an explicit horizon, supported closed-bar outcome classifier and invalidation-rules version. Outcome evidence must independently provide exact window boundaries, closed-bar classification, UTC bar-time basis, known price basis, source candle-version IDs, evidence SHA-256 and observed/as-of timestamps no later than the evaluation cutoff. Rejected records retain explicit reason codes. There is no implicit horizon, nearest-time join, reconstruction, probability, confidence calibration, or trading-performance claim. Phase43 currently does not emit the required scenario_evaluation_spec and no verified contemporaneous scenario archive is configured, so production status is NO_ARCHIVED_SCENARIOS with zero scores. Phase45's numeric baseline replay remains a separate stream and is independently blocked by the production schema-v3 archive lacking immutable candle versions. Eleven focused tests cover the archive/hash, exact horizon, cutoff, identity, evidence and no-data controls. No live monitor/archive wiring, DB mutation/migration, provider activation, risk/order change, RAG mutation or commit/merge.


## Phase 47 — Forecast Error Analysis

Added `eurusd_ai_monitor.engines.forecast_error_analysis_engine.ForecastErrorAnalysisEngine`, a descriptive diagnostic layer over completed Phase45 strict system-knowledge replay reports. It requires COMPLETE status, EURUSD M5 identity, and all six replay integrity flags. It scores 15M, 1H and 4H independently and reports directional accuracy including neutral and non-neutral-only, confusion matrices, MAE, RMSE, signed bias (actual minus forecast), median/P90/P95 absolute error, realized/forecast movement magnitude, direction-conditioned error and forecast-dispersion terciles. Missing outcomes are counted, not imputed; duplicate forecast IDs, unsupported horizons and invalid/non-finite records are excluded with explicit reason codes. Dispersion terciles are not market regimes. Regime attribution is unavailable because Phase45 does not store a contemporaneous Phase39 regime label; causal feature attribution is likewise not claimed. No probability/calibration metrics are produced. The production replay is still blocked by the schema-v3 spot archive lacking an immutable candle-version ledger, so Phase47 reports no production error metrics. Synthetic fixtures validate calculations only. No model tuning, live forecast changes, monitor restart, DB mutation, provider activation, risk/order change, RAG mutation or commit/merge.


## Phase 48 — Uncertainty Calibration

- Introduces chronological split-calibration of Phase44 descriptive interval widths using only completed Phase45 strict PIT replay records and all six replay integrity flags.
- Per-horizon calibration (15M/1H/4H) uses earlier outcomes to estimate finite-sample normalized-absolute-error multipliers and a later untouched holdout to measure empirical coverage and interval width at 80%, 90% and 95% target levels.
- Default readiness gates: 50 calibration outcomes and 30 later holdout outcomes per horizon. No cross-horizon pooling, probability/confidence synthesis, live application, or Gaussian coverage assumption.
- Production remains BLOCKED until Phase45 has a complete versioned-candle replay; no synthetic production metrics are emitted.


## Phase 49 — Walk-Forward Validation

- Adds sequential out-of-sample evaluation for the fixed Phase44 baseline, separately across 15M, 1H and 4H horizons.
- Uses non-overlapping chronological test folds and rolling past-only training sets. Training labels are purged unless their target candle has closed by the test fold's first forecast cutoff.
- Fold-local interval multipliers are fitted only on training residuals and scored only on later holdout records; reports fold and aggregate descriptive error, directional and interval metrics.
- Requires a COMPLETE Phase45 strict PIT replay, all six integrity flags, immutable forecast/target provenance, at least 100 training outcomes, 30 test outcomes per fold and two folds by default.
- Production validation is BLOCKED while the Phase45 candle-version ledger is unavailable. No model tuning, live deployment or synthetic production metrics.


## Phase 50 — Cross-Domain Attribution

- Adds point-in-time, per-horizon conditional attribution of out-of-sample forecast errors across ten EURUSD information domains.
- Requires contemporaneous domain states bound to the exact forecast snapshot, with independent context hashes, evidence lineage and timestamps no later than forecast cutoff; rejects lookahead and unverified context.
- Reports state-stratified MAE/RMSE/bias/directional agreement versus horizon baseline; state groups below 30 samples remain unscored. No imputation or horizon pooling.
- Shared data lineage prevents price-derived, macro/policy and derived relationship views from being counted as independent confirmations. No causal attribution, feature importance or incremental predictive contribution claims.
- Production BLOCKED until Phase45 replay is complete and historical domain context is archived; no synthetic production metrics.


## Phase 51 — Continuous Learning & Research

- Controlled research-cycle governance binds Phase45 replay, Phase49 walk-forward and Phase50 attribution to the same replay ID and source-history hash and requires all strict PIT replay integrity flags.
- Per-horizon research gates require at least two OOS folds, 100 completed outcomes and contemporaneous attribution. Readiness is for research review only; automatic training, tuning, promotion and live model changes remain disabled.
- Versioned experiment manifests pin code/parameter/source/replay hashes. A separate append-only SQLite ledger records experiment, evaluation and human review events with immutable triggers and replay/source matching.
- Production currently BLOCKED by missing immutable candle versions and no historical contemporaneous domain context. No research ledger is created from blocked preflight.

## Market archive migration hardening

- New explicit schema-v3 to v4 migration script defaults to read-only preflight. Apply mode backs up and verifies the SQLite database, migrates atomically under an exclusive writer lock and checks unchanged legacy rows.
- Legacy candles remain unversioned; no retrospective provenance or replay eligibility is fabricated. Versioned historical replay becomes possible only after the v4 ingestion process is running and newly observed versions are recorded.


### Operational update after Phase51

The previously observed schema-v3 market archive has now been backed up and migrated to schema v4 under a controlled monitor stop. The v3 backup passes integrity checks. Legacy rows remain unversioned; new v4 MT5 ingestion is active and has produced verified M1/M5 candle versions with source provenance. Historical replay is now able to generate forecasts from versioned inputs, but target outcomes have not yet matured for scored OOS validation.

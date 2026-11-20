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


## Phase 28 — First central scenario-synthesis vertical slice

Phase 28 introduces a deterministic CentralScenarioIntelligenceEngine in the live cycle. It evaluates technical structure, confirmed Price Action lifecycle and market-regime state for directional consistency, then combines macro fundamentals, policy differential, intermarket, positioning, quantitative statistics, liquidity, calendar/news, setup/session gates and historical descriptive outcomes as contextual evidence. It emits up-continuation, down-continuation and range/transition hypotheses with supporting/opposing evidence references, source freshness/identity states and explicit cross-domain tensions.

This is deliberately not a weighted majority vote. The three price-derived inputs share underlying broker price data and are treated as correlated consistency checks. Context-only domains do not cast directional votes. Conflicting direction or trend-versus-range evidence remains unresolved. The engine emits no numeric probability or calibrated confidence and has no trade authority.

Phase 28 is a first vertical slice, not the full Gate 3 exit. Phase 29 adds read-only replay of archived central scenario reports against later closed candles, with explicit horizons, classification accuracy, confusion matrices, archive ingestion and conservative revision-leakage exclusions. It does not reconstruct historical specialist state or calibrate probabilities. Calibrated uncertainty, demonstrated source-reliability weighting, causal cross-domain models, full as-of candle-version reconstruction, applicability learning and broader provider coverage remain future gaps.


## Phase 30 — Historical dataset integrity and walk-forward partitions

Phase 30 adds a read-only audit of the existing M1/M5 candle archive: expected wall-clock bar slots, observed closed bars, coverage, missing intervals, timestamp integrity, revision watermark/completeness and revised-candle counts. It also provides deterministic chronological train/validation/test partitioning with a forward-horizon embargo at partition boundaries. This is a single chronological holdout, not repeated rolling folds.

The audit does not distinguish FX market closures from data outages, does not mutate/backfill the store, and cannot reconstruct complete first-seen candle versions. Scenario archive coverage and point-in-time provenance of all multi-domain specialist inputs remain separate requirements. Full as-of reconstruction, scenario archive manifests, rolling-origin folds, regime-stratified evaluation and calibrated uncertainty remain future gaps.


## Phase 31 — Point-in-time evidence reconstruction and multi-domain replay

Phase 31 adds a read-only reconstruction engine for four evidence families at an explicit historical UTC timestamp: broker-specific M1/M5 candles (including reversal of later candle revisions and conservative closed-bar availability checks), append-only source-registry observations (effective/published/retrieved as-of filtering), news semantic versions (revision rollback with conservative exclusion where unchanged refresh history is unprovable), and macro calendar event versions (revision rollback bounded by immutable first-seen time).

The replay adapter consumes archived specialist reports from historical monitor JSONL cycles, reconstructs the evidence bundle independently at each original timestamp, rejects future/mismatched specialist reports, and reassesses archived reports through the central scenario engine. It does not recompute specialist algorithms from raw historical inputs. Missing reports and unprovable evidence remain explicit. Full historical specialist recomputation, complete news fetch-version history, explicit candle-closure event history, calendar source-health history, and source coverage manifests remain future capabilities.

The replay returns reconstructed raw evidence alongside central reassessment; raw observations are not yet transformed into specialist reports or injected as new votes. The central engine consumes only archived specialist report objects that pass timestamp and identity checks.


## Phase 32 — Deterministic historical specialist re-execution

Phase 32 extends Phase 31 reconstruction into a bounded deterministic replay loop. At each archived evaluation timestamp it independently reconstructs M1 and M5 candles, builds a historical MarketSnapshot, re-executes technical structure, market regime, quantitative statistics and liquidity proxies, and conditionally re-executes macro fundamentals, policy differential, intermarket and positioning specialists when their engines and read-only point-in-time observation store are supplied. Newly computed reports are passed to the central scenario engine; reconstructed news/calendar availability is retained as context.

This is a meaningful first recomputation slice, not full domain parity. Price Action lifecycle remains un-replayed because its current coordinator is stateful; news semantic and calendar impact specialists lack pinned historical model/feature versions; Fusion is not substituted as a directional authority. The replay reports these gaps explicitly and never falls back to archived future reports. It uses the currently injected algorithm versions rather than claiming exact historical code-version parity. Exact parity requires an immutable algorithm/parameter registry, feature snapshots, and isolated lifecycle event replay.

No data stores, monitor logs, RAG/knowledge stores, strategy configuration, lifecycle state, risk settings or execution controls are mutated. No probabilities, trading P&L or profitability claims are produced. See phase32_deterministic_historical_specialist_replay.md.


## Phase 33 ? Immutable specialist execution provenance

Phase 33 extends deterministic historical specialist replay with canonical SHA-256 fingerprints for the exact reconstructed M1/M5 feature snapshot, the Phase 31 reconstructed evidence bundle, each specialist report payload, and each specialist engine source file when locally available. Per-report provenance records also retain the declared algorithm/parameter versions, engine module/class, as-of timestamp, provenance scope and explicit non-claim of historical version parity.

These fingerprints make repeated replay outputs auditable and allow a changed feature snapshot, report or engine source file to be distinguished. They do not constitute a transitive build manifest, immutable raw observation snapshot, historical algorithm registry, or executable historical environment. Exact historical code/parameter parity and complete fundamental input reconstruction remain future dependencies. No database, source archive, RAG store, strategy configuration, lifecycle state, risk setting or execution control is mutated.

## Phase 34 - Local-only visual evidence specialist

Phase 34 connects the MT5 M1/M5 screenshot stream to a local Qwen2.5-VL model through a loopback-only Ollama adapter. Screenshot evidence carries capture time, dimensions, quality metadata, SHA-256 and a stable evidence ID. Inference runs asynchronously with latest-frame-wins scheduling, per-timeframe throttling, freshness expiry and screenshot-overwrite retry handling.

Visual output is an optional context-only Fusion specialist. It cannot cast directional votes or replace missing required evidence. The central evidence ledger retains observed timeframe direction/quality and explicit disagreement flags against technical/Price Action evidence. The model's qualitative output is not calibrated, and a recent-frame result is explicitly distinguished from an exact current-image match. Live order execution and the legacy WAIT decision boundary remain unchanged.

The local Qwen2.5-VL 7B model completed M1/M5 smoke-test analyses on 2026-11-19 at roughly 60-67 seconds per image. Vision inference was subsequently disabled in the operational config to preserve CPU capacity; no image processing is part of the current monitor cycle.

## Phase 35 — Official calendar feed identity and timezone hardening

Phase 35 hardens official macro-calendar normalization after runtime source-state inspection exposed a legacy `US-Eastern` iCalendar TZID and month-level event identity collisions in ECB/FOMC parsers. The parser now converts the observed legacy TZID through the explicit `America/New_York` alias while preserving the original label, and ECB/FOMC event IDs include exact scheduled dates. Regression tests cover the timezone alias and unique event identities. Calendar tests and the full 582-test suite pass. No external refresh was forced; the running monitor's in-memory parser remains unchanged until a controlled restart. See `phase35_official_calendar_feed_hardening.md`.

## Next strategic priority after Phase 35

Prioritize historical validation of central scenarios: point-in-time replay using complete available multi-domain evidence, measurable out-of-sample scenario/forecast evaluation, then uncertainty calibration from out-of-sample results. Do not substitute more isolated specialists, chart patterns or a single-domain strategy for this research sequence.


## Phase 36 — Registry-driven multi-domain point-in-time data plane

Phase 36 adds `source_registry.data_plane.PointInTimeDataPlane`, a shared read-only boundary that derives all enabled source/product requests from the validated registry, groups them into monetary policy, macro fundamentals, intermarket, positioning/sentiment, and spot-FX domains, and performs one batched strict as-of observation read. Its report exposes per-product and per-domain coverage, missing products, eligible observation counts, and a product-coverage ratio. It can open only an existing schema-valid observation database in read-only mode; a missing database remains unavailable and is never initialized as a side effect.

The current registry has 9 sources and 17 products, with every source enabled but `auto_fetch=false`. At Phase 36 implementation time, the configured point-in-time observation database and source-state database were absent. Existing market-candle, macro-calendar, and news databases remain separate and were not migrated. Consequently, Phase 36 establishes the common registry-driven read contract and explicit coverage reporting; it does not claim populated historical macro/intermarket/positioning data.

The data plane does not fetch, schedule, persist, mutate registry/source state, or alter specialist votes. Explicit ingestion remains a separate caller-controlled operation. See `phase36_multidomain_point_in_time_data_plane.md`.


## Phase 37 — Controlled multi-domain acquisition foundation

Phase 37 adds `source_registry.acquisition_plan` and `source_registry.raw_archive.RawSnapshotArchive`. The plan audits all registered source/products against source-specific point-in-time requirements without making network calls or changing registry flags. The raw archive stores exact HTTPS response bytes, local UTC retrieval time, HTTP metadata, request metadata, and SHA-256 before normalization; it is allowlisted from enabled registry products, redacts credential-like fields, is idempotent for identical snapshots, appends revised payloads, and blocks UPDATE/DELETE.

The 9-source / 17-product registry has materially different historical semantics. Eurostat's current API exposes the latest dataset version rather than historical vintages; FRED/ALFRED requires an API key and offers date-level vintage boundaries; BLS release calendars can provide scheduled release timestamps; CFTC publication timing and cadence require active schedule verification; LBMA needs licensing review; broker spot needs a durable timezone-aware local archive. No publication timestamp is inferred from an observation date.

Phase 37 establishes acquisition governance and immutable raw evidence capture, not populated historical macro/intermarket/positioning coverage. No external requests, credential reads, source auto-fetch activation, live DB writes, monitor restart, or trading behavior changes occurred. See `phase37_controlled_multidomain_source_acquisition.md`.


## Phase 37B — Official provider adapters and first historical ingestion

Phase 37B adds bounded HTTPS provider transport and source-specific BLS CPI and CFTC TFF adapters. BLS CPI-U all-items uses the unadjusted CUUR0000SA0 series and is accepted only after the current API value matches the corresponding original BLS release archive and the original embargo timestamp matches the release calendar. In this local environment the BLS API payload was archived, but BLS schedule/archive requests returned HTTP 403; no CPI observation was backdated or persisted.

CFTC TFF Futures-Only CME EURO FX (gpe5-46if, contract code 099741) was acquired for 51 Tuesday report dates from 2025-11-25 through 2026-11-10. The provider archived the raw dataset and official release evidence, applied the special 2025 catch-up publication schedule and the 2026 regular release calendar, and mapped all 51 report dates to official 3:30 p.m. Eastern publication timestamps. Three positioning products (Dealer, Asset Manager, Leveraged Money) were ingested with 51 observations each: 153 observations total. The raw archive contains 30 immutable snapshots / 3,013,170 bytes at this verification point.

Important limitation: local retrieval time is later than historical public publication time. The existing observation store's strict get_as_of query requires both publication and retrieval timestamps to precede the cutoff, so these backfilled observations are not visible to historical cutoffs before the local retrieval. A separately attested public-source-availability replay mode is required; do not bypass the existing retrieval-time guard. This preserves the distinction between actual system knowledge and reconstructed public availability.

FRED/ALFRED, ECB SDMX, Eurostat vintages, LBMA and durable broker history remain incomplete for the source-specific reasons documented in phase37b_official_provider_adapters_and_first_ingestion.md. No auto_fetch flag, monitor process, Vision setting, risk setting, or execution boundary was changed.

## Phase 37C ? Verified Historical Availability & Replay Integration

- Two replay modes remain separate: strict system-knowledge as-of (publication + local retrieval cutoff) and explicitly attested reconstructed public availability.
- `source_registry/historical_availability.py` provides an append-only, per-observation-version attestation ledger bound to observation and raw-evidence SHA-256 hashes.
- Public-availability replay is opt-in via `PointInTimeDataPlane.read_public_availability_as_of` and labels reconstructed rows; it never backdates local retrieval or relaxes strict `get_as_of`. Latest/revision-prone values require proof of the original as-released vintage.
- Phase37B CFTC historical values are not yet attested because the current dataset snapshot alone does not prove original released vintages. BLS and other unverified sources remain excluded.

## Phase 37D ? Official Provider Expansion

- Official provider set now includes BLS CPI v2/original-release verification, FRED/ALFRED vintage capture, and ECB SDMX `includeHistory=true` capture, alongside CFTC TFF.
- FRED vintage dates are date-grained and ECB revision history lacks an independently verified intraday publication time; both are archived as research evidence but are not promoted to strict PIT observations.
- Provider calls remain explicit and manual. No source activation, scheduler, or registry auto-fetch changes.


## Phase 37E ? Durable spot-history status

- Extended the existing MT5 market store to schema v4 with append-only ingestion-run and candle-version ledgers. The current `candles` table remains a latest-value projection; distinct versions are retained separately with UTC observation/as-of timestamps and SHA-256 fingerprints.
- MT5 ingestion provenance now records the read method, broker server, symbol, timeframe/range, UTC time basis, and available terminal/symbol metadata. OHLC chart basis is explicitly BID, LAST, or UNKNOWN from MT5 symbol metadata; no default Bid assumption is made.
- Existing pre-v4 rows are not backfilled with invented provenance. At Phase37E implementation time, the live database was left at v3 because the monitor was running. During Phase51, a verified backup-first schema-only migration was completed under a controlled monitor stop; the archive is now v4 and the monitor has restarted with the version-aware adapter. Historical v3 rows remain legacy; only newly observed post-migration MT5 candles enter the immutable version ledger. No live broker historical range backfill was performed.
- One-year coverage remains unverified. MT5 chart-history limits, weekend/session gaps, broker calendar semantics, and the distinction between bar spread and true bid/ask ticks remain explicit constraints.


## Phase 37F ? Multi-domain data coverage

- Expanded the explicit FRED/ALFRED vintage product allowlist to nine daily references spanning US nominal/real yields, broad trade-weighted USD, S&P 500, VIX, WTI, Brent and the Federal Reserve H.10 USD-per-EUR reference rate. The broad USD basket is not ICE DXY; H.10 is not executable broker spot.
- Added a deterministic registry-only coverage assessment across 11 domains. The current registry has 9 sources and 23 products spanning 9/11 domains by registration only; this is not live availability or PIT eligibility. News/geopolitics and options/cross-currency remain uncovered.
- FRED vintages remain date-grain and outside strict intraday PIT until exact public release-time evidence is independently verified. Gold/ICE DXY licensing/access remains unresolved. No network fetch, key lookup, auto-fetch activation, DB mutation, monitor restart, order, risk or RAG change.


## Phase 37G ? Data quality and revision control

- Added registry-aware quality assessment for timestamp integrity, no-lookahead, publication/retrieval chronology, units, finite numeric values, duplicate identities and frequency-based freshness. Missing/unknown/invalid/future evidence blocks analytics eligibility; stale evidence is not eligible.
- Added read-only append-only revision history access with optional strict as-of filtering and summaries of changed observation keys, revision counts and comparable numeric deltas.
- Quality scores are diagnostic only, not forecast probabilities. No automatic correction, imputation, provider activation, production DB mutation, Fusion wiring, monitor restart, live order, risk, Vision or RAG change.


## Phase 38 ? Unified Historical Data Plane

- Added `PointInTimeDataPlane.read_unified_as_of` for one strict system-knowledge cutoff across enabled multi-domain products.
- Exposes immutable source evidence separately from a Phase 37G quality-gated analytics projection; failed products are quarantined, not deleted or repaired.
- Includes append-only revision summaries and deterministic SHA-256 snapshot identity. Public-availability reconstruction remains a separate attested mode.
- Read-only, no network/auto-fetch, no DB migration, and no live Fusion/decision rewiring in this phase.

- Spot FX history is joined from the separate market archive through a read-only interface. Only closed, versioned candles with observed/as-of cutoffs, UTC time basis, known BID/LAST price basis and valid OHLC can enter the analytics projection. Legacy schema-v3 candles remain visible as unpromoted archive metadata; no implicit migration occurs.


## Phase 39 — Multi-Domain Market Regime Intelligence

Phase 39 adds `MultiDomainMarketRegimeEngine` as a quality-gated synthesis layer above the legacy Phase 11 live M1/M5 regime specialist. It consumes only the Phase 38 unified strict system-knowledge snapshot. EURUSD structure and volatility classifications require a quality-eligible, versioned, closed M5 spot stream with valid OHLC and observation/as-of timestamps no later than the common cutoff; at least 65 bars are required. The descriptive price dimensions are calculated with a 20-bar directional-efficiency measure and a 14-bar true-range average against a preceding 50-bar baseline.

Macro fundamentals, monetary policy, intermarket and positioning remain separate coverage/context dimensions. They are not imputed, and CFTC positioning alone cannot create a EURUSD market-regime label. With the current schema-v3 legacy spot archive, the expected production result remains `INSUFFICIENT_EVIDENCE / UNKNOWN`; the three quality-eligible CFTC products are visible only as positioning context. The engine is not wired into live Fusion or order decisions. No network fetch, provider activation, database migration, monitor restart, risk/strategy change, or execution authority is introduced. See `phase39_multidomain_market_regime_intelligence.md`.


## Phase 40 — Statistical & Quantitative Intelligence

Phase 40 adds `PointInTimeQuantitativeStatisticsEngine` over the Phase 38 unified strict system-knowledge snapshot. It accepts only quality-eligible EURUSD M1/M5 streams marked PASS by the data plane, and independently verifies closed-bar cutoff, observation/as-of timestamps, contiguous cadence, OHLC bounds, source identity, BID/LAST basis, UTC bar-time basis, and candle version IDs. Bounded windows produce close-to-close pip-return distributions, empirical quantiles, realized volatility, downside/upside semideviation, historical sample VaR/expected shortfall, close-to-close drawdown, true-range summaries, lag-1 autocorrelation and sign persistence. Timeframes remain separate; missing streams are explicit and one available timeframe yields PARTIAL. The existing live `QuantitativeMarketStatisticsEngine` and read-only `StatisticalOutcomeEvaluator` remain separate; no live feed is silently promoted to historical PIT evidence. Current schema-v3 spot archive is not provenance-eligible, and CFTC positioning is not substituted for price returns, so current production assessment correctly remains `INSUFFICIENT_EVIDENCE`. No forecasts, trading signals, strategy performance claims or execution authority are introduced. See `phase40_statistical_quantitative_intelligence.md`.


## Phase 41 — Session & Time Intelligence

Phase 41 adds `SessionTimeIntelligenceEngine` as a deterministic temporal context layer over Phase 38 strict system-knowledge snapshots. It maps UTC instants into IANA Sydney, Tokyo, London and New York time zones, reports local clock/offset/DST state, reference session windows and London/New York overlap. It counts M1/M5 session coverage only from a single PASS, analytics-eligible EURUSD stream with strict closed-candle, observed-at and as-of cutoffs. These counts describe evidence coverage only; they do not imply volatility, liquidity or a session trading edge. Optional calendar context requires exact scheduled timestamps and publication/retrieval evidence at or before cutoff; date-only events remain date-only. Broker-specific weekly hours and holidays remain unknown without verified schedules. Current schema-v3 spot history is not promoted, so historical session coverage remains insufficient. Phase 41 is a temporal foundation for Phases 42–44, not a standalone strategy or live Fusion/order change. See `phase41_session_time_intelligence.md`.


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

- Added a strict-PIT baseline forecast engine for 15-minute, 1-hour and 4-hour EURUSD horizons, using verified closed M5 candle versions only.
- Horizon drift and descriptive dispersion are reported separately; central Phase 43 scenarios and domain coverage are context for comparison, never an override or independent vote.
- Numeric probabilities and calibrated confidence remain null; descriptive bands are not prediction intervals. Predictive skill remains unestablished pending historical replay and out-of-sample evaluation.
- Current production legacy schema-v3 spot history is ineligible, so all horizon forecasts remain INSUFFICIENT_EVIDENCE until controlled versioned ingestion.
- No live monitor rewiring/restart, DB migration/write, provider activation, execution/risk change, or commit/merge.
- Next: Phase 45 — Point-in-Time Historical Replay of timestamped forecast outputs.


## Phase 45 — Point-in-Time Historical Forecast Replay

- Added a bounded read-only candle-version history API and a replay engine that calls Phase 44 at each historical system-knowledge cutoff.
- Per-cutoff snapshots exclude any candle version whose observed_at or as_of timestamp is later than the cutoff; only closed, contiguous, verified, consistent-price-basis M5 history is used.
- Historical target outcomes use the first verified closed version observed after the target candle closes. Later corrections do not rewrite forecasts or selected target versions.
- Replay and forecast identities are deterministic and hash-bound to source history, exact visible versions, cutoff and configuration.
- Completed replay records can be stored in a separate append-only research ledger, never in the production market archive.
- Production archive remains schema v3 / 1,132 legacy candles without a version ledger, so preflight returns BLOCKED and no historical forecasts are fabricated.
- No DB migration/backfill, network/provider activation, live monitor wiring/restart, execution/risk changes or commit/merge.
- Next: Phase 46 — Scenario Evaluation Framework, with explicit scenario/forecast horizon matching and outcome coverage accounting.


## Phase 46 — Scenario Evaluation Framework

- Added ScenarioEvaluationEngine for categorical evaluation of contemporaneously archived Phase43 leading hypotheses, separate from Phase44/45 numeric baseline forecast replay.
- Requires an issuance-time archive envelope with canonical SHA-256, archive availability no later than scenario issuance, exact broker/symbol/cutoff matching, one unique leading hypothesis, and a scenario-declared horizon/classifier/invalidation-rules version.
- Outcome records must have exact matching window boundaries and horizon, verified closed-bar classification, UTC bar-time basis, known BID/ASK/MID/LAST price basis, source candle-version IDs, evidence hash, and observed/as-of timestamps no later than evaluation cutoff.
- No implicit horizon, nearest-time joins, reconstruction of missing historical scenarios, probabilities, confidence calibration, or trade-performance claims.
- Current production status is NO_ARCHIVED_SCENARIOS: Phase43 does not yet emit scenario_evaluation_spec and no verified contemporaneous scenario archive is configured. Phase45 market replay is independently blocked by the schema-v3 archive lacking the immutable candle-version ledger.
- Eleven focused Phase46 tests pass. No live monitor/archive wiring, DB mutation/migration, provider activation, risk/order changes, RAG mutation, commit or merge.


## Phase 47 — Forecast Error Analysis

- Added a read-only diagnostic engine over completed Phase45 strict system-knowledge replay records; Phase44 forecast generation is unchanged.
- Reports 15M, 1H and 4H separately: directional accuracy (including and excluding neutral forecasts), confusion matrix, MAE, RMSE, signed bias (actual minus forecast), median/P90/P95 absolute error, and forecast-vs-realized movement magnitudes.
- Adds direction-conditioned error and forecast-dispersion terciles. Dispersion terciles are explicitly not market regimes; Phase39 regime attribution is unavailable because Phase45 records do not archive contemporaneous regime labels.
- Requires replay COMPLETE status, M5 EURUSD identity and all six strict PIT integrity flags. Missing outcomes are not imputed; duplicate IDs, unsupported horizons and invalid numeric/provenance records are excluded with reason codes.
- Production remains BLOCKED because Phase45 cannot create a production replay while the spot archive lacks the immutable candle-version ledger. No production error metrics are claimed.
- No model tuning, live forecast changes, monitor restart, DB mutation, provider activation, risk/order changes, RAG mutation or commit/merge.


## Phase 48 — Uncertainty Calibration

- Added a read-only calibration research engine over COMPLETE Phase45 strict system-knowledge replay records. All six Phase45 PIT integrity flags are mandatory.
- Calibrates descriptive interval width, not directional probabilities or confidence. For each horizon (15M, 1H, 4H), an earlier chronological partition estimates finite-sample split-conformal multipliers from absolute forecast error normalized by Phase44 historical dispersion; a strictly later holdout measures empirical coverage and interval width.
- Reports 80%, 90% and 95% target-coverage interval multipliers, holdout coverage/gap/width, and uncalibrated one-/two-sigma baseline coverage. The latter are empirical coverage figures only; no Gaussian nominal coverage is assumed.
- Default readiness requires at least 50 calibration and 30 later holdout outcomes per horizon. Insufficient samples remain BLOCKED; horizons are never pooled and tied timestamps cannot cross the split.
- Serial dependence, overlapping horizons, nonstationarity and one-holdout limitations are explicit. Multipliers are research-only and are not applied to Phase44, Fusion, decisions, risk or live monitoring. No probabilities, calibrated confidence or trading performance are claimed.
- Current production result remains BLOCKED because Phase45 has no COMPLETE replay: the spot archive is schema v3 and lacks immutable candle-version history. Synthetic fixtures test mathematics only.
- No provider activation, network fetch, credentials, database mutation, monitor restart, RAG mutation, risk/order changes, commit or merge.


## Phase 49 — Walk-Forward Validation

- Added a strict chronological walk-forward research engine over COMPLETE Phase45 system-knowledge replay records. All six Phase45 PIT integrity flags, forecast/target version provenance, source-history hash and replay identity are required.
- Validates the fixed Phase44 baseline without tuning its parameters. EURUSD M5 horizons 15M, 1H and 4H remain separate.
- Uses rolling eligible training history (default minimum 100, maximum 500 outcomes), followed by non-overlapping 30-outcome test windows; requires at least two folds per horizon.
- Critical label-availability purge: a training outcome is eligible only if its target candle close is at or before the first forecast cutoff of the test window. This prevents using training labels that would not yet have been known at test time.
- Each fold fits 80%, 90% and 95% interval-width multipliers on training residuals only and measures holdout coverage/width, baseline descriptive-band coverage, MAE, RMSE, signed bias and directional agreement. Aggregate and fold-to-fold variation are descriptive only.
- No probabilities, calibrated confidence, model tuning, live forecast application or profitability claims. Production remains BLOCKED until Phase45 can produce a complete immutable versioned-candle replay.
- No external acquisition, provider activation, credentials, production DB mutation, monitor restart, RAG/risk/order changes, commit or merge.


## Phase 50 — Cross-Domain Attribution

- Added a read-only attribution research engine over completed Phase45 strict system-knowledge forecast replay records with all six PIT integrity flags.
- Requires contemporaneous per-forecast domain context, bound to the exact forecast snapshot and carrying its own context hash, evaluated/as-of/available timestamps, evidence references and source-lineage IDs. Any context later than the forecast cutoff, snapshot mismatch, missing evidence lineage or invalid hash is rejected.
- Analyzes spot FX, macro fundamentals, monetary policy, intermarket, positioning/sentiment, news/events, market regime, session/time, liquidity/microstructure and derived cross-domain relationships.
- Per horizon (15M/1H/4H), reports baseline forecast error and conditional state-stratified MAE/RMSE/signed bias/directional agreement and deltas versus baseline. State groups below 30 records remain unscored; missing context is never imputed.
- Shared price-derived, macro/policy and derived-relationship lineage groups prevent correlated views being treated as independent confirmations. Causality, feature importance and incremental predictive contribution are explicitly NOT_ESTABLISHED / NOT_ESTIMATED.
- Current production remains BLOCKED because Phase45 has no complete immutable candle-version replay; historical domain context was not supplied in existing replay records. No production attribution metrics are emitted.
- No provider activation, external acquisition, credentials, database mutation, monitor restart, live decision wiring, RAG/risk/order changes, commit or merge.


## Phase 51 — Continuous Learning & Research Governance

- Adds a controlled research-cycle engine that joins only matching Phase45 strict PIT replay, Phase49 walk-forward validation and Phase50 contemporaneous cross-domain attribution reports. Replay ID, source-history hash and all six PIT integrity flags must match.
- Each 15M/1H/4H horizon is gated independently. Research readiness requires at least two chronological OOS folds and 100 completed outcomes plus matching attribution evidence. A passing gate only permits governed research review; it never authorizes live promotion.
- Adds an experiment manifest contract pinning engine/version, code SHA-256, parameter SHA-256, replay ID, source-history hash and UTC registration time.
- Adds an explicit append-only research SQLite ledger for experiment manifests, evaluation reports and human review events. UPDATE/DELETE are blocked; replay/source mismatches and unsupported promotion states are rejected. The ledger is not created by a blocked production preflight.
- No automatic training, parameter tuning, model promotion, probability/confidence synthesis or live model mutation. Human review and a separate authorization are mandatory for any future deployment.

## Phase 37E — Controlled schema-v3 to v4 migration procedure

- Adds scripts/migrate_market_archive_v4.py. Default invocation is read-only preflight. Explicit --apply performs a verified SQLite online backup, then an atomic exclusive schema migration to v4, and verifies integrity and unchanged legacy candle count.
- Existing v3 candles remain legacy and are never assigned fabricated observation/as-of times or inserted into candle_versions. The new immutable ledger starts empty and records only observations made by the v4 ingestion code after activation.
- A schema migration alone is not proof of versioned ingestion. The monitor must run the v4 MT5 adapter after a controlled restart, then verify fresh ingestion runs and candle versions with source provenance.

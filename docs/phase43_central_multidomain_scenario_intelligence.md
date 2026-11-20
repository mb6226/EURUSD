# Phase 43 ? Central Multi-Domain Scenario Intelligence

## North Star capability advanced
Upgrade the existing central EURUSD scenario brain into an explicit multi-domain scenario orchestrator. This phase extends the existing engine/runtime; it does not create a parallel scenario engine or turn the project into a Price Action bot.

## Concrete gap closed
The prior central engine accepted live specialists and contextual domains but did not accept the Phase 39?42 strict PIT reports as first-class, typed context. It also lacked a machine-readable dependency map for overlapping evidence lineage.

## Implementation
- Upgraded `CentralScenarioIntelligenceEngine` to version `1.1.0`.
- Added context-only sources for strict PIT market regime, PIT quantitative statistics, session/time intelligence, cross-domain relationship intelligence, and a compact unified data-plane summary.
- Extended `build_central_scenario_payload` to accept explicit PIT reports or one unified historical snapshot. When a snapshot is supplied, the runtime derives Phase39, Phase40, Phase41 and Phase42 assessments from that same immutable snapshot and binds each report to its own `as_of_utc`.
- Rejects mixed explicit PIT reports plus a unified snapshot to avoid ambiguous provenance.
- Preserves `INSUFFICIENT_EVIDENCE` and `BLOCKED` as incomplete evidence rather than relabeling them as missing; incomplete reports remain visible in contextual summaries.
- Added a dependency map for shared EURUSD broker-price lineage, CFTC positioning, intermarket drivers, macro/policy/calendar, news, and historical outcome research. Shared-lineage members have zero independent votes.
- Added an explicit scenario contract: qualitative conditional hypotheses, no numeric probability, no calibrated confidence, out-of-sample validation not established, context-only sources cannot vote, and invalidation conditions required.
- Existing directional assessment remains restricted to the prior permitted price-structure sources. PIT regime, PIT statistics, session/time, intermarket relationships, macro, news, positioning, and historical research remain context-only.
- Existing Fusion, decision, risk, and order-execution boundaries remain unchanged.

## Production snapshot validation
A read-only production snapshot was passed through the Phase39?42 orchestrator and central scenario engine. Data-plane status was `PARTIAL`; the four PIT specialist outputs were each `INSUFFICIENT_EVIDENCE`; the unified data-plane summary was `PARTIAL`. With no live directional reports supplied to this isolated research check, direction correctly remained `UNRESOLVED` and all three scenario hypotheses remained unresolved. Coverage was `LIMITED`. The shared broker-price dependency group recorded three PIT views and zero independent votes. This validates orchestration and honest evidence handling, not market predictive skill.

Current archive limitations remain: three quality-eligible products are all from the CFTC positioning domain; no eligible cross-domain relationship pair exists; the Spot archive lacks eligible versioned provenance for M1/M5; macro, policy and intermarket coverage remain insufficient. No directional or predictive claim is made.

## Tests and acceptance
Focused central engine/runtime regression suite: 25 tests. Full-suite, compileall, diff-check, report JSON validation, and read-only SQLite integrity checks are recorded in `reports/phase43_central_multidomain_scenario_intelligence_report.json`.

## Explicit non-goals and safety
No live monitor wiring or restart, no external fetching/provider activation, no registry mutation, no database write/migration, no RAG mutation, no Fusion directional vote changes, no decision/risk changes, no live orders, no commit or merge. The current monitor remains on its existing runtime path; the new PIT snapshot orchestration is available through the central runtime API and is tested independently.

# Phase 37G ? Data Quality & Revision Control

## Purpose

Protect the multi-domain EURUSD intelligence plane from invalid, stale, inconsistent, revised, or temporally unsafe evidence. This phase adds an explicit quality assessment layer and read-only revision history access. It does not auto-correct data or silently feed scores into Fusion.

## Implemented

- `source_registry/data_quality.py` evaluates explicitly supplied point-in-time observation rows against registry units and declared observation frequency.
- Structural checks: observation identity duplication, finite scalar or valid low/high range, expected unit, timezone-aware effective/publication/retrieval timestamps, publication-before-retrieval chronology, and as-of cutoff/look-ahead constraints.
- Freshness defaults are frequency-aware: intraday 1 day, daily 5 days, weekly 21 days, monthly 75 days, quarterly 120 days, event-driven 180 days. These are conservative operational defaults, not economic validity ranges; product-specific thresholds need later calibration.
- Missing observations, unknown publication time, invalid timestamps, unit mismatch, invalid numeric values and future evidence block downstream analytics eligibility. Stale evidence is warned and also not eligible.
- Quality score is an explainable diagnostic (100 minus fixed issue penalties), not a probability, confidence estimate, or model forecast score.
- `PointInTimeObservationStore.get_revision_history` exposes immutable observation versions, optionally constrained by the same publication, retrieval and effective-time cutoff as strict system-knowledge replay.
- Revision summaries count changed observation keys and versions and calculate maximum absolute numeric delta where comparable. Original versions remain intact.

## Boundaries

- No values are repaired, imputed, clipped, or overwritten.
- No source is fetched; no credentials or API keys are read; no auto-fetch is enabled.
- No PIT filters are bypassed and no historical public availability is inferred.
- Quality gate is not yet wired into Fusion/Scenario Intelligence; the report is an auditable diagnostic layer pending Phase38 integration design.
- No DB schema migration, production DB mutation, monitor restart, order, risk, Vision, or RAG change.

## Validation

Dedicated regression tests cover clean records, unknown publication timestamps, unit mismatch, future timestamps, retrieval/publication ordering, invalid/non-finite values, stale products, missing products, revision deltas, deterministic no-mutation reporting, and read-only revision history with as-of cutoffs. Acceptance: 42 focused tests and the complete 648-test suite passed; `compileall`, registry validation, SQLite integrity checks and `git diff --check` passed. The production observation, raw archive and market databases were integrity-checked without writes.

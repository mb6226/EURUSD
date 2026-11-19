# Phase 10 — Statistical Outcome Evaluation

## Purpose

Phase 10 reads Phase 9's durable price-excursion observations and produces deterministic descriptive statistics. It is a read-only research report, not a backtest or a trade-performance evaluator.

## Data source and cohort

- Source: `setup_observations.sqlite3`, tables `setup_observations` and `observation_candles`.
- The evaluator opens the existing database in SQLite read-only mode. It never creates a missing database, writes rows, changes statuses, or edits Phase 9 evidence.
- Only `COMPLETED` observations with at least one stored candle and an exact match between `candles_processed` and immutable candle evidence count are included.
- `ACTIVE`, `DATA_CONFLICT`, zero-evidence, and integrity-inconsistent records are counted and excluded from the statistical cohort.
- A missing database returns `UNAVAILABLE`; missing tables or read errors return `DEGRADED`; no usable completed observations returns `INSUFFICIENT_DATA`.

## Statistics

For each available cohort, report sample size and MFE/MAE distributions:
- mean
- nearest-rank median, p25, p75
- minimum and maximum

Groups:
- all observations
- London and New York
- UP and DOWN
- each session-direction combination

A configurable minimum group sample size (default 30) labels a group as either `MINIMUM_SAMPLE_REACHED` or `LOW_SAMPLE_DESCRIPTIVE_ONLY`. This is a reporting convention, not a statistical significance test or a guarantee of representativeness.

## Interpretation and safety

- MFE and MAE are independent price excursions from the M1 retest close; they are not trade returns.
- Intrabar ordering between favorable and adverse extremes is unknown.
- No win rate, expectancy, realized P/L, or actual SL/TP hit rate is calculated.
- Phase 9 does not persist market-regime or news-context features, so this phase cannot honestly segment by those dimensions.
- The report is descriptive. It does not establish causality, profitability, or predictive edge.
- No parameter optimization, automatic learning, strategy mutation, entry signal, order, or MT5 execution is permitted.
- Every report has `decision_authority=ASSESSMENT_ONLY`, `trade_authority=NONE`, and `order_execution=DISABLED`.

## Acceptance tests

The focused suite covers missing-database behavior, completed-cohort aggregation, session/direction grouping, active/conflict exclusion, evidence-count integrity, read-only behavior, and absence of trade-performance claims.

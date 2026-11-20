# Phase 48 — Uncertainty Calibration

## Purpose

Add a point-in-time-safe calibration research layer for Phase 44's descriptive forecast dispersion. This phase does not claim predictive skill, generate directional probabilities, or alter live forecasts.

## Method

- Input must be a COMPLETE Phase 45 EURUSD M5 strict system-knowledge replay with all six replay integrity flags true.
- Completed records must include forecast/target version lineage, snapshot hash, valid chronological cutoff/target timestamps, finite expected and realized moves, and the exact Phase 44 descriptive one-sigma/two-sigma bands.
- Horizons (15M, 1H, 4H) are evaluated independently.
- For each horizon, unique forecast cutoffs are split chronologically. The earlier partition estimates a finite-sample split-conformal order statistic of absolute forecast error divided by baseline historical dispersion. The later partition is held out for evaluation.
- Multipliers are estimated separately for nominal target coverage levels 80%, 90%, and 95%. The report measures empirical holdout coverage, coverage gap and interval width. Baseline descriptive one-sigma/two-sigma coverage is also reported without assigning them Gaussian nominal coverage.
- The evaluation partition is never used to fit the multiplier. Tied cutoff timestamps cannot cross the partition boundary.

## Readiness and fail-closed behavior

Default minimums are 50 calibration outcomes and 30 later holdout outcomes per horizon. A horizon below either minimum is BLOCKED. Overall status is AVAILABLE only when all three horizons pass, PARTIAL when some pass, and BLOCKED when none pass.

## Important limitations

- This is interval-width calibration research, not directional probability or calibrated confidence.
- Split-conformal order statistics do not guarantee future coverage under serial dependence, overlapping horizons, nonstationarity or regime change.
- Forecast records can share anchors and overlapping outcome windows; sample counts are not independent-trial counts.
- One chronological holdout is not a substitute for repeated walk-forward validation.
- Calibration multipliers are reported for research only. They are not applied to Phase44, Fusion, decisions, risk, live monitoring or orders.
- No production replay currently exists: Phase45 is blocked because the market archive has no immutable candle-version ledger. Therefore the expected production Phase48 result is BLOCKED with zero scored records; synthetic unit-test fixtures validate calculations only.

## Safety boundaries

No provider activation, network fetch, credentials, production database mutation, monitor restart, RAG mutation, risk change or order execution is performed. Phase44 forecast behavior remains unchanged.

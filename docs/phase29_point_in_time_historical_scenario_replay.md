# Phase 29 — Point-in-Time Historical Scenario Replay & Evaluation

## North Star capability

Advance central intelligence, quantitative/statistical intelligence, reliable historical data, and the research/learning laboratory. The objective is to measure the quality of Phase 28 multi-domain scenario hypotheses across historical market conditions without turning the evaluator into a trading strategy or execution authority.

## Repository gap closed

Phase 28 emits live qualitative scenario assessments, while prior outcome evaluators measure setup-specific MFE/MAE. The repository did not provide a reproducible evaluator for archived central scenario reports against later closed EURUSD candles.

## Implementation

- `HistoricalScenarioReplayEngine` consumes archived Phase 28 report mappings and the existing `MarketDataStore`.
- `replay_monitor_logs` reads existing monitoring JSONL files, extracts `central_scenario_intelligence`, reports malformed/unreadable archive coverage, and never modifies source files.
- Supports M1/M5 and explicitly configured pip size, neutral band, and bar-count horizons.
- Uses the latest closed anchor candle whose close time is at or before the scenario evaluation timestamp.
- Measures close-to-close movement at the Nth subsequent timeframe candle and classifies the realized outcome as UP, DOWN, or RANGE using the explicit neutral band.
- Emits horizon-specific sample counts, scenario accuracy, directional accuracy, and forecast-row / realized-column confusion matrices.
- Excludes unresolved/conflicted scenarios, identity mismatches, missing anchors, insufficient future history, gaps, and post-forecast candle revisions.
- Reads the market archive through its existing API and reads revision history to prevent later candle corrections from leaking into historical results. If the revision scan reaches its safety limit, samples fail closed.
- The replay loop uses timestamp binary search so archived replay scales better than scanning all candles for every report.

## Point-in-time contract and limits

This phase evaluates archived scenario outputs; it does not regenerate historical specialist states. The scenario's `evaluated_at_utc` and broker/symbol identity are mandatory. The market archive must contain the later closed bars required for each horizon. Anchor and future candles revised after the scenario timestamp are excluded.

The current candle archive records when a revision was detected, not a complete versioned history of every first-seen candle value. Therefore this implementation conservatively excludes affected samples rather than attempting to reconstruct a potentially contaminated historical candle. A future phase may add a full as-of candle-version reader and specialist-report archive manifest.

Only reports captured at their original time are valid forecasts. Current reports cannot be backdated or relabeled as historical predictions.

## Metrics

- Scenario accuracy: exact match between the Phase 28 resolved state (UP/DOWN/RANGE) and realized horizon class.
- Directional accuracy: exact UP/DOWN match among directional forecasts only; range forecasts are excluded from this metric.
- Confusion matrix: forecast class rows and realized class columns.
- Forward move in pips: descriptive close-to-close movement, not a trade return.

No probability scores, calibration, confidence, profitability, win rate, expectancy, P/L, entry/exit, spread/slippage simulation, SL/TP, position sizing, or automatic learning is introduced. Calibration is deferred until sufficiently large, representative, out-of-sample evidence and a separate methodology exist.

## Integration

The runtime adapter consumes the monitoring JSONL artifacts produced by the existing `SignalManager`, extracting the exact central scenario object already published in each cycle. It uses the existing market archive and does not change the live monitoring loop, Fusion votes, decision path, or WAIT/alert-only behavior.

## Acceptance

- Deterministic unit tests for correct/incorrect direction, unresolved/conflicted and wrong-identity reports, absent anchors, revision leakage, invalid parameters, and JSONL ingestion.
- Focused tests run with the repository's local Python environment.
- Full repository regression, compile checks, and diff validation before merge.
- Exact tested PR head SHA required for merge.

## Explicit non-goals

- No live provider fetching or historical report fabrication.
- No modification of market, observation, RAG, or knowledge databases.
- No automatic model training, probability calibration, source weighting, or strategy optimization.
- No Fusion directional vote changes, BUY/SELL enablement, risk changes, or MT5 order execution.

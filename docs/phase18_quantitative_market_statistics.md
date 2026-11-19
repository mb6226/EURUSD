# Phase 18 — Quantitative Market Statistics Foundation

## North Star capability advanced

Gate 2 — domain specialist coverage. This phase starts the general quantitative/statistical domain, independently of Price Action and setup-outcome reporting. It measures closed-bar EURUSD behavior on M1 and M5 and makes the resulting evidence consumable by the central research synthesizer.

## Repository gap addressed

Before this phase, `statistical_engine.py` was a placeholder. The existing statistical outcome evaluator only summarized completed setup MFE/MAE observations; it was not a general market-statistics specialist. The repository also lacked a tested path for publishing a current-cycle quantitative assessment into the research source envelope.

## Deliverables

### 1. Deterministic quantitative specialist

`eurusd_ai_monitor/engines/quantitative_market_statistics_engine.py` adds `QuantitativeMarketStatisticsEngine` over the shared immutable `MarketSnapshot`.

For separately evaluated M1 and M5 closed-candle windows, it reports:
- close-to-close return distribution in pips: mean, median, sample standard deviation, nearest-rank p05/p25/p75/p95, min and max;
- positive, negative and zero return sample frequencies;
- candle-range and true-range distributions in pips;
- directional efficiency ratio;
- exact candle IDs and window boundaries for provenance.

The lookback and minimum-history thresholds are explicit and injectable. Decimal arithmetic is used for reported statistics. Forming/future bars, non-chronological or duplicate timestamps, identity mismatches, invalid snapshot quality, and insufficient history are rejected or reported as blocked/degraded/insufficient rather than silently filled.

### 2. Central research consumption

The research source contract now recognizes `quantitative_market_statistics` as an optional current-cycle specialist:
- when supplied, identity and timestamp are validated and its descriptive features/provenance are retained in `current_context`;
- insufficient history becomes an incomplete/partial research context, not a directional vote;
- when absent, legacy research cycles remain compatible and explicitly mark the optional specialist missing;
- the specialist is not promoted to a required source until the runtime produces it consistently.

An end-to-end test exercises `MarketSnapshot → QuantitativeMarketStatisticsEngine → research source envelope → ResearchIntelligenceEngine`.

## Acceptance criteria

- M1 and M5 windows are measured separately using only closed candles.
- Sample sizes, distributions, return frequencies, ranges, true ranges and efficiency are deterministic.
- Invalid quality, short history, forming/future bars, duplicate or unordered candles fail closed.
- Output includes candle-level provenance and explicit assessment-only authority.
- Research synthesis preserves the quantitative payload and its provenance without treating it as directional evidence.
- Missing optional quantitative output does not break existing research cycles.
- Focused tests and the full regression suite pass on the exact PR head SHA.

## Explicit non-goals and safety

- No forecast, calibrated probability, directional bias, signal, strategy, win rate, expectancy, or profitability claim.
- No automatic invocation from the live monitoring loop in this phase; the research contract is ready for explicit runtime injection, and absence remains visible.
- No new data provider, network fetch, historical backfill, scheduler, or persistent database.
- No change to Price Action, strategy parameters, legacy WAIT behavior, risk, BUY/SELL, MT5 orders, or execution.
- No mutation of source-registry operational state or RAG/knowledge databases.

## Next capability gaps

This is a foundation, not the completed quantitative brain. Follow-on work should add point-in-time event studies, wave/sequence measurement, conditional distributions by regime/session/news context, robust uncertainty intervals and walk-forward research controls. Macro/fundamental interpretation and official source ingestion remain a parallel high-priority domain and must not be displaced by further Price Action work.

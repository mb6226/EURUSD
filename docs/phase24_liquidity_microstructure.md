# Phase 24 — Liquidity & Microstructure Intelligence Foundation

## Objective

Add a deterministic, research-only specialist that describes broker-feed liquidity and microstructure proxies from closed EURUSD MT5 candles. This is one specialist in the multi-domain EURUSD market brain, not a standalone trading strategy.

## Evidence contract

Input samples must explicitly provide a validated `Candle`, symbol-specific `pip_size`, independently normalized `spread_pips` (or null), and timezone-aware `retrieved_at_utc`. The engine never guesses pip size or converts the stored MT5 `spread` integer because its point scale depends on broker and symbol configuration.

The engine evaluates M1 and M5 separately. It excludes unclosed candles, rejects future retrieval timestamps, rejects duplicate timestamps and identity mismatches, enforces freshness and minimum history, and reports missing spread evidence as partial rather than fabricating it.

## Initial metrics

- Spread median, p95, and recent-to-baseline median ratio.
- Broker tick-count median, p95, and recent-to-baseline median ratio.
- Candle range median, p95, and recent-to-baseline median ratio.
- Median candle body-to-range ratio.

All metrics are descriptive. Tick volume is broker tick activity, not centralized traded volume. These proxies cannot establish consolidated FX liquidity, executable depth, queue position, hidden liquidity, or order-book imbalance.

## Integration boundary

The output follows the optional specialist payload contract used by ResearchIntelligenceEngine: `status`, `evaluated_at_utc`, broker/symbol identity, `reason_codes`, provenance, and explicit non-trading authority. Research synthesis can retain it as optional context; the engine is not wired to live MT5, runtime scheduling, automatic ingestion, or order execution in this phase.

## Acceptance

Run the focused test module, research-intelligence integration tests, and full unittest regression suite on the exact PR head SHA. No local test success is claimed by the implementation author.

## Non-goals

No Level 2 provider, centralized volume claim, live data polling, scheduler, signal generation, BUY/SELL authority, risk changes, MT5 order placement, RAG database mutation, or strategy profitability claim.

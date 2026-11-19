# Phase 26 — Live Multi-Domain Runtime Vertical Slice

## North Star capability

Advance the central-intelligence and operations domains by making selected, already-computable specialists actual participants in each monitoring cycle. This is a first integration slice, not completion of Central Intelligence v2.

## Repository gap

Phases 18 and 24 supplied deterministic quantitative and broker-feed liquidity specialists, but the main monitoring loop did not invoke them. Phase 25 ensured the research source envelope could carry liquidity payloads, but did not connect producers.

## Implementation

- Instantiate the quantitative market-statistics and liquidity/microstructure engines in `eurusd_ai_monitor/main.py`.
- Evaluate both against the current `MarketSnapshot` during each cycle.
- Pass the resulting reports through the canonical research source envelope and expose them in the published cycle payload.
- Isolate specialist exceptions: one failure degrades only that specialist report and cannot suppress the other.
- Keep specialist evaluation timestamps and broker/symbol identity tied to the current snapshot.
- For liquidity samples, pass closed snapshot candles and the configured pip size. Do not fabricate historical spread observations: `spread_pips` remains null because the current tick spread is not a per-candle history and raw `Candle.spread` is not normalized.

## Explicitly not integrated

Macro fundamentals, policy-rate differential, intermarket, and positioning remain absent from the live cycle because their current inputs are manual point-in-time observation sets and the runtime has no validated query/selection contract for those datasets. They remain explicitly missing in the research manifest. No hidden fetch, timestamp substitution, forward fill, or synthetic values are introduced.

No new directional votes are added to Fusion. Quantitative and liquidity outputs remain descriptive/context-only. Existing WAIT/alert-only behavior, risk gates, strategy parameters, RAG/knowledge stores, and order execution are unchanged.

## Acceptance

- Unit tests prove both specialists receive the current cycle snapshot.
- Quantitative and liquidity reports preserve current cycle identity/time.
- Liquidity spread history remains explicitly unknown unless a future normalized per-candle source is supplied.
- Failure of either specialist is isolated and fails closed.
- Research source manifest receives the live specialist payloads.
- Full regression suite passes on the exact PR head before merge.

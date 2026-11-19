# Phase 11 — Market Regime Intelligence

## Objective

Add a deterministic, explainable market-regime specialist over the validated point-in-time MarketSnapshot. The specialist describes the current M5 market environment and supplies independently visible M1 alignment context. It does not create a trade signal or change any strategy setting.

## Regime model

The engine emits two orthogonal assessments:

- **Structure regime:** TRENDING, RANGING, TRANSITIONAL, or UNKNOWN.
- **Volatility state:** HIGH, NORMAL, LOW, or UNKNOWN.

The M5 TechnicalEngine remains the sole source of directional structure. A TRENDING classification requires both sufficient directional efficiency and an UP/DOWN M5 structure direction. A confirmed protected-swing break forces TRANSITIONAL. Low directional efficiency classifies RANGING. Intermediate or structurally unconfirmed conditions remain TRANSITIONAL rather than guessing direction.

M1 alignment is separately reported as ALIGNED, OPPOSED, NEUTRAL, or UNAVAILABLE. It is context-only and cannot override M5 direction or change the M5 regime.

## Features and defaults

- Kaufman-style directional efficiency ratio over 20 closed M5 bars.
- Prior-window efficiency over the preceding 20 M5 bars to detect a range-to-trend candidate.
- True-range ATR over 14 recent M5 bars.
- Baseline ATR over 50 preceding M5 bars.
- Volatility ratio = recent ATR / baseline ATR.
- Default efficiency thresholds: TRENDING >= 0.35; RANGING <= 0.20.
- Default volatility thresholds: HIGH >= 1.50; LOW <= 0.65; otherwise NORMAL.

Thresholds are explicit, validated, versioned in the report, and are descriptive research defaults rather than optimized trading parameters.

## Data integrity and provenance

- Uses only the immutable MarketSnapshot and closed M5/M1 candles.
- Rejects invalid snapshot quality, out-of-order/duplicate candles, and forming/future candles.
- Requires sufficient M5 history for both the recent window and volatility baseline.
- Reports exact M5 and M1 candle identifiers and analysis windows.
- Deterministic and stateless: the same snapshot and M5 structure produce the same report.
- No future bars, tick-derived directional inference, or hidden mutable regime memory.

## Runtime integration

The monitor publishes `market_regime_intelligence` alongside the existing Phase 6–10 outputs. An exception is converted to a DEGRADED/UNKNOWN assessment and does not interrupt the legacy WAIT/alert-only path.

## Explicit non-authorities

This phase does not:
- issue BUY/SELL, entry, exit, or WAIT-to-trade transitions;
- authorize or block an order, position, or risk allocation;
- change SL/TP, session gates, strategy configuration, or parameters;
- optimize thresholds, learn online, or mutate the RAG database;
- claim regime probabilities, predictive accuracy, or profitability.

Every output carries `decision_authority=ASSESSMENT_ONLY`, `trade_authority=NONE`, and `order_execution=DISABLED`.

## Acceptance coverage

Focused tests cover trend/range/transition classification, volatility expansion, M5 structure authority, M1 context-only alignment, invalid quality, insufficient history, forming candles, deterministic provenance, and threshold validation.

# Phase 39 — Multi-Domain Market Regime Intelligence

## Objective

Add a quality-gated regime synthesis layer above the existing Phase 11 M1/M5 descriptive specialist. This phase does not duplicate the legacy specialist and does not claim that the live rolling-candle path is point-in-time historical evidence.

## Architecture

- New `MultiDomainMarketRegimeEngine` consumes the Phase 38 unified data-plane report only.
- Spot price structure and volatility are classified only from the strict, quality-eligible EURUSD M5 version ledger.
- Requires at least 65 closed M5 candles with valid OHLC, version identity, timezone-aware open/close/observed/as-of timestamps, and all timestamps no later than the unified cutoff.
- Uses a 20-bar directional efficiency ratio and recent 14-bar true-range average against a preceding 50-bar baseline.
- Reports TRENDING, RANGING, TRANSITIONAL, or UNKNOWN structure and a separate HIGH/NORMAL/LOW volatility dimension.
- Macro fundamentals, monetary policy, intermarket, and positioning are independent coverage/context dimensions. Their presence is never converted into a price direction or a market-regime label by this phase.
- Positioning-only evidence cannot produce a market regime. Missing or blocked domains remain explicit.

## Current production interpretation

The current production snapshot has quality-eligible CFTC positioning observations but no provenance-eligible M5 spot candle stream. Therefore the expected current result is `INSUFFICIENT_EVIDENCE / UNKNOWN`, with positioning shown as context only. The legacy schema-v3 spot candles remain quarantined.

## Safety and boundaries

- Strict system-knowledge point-in-time cutoff only; no public-availability replay shortcut.
- No lookahead, candle repair, interpolation, imputation, or hidden fallback to rolling MT5 candles.
- No network access, provider activation, database migration, monitor restart, Fusion rewiring, or live execution.
- No trade signal, order authority, sizing, stop/target, risk, or strategy-setting changes.
- Existing Phase 11 MarketRegimeEngine remains intact and separately described as its live descriptive specialist.

## Acceptance

Offline tests cover positioning-only insufficiency, eligible trend/range classification, partial multi-domain coverage, insufficient history, future timestamp rejection, and timezone-aware cutoff validation.

# Phase 34 — Local-Only Vision Context Specialist

## North Star capability advanced

Advance the comprehensive multi-domain EURUSD intelligence system's cross-domain evidence and operational-observability capabilities. Chart imagery becomes a traceable visual evidence source alongside broker candles and other specialist reports. Vision remains descriptive context, not a trading authority.

## Repository gap

The MT5 screenshot exporter already produced M1/M5 PNGs, but the vision engine only checked file existence, freshness and dimensions. No model interpreted the image, and the screenshot evidence had no stable content fingerprint. The MT5 connector also relied on default terminal discovery even though multiple terminals were installed.

## Implementation

- The MT5 connector accepts an explicit terminal executable path. The live configuration pins the Headway MT5 terminal so the monitor does not accidentally attach to another terminal.
- Screenshot inspection now records UTC capture time, dimensions, file size, SHA-256, stable evidence ID and basic image-quality measurements.
- The local Ollama vision provider uses the locally installed qwen2.5vl:7b model through Ollama on 127.0.0.1. The adapter rejects non-loopback endpoints, resizes images to a bounded input size, requests compact descriptive JSON and normalizes the output schema.
- The vision runtime performs inference in a background thread. It uses a latest-frame-wins queue per timeframe, throttles inference to one attempt per timeframe every 240 seconds, treats results older than 360 seconds as stale, and retries when the MT5 exporter overwrites a screenshot between inspection and analysis. The market polling loop is not blocked by model inference.
- The M1/M5 vision reports are attached to each monitoring cycle with the analyzed image hash, model identity, age, latency and whether the analyzed image is the exact current screenshot or a recent prior frame.
- Fusion accepts visual as an optional context-only specialist. It retains timeframe direction/quality flags and detects disagreements with technical and Price Action evidence. Visual direction is always NEUTRAL at the Fusion interface; it cannot cast a directional vote or make an incomplete required specialist set appear complete.
- The legacy decision engine remains fail-closed. Even when visual analysis is available, the monitor stays WAIT until the complete user-defined Trend-Correction-Rejection-Pullback rules are implemented and validated.

## Runtime verification

On 2026-11-19, the live Headway MT5 connection supplied M1/M5 CSV data and M1/M5 screenshots to the advanced repository. The local Qwen model analyzed both timeframes successfully in a live cycle:

- M1: observed direction DOWN, chart quality GOOD, approximately 63 seconds inference latency.
- M5: observed direction DOWN, chart quality GOOD, approximately 67 seconds inference latency.
- Both reports were marked ANALYZED_RECENT_FRAME, not exact-current-image matches; their analyzed SHA-256 values remain attached to the evidence.
- The technical specialist disagreed with the visual observation and Fusion emitted VISUAL_TECHNICAL_DIRECTION_DISAGREEMENT.
- The final decision remained WAIT, direction NONE, execution DISABLED.

These two chart observations are a connectivity smoke test, not an accuracy study, calibrated signal, forecast validation or profitability claim.

## Acceptance

- 18 focused unit tests pass across screenshot provenance, local-provider endpoint safety, asynchronous runtime/retry behavior, MT5 terminal selection, duplicate evidence normalization, decision safety and optional visual Fusion integration.
- compileall, configuration JSON validation and git diff --check pass.
- The local monitor starts, reports the explicit Headway terminal path, reports the local-only vision provider, and continues writing M1/M5 market outputs.
- No BUY/SELL authority or order execution is introduced.

## Limitations

- The local 7B vision model is CPU-bound on this machine; measured per-image inference is roughly 60–67 seconds. The 240-second per-timeframe interval is an operational throttle, not a model-quality guarantee.
- Vision outputs are qualitative descriptions. They are not independently validated against a labeled screenshot set and must not be treated as precise price extraction, support/resistance detection, scenario probabilities or trade signals.
- Recent-frame analysis can refer to a screenshot captured before the current PNG; exact image hashes and age are retained so this is not hidden.
- The runtime currently uses the existing Starter v1 Python virtual environment because it contains the required MetaTrader5/pandas packages. A dedicated environment for the advanced repository remains operational cleanup.
- This phase does not complete the central scenario historical validation or uncertainty-calibration gates.

## Non-goals

No external vision API, cloud image upload, live trading, BUY/SELL enablement, order placement, strategy/risk configuration change, RAG/knowledge database mutation, historical archive repair, model training, probability calibration or automatic strategy promotion.

# Phase 23 — Positioning & Sentiment Intelligence

## North Star capability
Gate 2 — Positioning/Sentiment Intelligence, one specialist among macro, quantitative, intermarket, news, technical, and Price Action domains. Not a trading strategy.

## Official source
CFTC Traders in Financial Futures (TFF), Futures-Only report, filtered to CME EURO FX (contract market code 099741). The TFF classes include Dealer/Intermediary, Asset Manager/Institutional, Leveraged Funds, Other Reportables, and Non-Reportables; this initial slice covers the first three. CFTC positioning is measured Tuesday close and generally released Friday at 3:30 p.m. Eastern; holidays can shift release. Actual publication timestamp is required and must not be inferred. Classification is based on predominant business purpose, not intent of each individual position.

Official references:
- https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
- https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm
- https://publicreporting.cftc.gov/d/gpe5-46if/visualization
- https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm

## Deliverables
- Manual-only source registration with Dealer, Asset Manager, and Leveraged Money net position as percent of open interest.
- CFTCPositioningAdapter validates contract identity, dates, actual publication time, integer positions, positive open interest, duplicate dates, and calculates (long-short)/open_interest*100. It accepts extracted records and performs no network I/O.
- PositioningSentimentIntelligenceEngine enforces effective/published/retrieved as-of filters and freshness; computes net classification, weekly percentage-point change, and historical percentile only after minimum history.
- Optional positioning_sentiment_intelligence research source. Missing and partial data remain explicit; no directional vote.

## Limitations
CME EURO FX futures are not OTC EURUSD and do not represent all global EUR exposure. Futures-only avoids mixing with combined reports. Three of five TFF groups only. Weekly lag makes it unsuitable as an intraday trigger. Percentiles are descriptive, not contrarian signals. No options risk reversals, implied volatility, retail positioning, broker-client sentiment, or social sentiment.

## End-to-end
Official dataset → extracted normalized rows → adapter → Phase 16 ingestion → Phase 15 point-in-time store → specialist → optional Phase 13 research envelope. Fetching remains disabled; no provider HTTP client, scheduler, backfill, or runtime invocation.

## Acceptance
Registry has one source/three products with auto_fetch=false; adapter validation and arithmetic tests pass; future timestamps excluded; stale/missing states explicit; percentile omitted below minimum sample; optional research integration backward-compatible; full regression green on exact PR SHA.

## Safety
No automatic fetching, runtime wiring, spot-wide extrapolation, BUY/SELL, risk/strategy changes, MT5 execution, or RAG database mutation.

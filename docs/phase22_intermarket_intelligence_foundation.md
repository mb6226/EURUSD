# Phase 22 — Intermarket Intelligence Foundation

## North Star capability advanced

Gate 2 — Intermarket Intelligence, built on the Phase 15 point-in-time observation store, Phase 16 controlled ingestion boundary, and Phase 18 quantitative foundations. This phase gives the broader EURUSD brain a first deterministic cross-market relationship specialist. It is independent of Price Action and does not create a trading strategy.

## Repository gap addressed

The repository had no intermarket specialist or normalized intermarket products. EURUSD monitoring was centered on spot candles, while macro/fundamental work had begun to produce point-in-time evidence. There was no tested path to compare EURUSD changes with rates, broad USD, gold, and equity reference series without mixing units, leaking future revisions, or fabricating missing timestamps.

## Deliverables

### 1. Registered logical reference products

The source registry now declares six manually ingested logical products across four publisher/source families:

- `BROKER_SPOT_REFERENCE/EURUSD_SPOT_REFERENCE` — EURUSD benchmark, USD per EUR.
- `FRED_INTERMARKET/US_10Y_TREASURY_YIELD` — US 10-year yield, percent per annum.
- `ECB_INTERMARKET/DE_10Y_GOVERNMENT_YIELD` — German 10-year government yield, percent per annum.
- `FRED_INTERMARKET/USD_BROAD_TRADE_WEIGHTED_INDEX` — broad trade-weighted USD index, index points.
- `LBMA_INTERMARKET/GOLD_USD_TROY_OUNCE` — gold reference price, USD per troy ounce.
- `FRED_INTERMARKET/SP500_INDEX` — S&P 500 reference index, index points.

These are logical canonical products, not a claim that the exact upstream series identifiers, licensing terms, or parser mappings have been finalized. In particular, the broad trade-weighted USD product is **not ICE DXY**. The exact FRED/ECB/LBMA series codes, release/availability metadata, calendar conventions, redistribution rights, and broker feed contract must be verified before any real provider is connected.

All four sources are enabled for explicit manual adapter injection but have `auto_fetch=false`; no scheduler or live provider is activated.

### 2. Shared intermarket adapter

`IntermarketSeriesAdapter` normalizes injected provider-extracted records with:

- timezone-aware `observed_at_utc` and actual `published_at_utc`;
- exact finite Decimal values and registered units;
- stable canonical identity from product plus observation timestamp;
- duplicate timestamp rejection;
- publication-before-observation rejection;
- incremental empty response support and full-history empty response rejection.

Retrieval time is stamped only by the existing `SourceObservationIngestion` boundary. No HTTP client, scraper, credentials, or provider-specific parsing is introduced.

### 3. Deterministic intermarket specialist

`IntermarketIntelligenceEngine` consumes strict as-of rows from the Phase 15 store and reports:

- EURUSD close-to-close percentage changes;
- price/index percentage changes for broad USD, gold, and S&P 500;
- yield changes in basis points for US and German 10-year yields;
- contemporaneous Pearson correlations on exact common timestamps;
- exploratory one-observation lead/lag correlations in both directions;
- aligned sample counts, window boundaries, selected observation IDs, and payload hashes.

The engine selects the latest revision available at the requested cutoff, excludes future-effective, future-published, and future-retrieved rows, enforces series-specific freshness, and never forward-fills or interpolates. Sparse calendars reduce the common sample and are reported as insufficient rather than silently aligned.

Default research window is up to 120 observations with a minimum of 20 aligned returns. Thresholds are injectable for deterministic tests and future research.

### 4. End-to-end path

Validated source registry → explicitly injected provider-extracted records → `IntermarketSeriesAdapter` → `SourceObservationIngestion` → append-only Phase 15 SQLite store → strict `get_as_of` reads → `IntermarketIntelligenceEngine`.

The integration test uses synthetic, timestamped records for all six products and a temporary SQLite database. It validates the data contract and calculation path; it does not validate live provider availability, actual historical correlations, or any trading edge.

## Interpretation limits

- Correlation is descriptive and does not establish causation, structural stability, or predictive power.
- One-period lead/lag correlations are exploratory diagnostics, not forecasts or evidence of a tradable lead.
- Different market calendars, holidays, publication times, and observation frequencies can sharply reduce exact timestamp overlap.
- The US and German yield products are not guaranteed to have identical close conventions or maturities until the provider mappings are selected and documented.
- A broad trade-weighted USD index is not DXY; it must not be displayed or reasoned about as DXY.
- The specialist does not compute a composite score or directional EURUSD vote. Central intelligence must later consider macro, quantitative, technical, news, and other domains with explicit conflict handling.

## Acceptance criteria

- Source registry validates with four new manual sources and six products; all have `auto_fetch=false`.
- Adapter validates timestamps, values, units, identities, duplicates, and stable record keys.
- All six products persist through the existing ingestion service and append-only point-in-time store.
- As-of selection excludes future publication/retrieval/effective observations and selects only revisions available at cutoff.
- Yield changes are in basis points; price/index changes are percentage returns.
- Correlations use exact timestamp intersections only, with no interpolation or forward-fill.
- Insufficient, stale, missing, and misaligned series remain explicit.
- Output includes method, sample counts, source/product identity, observation IDs, payload hashes, and assessment-only authority.
- Focused adapter, engine, integration, registry, ingestion, observation-store, and full regression tests pass on the exact PR head SHA.

## Explicit non-goals and safety

- No automatic HTTP fetching, scraping, scheduler, credentials, provider activation, or historical backfill.
- No final provider series-code mapping or claim of real-time coverage.
- No DXY product, options/futures positioning, CFTC data, order-book/depth, or OTC FX consolidated liquidity claims.
- No causal model, forecast, calibrated probability, regime-dependent relationship model, composite directional score, or trading signal.
- No runtime main-loop wiring until provider mappings, legal use, real publication/availability timestamps, and operational freshness are validated.
- No modification of existing MT5, calendar, news, RAG, or knowledge databases.
- No strategy/WAIT behavior change, BUY/SELL authority, risk change, or MT5 order execution.

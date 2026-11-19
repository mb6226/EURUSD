# Phase 27 — Live Fundamental and Intermarket Runtime Bridge

## North Star capability

Move the existing Macro/Fundamental, Policy Rate, Intermarket, and Positioning/Sentiment specialists from disconnected/manual research modules into the live EURUSD monitoring cycle. The objective is broad multi-domain coverage, not a Price Action-only signal generator.

## Runtime contract

- Read from the existing source_registry append-only point-in-time observation database only.
- Open the database in SQLite read-only mode; if it is absent, do not create it. If its schema is invalid or a read fails, emit explicit degraded specialist reports.
- Retrieve all required products in one batched query for the current snapshot timestamp.
- Require effective_at_utc, published_at_utc, and retrieved_at_utc to be no later than the cycle cutoff. Unknown publication times, future observations, and post-cutoff retrievals are excluded.
- Feed the selected rows to the existing deterministic specialist engines without transforming units or fabricating missing values.
- Preserve source/product IDs, record IDs, publication/effective/retrieval times, and payload hashes in specialist provenance.
- Add the reports to the canonical research source envelope as optional current-cycle context. Missing/unconfigured evidence remains missing; partial coverage remains incomplete; stale/degraded data is not promoted to available.
- Keep all four specialists at assessment/context-only authority. They do not become Fusion directional votes or execution authorities.

## Products queried

- Macro fundamentals: US CPI, US unemployment, euro-area HICP, euro-area unemployment.
- Policy differential: ECB deposit facility rate and Fed target range.
- Intermarket: broker EURUSD spot reference, US 10Y yield, German 10Y yield, broad trade-weighted USD index, gold, and S&P 500.
- Positioning: CFTC TFF Futures-Only Dealer, Asset Manager, and Leveraged Money EURO FX net positioning as a percentage of open interest.

## Acceptance

- One batched as-of read covers the complete 15-product request set.
- Read-only store mode cannot persist or mutate observations and never creates a missing database.
- Runtime tests verify exact source/product mapping, snapshot cutoff propagation, independent specialist failures, and explicit NOT_CONFIGURED state.
- Research synthesis retains specialist identity, evaluation time, provenance, and bounded authority.
- Full regression suite passes.

## Non-goals and limits

- No automatic external fetching, scheduled ingestion, or database writes.
- No RAG/knowledge database access or mutation.
- No new Fusion directional votes, scenario probability, strategy, signal, or trade authority.
- No risk parameter changes, BUY/SELL enablement, or MT5 order placement.
- Runtime wiring does not prove the operational database contains current/licensed data or that providers are connected.
- Intermarket correlations remain descriptive and exact-timestamp-only; CFTC positioning remains a CME futures proxy, not total spot positioning.
- This is an integration vertical slice, not yet the complete central scenario-reasoning brain.

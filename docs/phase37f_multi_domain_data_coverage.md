# Phase 37F ? Multi-Domain Data Coverage

## North Star contribution

This phase broadens the evidence map supporting comprehensive EURUSD intelligence. It adds measurable cross-asset coverage and makes missing domains explicit; it does not turn a registered source into a claim of live data availability or predictive skill.

## Registered product expansion

The existing official FRED/ALFRED vintage adapter now has an explicit allowlist for nine daily reference series:

| Domain | Product | FRED series | Interpretation / limitation |
|---|---|---|---|
| Rates | US 2Y Treasury yield | DGS2 | Daily nominal yield; vintage dates only |
| Rates | US 10Y Treasury yield | DGS10 | Daily nominal yield; vintage dates only |
| Rates | US 10Y real yield | DFII10 | Daily inflation-indexed yield; vintage dates only |
| USD | Broad trade-weighted USD | DTWEXBGS | Broad USD basket, explicitly not ICE DXY |
| Equities | S&P 500 | SP500 | Daily index reference, not intraday futures |
| Volatility | VIX close | VIXCLS | Daily volatility index reference, not FX implied volatility |
| Energy | WTI crude | DCOILWTICO | Daily spot reference, not executable intraday quote |
| Energy | Brent crude | DCOILBRENTEU | Daily spot reference, not executable intraday quote |
| FX benchmark | USD per EUR H.10 reference | DEXUSEU | Daily reference rate, not broker EURUSD spot |

All products preserve ALFRED `realtime_start` / `realtime_end` vintage intervals and raw snapshots. The adapter still requires an explicitly supplied API key; no environment variables are inspected. Date-grain vintage intervals do not establish exact intraday public release times, so these records remain outside strict intraday PIT promotion.

## Coverage assessment

New `source_registry/coverage.py` creates a deterministic registry-only coverage report across 11 required domains: spot FX, monetary policy, macro fundamentals, rates/yields, USD/FX benchmarks, equities/volatility, energy, precious metals, positioning/sentiment, news/geopolitics, and options/cross-currency. It reports registration separately from live availability and lists unmapped products and known gaps.

The current registry contains 9 sources and 23 products. Registration spans 9 of 11 required domains, but this is a catalog measure only?not a live observation coverage ratio. News/geopolitics and options/cross-currency remain unregistered. Gold is catalogued but its LBMA access/licensing and release semantics remain unresolved. The broad USD index is not mislabeled as ICE DXY.

## Explicit exclusions and controls

- No network requests, provider acquisition, API key lookup, database creation/mutation, or source activation occurred.
- `auto_fetch` remains false for every source; the registry's source/product enablement is unchanged.
- FRED daily values are not treated as intraday quotes or exact release-time observations.
- No ICE DXY substitution, unlicensed gold feed, FX options feed, news scraping, or speculative source adapter was introduced.
- Existing strict point-in-time reads and the separate public-availability attestation mode are unchanged.
- No monitor restart, live order, risk change, Vision activation, or RAG/knowledge mutation occurred.

## Validation

Tests verify the nine-product FRED allowlist, registry/provider consistency, deterministic domain coverage, explicit missing domains, date-grain PIT limitations, and zero-network/zero-mutation behavior. Acceptance results: 23 focused regression tests passed; the complete suite passed 637 tests. `compileall`, registry schema/semantic validation, FRED registry/allowlist consistency, SQLite integrity checks and `git diff --check` passed. The operational DBs were inspected for integrity only; no production data was inserted.

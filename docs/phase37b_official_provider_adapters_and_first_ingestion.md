# Phase 37B — Official Provider Adapters & First Historical Ingestion

## North Star capability advanced

This phase advances the canonical multi-domain data foundation and historical evidence layer. It is not a Price Action feature, a trading strategy, or a new directional specialist.

## Provider implementation

### BLS CPI-U all-items

Implemented source_registry/providers/bls.py with:
- HTTPS host allowlisting, bounded response sizes, explicit timeouts, and a browser-style User-Agent;
- BLS Public Data API v1 series mapping CUUR0000SA0;
- original CPI release archive parsing for the unadjusted CPI-U all-items index;
- reference-month to release-date/time mapping;
- comparison of current API value to the value in the original release table;
- original embargo timestamp extraction and conversion from America/New_York to UTC;
- raw response archiving before parsing.

**Live result:** the BLS API response was retrieved and archived. The BLS schedule/archive host returned HTTP 403 from the local machine, including the BLS mirror host. No CPI observations were persisted. This is a fail-closed outcome: no publication timestamp was guessed and no current value was backdated. BLS CPI remains RAW_API_SNAPSHOT_ONLY until the official release evidence can be fetched and cross-checked.

The unadjusted CPI-U series is intentionally chosen rather than a seasonally adjusted index. BLS explains that CPI-U/CPI-W indexes are considered final when released, while seasonally adjusted indexes are revised. Original release-page verification remains mandatory before ingestion.

### CFTC TFF Futures-Only — CME EURO FX

Implemented source_registry/providers/cftc.py with:
- official Socrata dataset gpe5-46if;
- strict contract market code 099741;
- 365-day query window, sorted by report date;
- raw dataset, official 2026 release schedule, and historical special-announcement pages archived before normalization;
- explicit report-date to publication-date join;
- publication time set to the official 3:30 p.m. America/New_York release time;
- fail-closed behavior if a report date cannot be mapped uniquely;
- normalized records for Dealer, Asset Manager, and Leveraged Money net positions as a percentage of open interest.

The special-announcement page is used for the 2025 shutdown/catch-up period. The regular 2026 calendar is used only for dates covered by that official calendar. The October 27, 2026 announcement of a planned semiweekly transition is recorded as a future cadence risk; this ingestion does not infer that the new cadence was already active.

## First historical ingestion — verified result

| Measure | Result |
|---|---:|
| CFTC report rows | 51 |
| Report-date coverage | 2025-11-25 to 2026-11-10 |
| Regular 2026 schedule dates parsed | 52 |
| Special-announcement mappings parsed | 17 |
| Report dates mapped to publication timestamps | 51 / 51 |
| CFTC products ingested | 3 |
| CFTC observations persisted | 153 |
| Raw archive snapshots | 30 |
| Raw payload bytes | 3,013,170 |

Each of the three CFTC products contains 51 observations. Publication timestamps span 2025-12-15 20:30 UTC through 2026-11-16 20:30 UTC. All three products use the same source record identity per report date, while retaining independent product observations and values.

Raw archive: source_registry/operational/raw_snapshots.sqlite

Normalized observation store: source_registry/operational/observations.sqlite

The raw archive is append-only and stores original payload bytes, response headers, request metadata, retrieval timestamp, and SHA-256. Repeated acquisition attempts are retained as separate immutable snapshots where retrieval time or payload differs.

## Critical point-in-time distinction

The CFTC report date, official public publication time, and local retrieval time are separate fields:
- effective_at_utc: Tuesday report date;
- published_at_utc: official public release timestamp;
- retrieved_at_utc: when this machine acquired the historical dataset in November 2026.

The source publication timestamp is reconstructed from official release evidence, not inferred from the Tuesday report date. CFTC states historical data are not backdated after publication. However, the existing observation store's strict get_as_of query also requires retrieved_at_utc <= as_of_utc. Therefore these backfilled observations are not visible to a replay cutoff earlier than the local retrieval time. This preserves the distinction between:
1. **System-knowledge replay** — what this running system had actually retrieved at that historical time; and
2. **Public-source-availability reconstruction** — what the public could have known by the official publication time, based on verified original release evidence.

A separate attested historical-availability read mode is still required before using these backfilled observations in historical public-information replay. Do not bypass the retrieval-time filter or claim complete historical replay readiness in this phase.

Verification confirmed the distinction: each CFTC product returns 51 rows for an as-of cutoff after the local retrieval time, but 0 rows for a historical cutoff before that retrieval time. This is the intended strict system-knowledge behavior, not missing data.

## Other source status

- **BLS:** API raw snapshot archived; local schedule/archive requests returned HTTP 403; no normalized observations.
- **FRED/ALFRED:** no request made; API key was not read or logged. Provider mapping and vintage semantics remain pending.
- **ECB SDMX:** no request made; exact flow/key and revision semantics remain pending.
- **Eurostat:** no historical-vintage reconstruction; latest-only snapshots remain forward-only.
- **LBMA:** no acquisition; licensing/access review remains required.
- **Broker spot/MT5:** no durable one-year broker history was acquired in this phase.
- **Fed/ECB policy rates:** no live policy-release acquisition in this subphase.

## Safety and operational boundaries

- All source auto_fetch flags remain false.
- No background scheduler or automatic refresh was enabled.
- The live monitor was not restarted.
- Vision remains disabled.
- Existing risk settings and alert-only execution boundary are unchanged.
- No order functions, BUY/SELL authority, RAG mutation, or strategy parameter changes were introduced.

## Acceptance evidence

- Provider-focused suite: 10 tests passed.
- Combined Phase 37 acquisition/provider tests: 23 tests passed.
- Full repository suite: 614 tests passed.
- compileall passed for source_registry, eurusd_ai_monitor, tests, and scripts.
- git diff --check passed.

## Official references

- BLS API documentation: https://www.bls.gov/developers/api_signature_v2.htm
- BLS CPI release schedule: https://www.bls.gov/schedule/news_release/cpi.htm
- BLS CPI release archive: https://www.bls.gov/bls/news-release/cpi.htm
- CFTC TFF Futures Only dataset: https://publicreporting.cftc.gov/Commitments-of-Traders/TFF-Futures-Only/gpe5-46if
- CFTC release schedule: https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm
- CFTC historical special announcements: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm
- CFTC October 27, 2026 cadence announcement: https://www.cftc.gov/PressRoom/PressReleases/9316-26

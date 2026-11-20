# EURUSD Data Completion Backfill — 2026-11-20

## Outcome

This operational data-completion run expanded the local Headway market archive and the official-provider raw snapshot archive. It did not promote unverified historical values into the point-in-time observation store.

## Headway MT5 spot history

- Broker server: `Headway-Real`; symbol: `EURUSD`.
- Chart price basis verified as `BID`.
- Terminal `Max bars`: 100,000.
- M1: 99,999 bars fetched, from 2026-08-14 00:16 UTC through 2026-11-20 06:53 UTC at retrieval; archive now contains 100,004 M1 candles.
- M5: 99,999 bars fetched, from 2025-07-18 00:25 UTC through 2026-11-20 06:50 UTC at retrieval; archive contains 100,000 M5 candles.
- 199,998 bars received: 198,756 inserted, 2 updated, 1,240 unchanged; no candle revisions were detected in this batch.
- Market archive schema v4 integrity: `ok`; 201,333 immutable candle versions and 1,459 ingestion runs.
- The spread field is stored in MT5 points. Average observed spread was 9.22 points on M1 and 9.48 points on M5 (approximately 0.922 and 0.948 pips for this five-digit EURUSD symbol).
- Gap audit found 547 M1 and 203 M5 intervals longer than 1.5 bars. The larger gaps include weekends; shorter gaps include rollover/maintenance and possible low/no-tick periods. No gaps were synthetically filled.

The 100,000-bar terminal limit constrains the oldest accessible range. M1 history currently covers roughly three months; M5 reaches back to July 2025. Older data requires a separately controlled increase of the terminal history limit and a fresh coverage audit.

### Tick history

- A recent sample returned 585 Bid/Ask ticks.
- A prior-day sample returned 10 ticks.
- A one-year-back sample did not complete within the bounded audit and remains unverified.
- No long-range tick archive was created. Do not infer historical Ask OHLC from Bid bars and bar-level spread.
- MT5 tick volume is broker tick activity, not centralized global FX traded volume.

## Fundamental and intermarket raw history

Twenty-one new immutable raw snapshots were archived, bringing the raw snapshot archive to 61 records (5,988,376 payload bytes). The new snapshots cover:

- FRED: 9 series (2Y/10Y and real yields, broad USD, S&P 500, VIX, WTI, Brent and the daily EUR/USD reference rate); 82,238 valid observations in the current revised CSV views.
- Eurostat: HICP, 312 monthly values from 2000-01 through 2025-12; unemployment, 321 monthly values from 2000-01 through 2026-10.
- BLS: CPI and unemployment, 322 monthly values each from 2000-01 through 2026-10.
- Federal Reserve FOMC and ECB policy-rate history pages, archived as raw HTML.

The raw snapshots retain retrieval time, source URL, payload hash and request metadata. They are not normalized PIT observations:

- FRED public CSV is the latest revised series, not an ALFRED vintage replay. The explicit-key ALFRED adapter was not called because no API key was supplied to it.
- BLS API history was retrievable, but the official CPI release calendar and original-release archive endpoints returned HTTP 403. Exact original release/embargo timestamps could not be verified.
- Eurostat historical values do not by themselves establish exact intraday publication times or vintage availability.
- Fed/ECB effective dates are not treated as publication timestamps.

## Existing PIT evidence

The observation store remains at 153 verified CFTC TFF observations: 51 each for Dealer, Asset Manager and Leveraged Money. The latest report date in the archive is 2026-11-10, with the latest verified publication timestamp 2026-11-16 20:30 UTC.

The macro calendar currently contains 196 events.

## Replay and evaluation boundary

Phase45 remains `REPLAY_WINDOW_REQUIRED`; Phase51 remains `BLOCKED`. No matured out-of-sample outcomes were created by this backfill.

All backfilled candles and raw provider snapshots retain their actual retrieval/observation timestamps. They are not made visible to strict system-knowledge replay before retrieval. No historical publication timestamps, original values or vintages were fabricated. A separate public-source-availability policy with evidence and revision semantics is required before using backfilled market history at historical cutoffs.

## Safety and runtime

- Market archive, raw snapshot archive, observation store and calendar archive integrity checks all pass.
- All registered provider auto-fetch flags remain false.
- The alert-only monitor was left running; Vision remains disabled.
- No live orders, risk-setting changes or RAG database mutations were made.

## Next evidence-first work

1. Raise the MT5 history limit only in a controlled terminal-maintenance window, then extend M1 and M5 coverage and re-audit gaps.
2. Determine whether Headway exposes a reliable multi-month/year tick-history range; if it does, implement an immutable tick archive before claiming Bid/Ask microstructure coverage.
3. Resolve BLS release-calendar/archive access and acquire explicit ALFRED vintages / exact publication-time evidence for the remaining macro series.
4. Integrate only PIT-eligible observations into strict replay; then define a formal replay window and wait for matured OOS outcomes before calibration or learning claims.

## Additional user-supplied MT5 CSV history import

Two Headway MT5 chart-history exports were found in the terminal's MQL5/Files directory and audited:

- EURUSD_M1_202608131731_202611200655.csv: 100,398 rows; no malformed rows, duplicate timestamps or ordering defects.
- EURUSD_M5_202511200005_202611200655.csv: 74,406 rows; no malformed rows, duplicate timestamps or ordering defects.

The CSV timestamps were checked against overlapping Headway MT5 Python copy_rates candles at identical timestamps. UTC alignment was retained. The Windows file modification clock was not used as the data-observation timestamp because it differed from the MT5/Python clock.

Only 397 missing M1 bars (2026-08-13 17:31 through 2026-08-14 00:15 UTC) were imported under source ID HEADWAY_MT5_CSV_HISTORY_EXPORT, with immutable candle versions, SHA-256 file provenance, and the actual ingestion time. The M5 export was already fully covered by the archive, so no duplicate M5 rows were inserted. The one differing final candle in each file was preserved rather than overwriting the newer live archive version.

A consistent pre-import backup was created at market_data.sqlite.pre-csv-import-20261120T071200Z.bak and its SQLite integrity check passed. Post-import market archive integrity also passed. The monitor remained running.

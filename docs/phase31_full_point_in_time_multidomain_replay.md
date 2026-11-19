# Phase 31 — Full Point-in-Time Data Reconstruction & Multi-Domain Historical Replay

## North Star

Build a trustworthy historical research loop for the comprehensive EURUSD market-intelligence system. At a historical evaluation timestamp, reconstruct only evidence that can be proven to have been available then, preserve missing/uncertain source coverage, and reassess archived specialist reports through the central multi-domain scenario engine.

## Implemented vertical slice

### PointInTimeReconstructionEngine

The new read-only engine reconstructs four evidence families at an explicit UTC `as_of_utc`:

1. **Broker EURUSD candles (M1/M5):** reads the current market archive and reverses candle revisions detected after the replay timestamp. It uses immutable first-seen/last-seen timestamps to prove that a candle was closed and observed by the requested instant. It excludes bars whose closure timing cannot be proven, future first-seen bars, invalid reconstructed OHLC, and all samples if the relevant revision scan exceeds its safety limit.
2. **Source-registry observations:** delegates to the existing append-only `PointInTimeObservationStore.get_many_as_of`, requiring effective, published and retrieved timestamps no later than the requested instant. This can cover macro fundamentals, policy rates, intermarket, positioning, quantitative and liquidity products when the caller explicitly supplies the source/product registry pairs.
3. **News:** reconstructs the latest semantic version at or before the requested instant from recorded news revisions. Because unchanged refreshes are not separately versioned and the news table has no immutable first-seen field, records whose pre-as-of retrieval cannot be proven are excluded.
4. **Macro calendar:** reverses event revisions after the requested instant and uses immutable `first_seen_at_utc` as the event-availability boundary. Mutable calendar source-health state is deliberately not represented as historical truth.

Every component returns its own status, exclusions, counts and limitations. Missing stores or unavailable evidence are explicit; no current values are backdated.

### Multi-domain historical replay

`PointInTimeReconstructionEngine.replay` accepts archived replay points with original `evaluated_at_utc` timestamps and archived specialist reports. It independently reconstructs the evidence bundle for each timestamp, rejects future-dated or mismatched specialist reports, and reassesses the remaining archived reports with the existing `CentralScenarioIntelligenceEngine`.

The JSONL runtime adapter reads either a `specialist_reports` mapping or the existing monitor payload's top-level specialist fields, using `market_context.timestamp_utc` as the cycle timestamp. It never modifies source logs.

The reconstructed raw evidence bundle is returned alongside the central scenario reassessment; it is not silently converted into specialist reports or injected as new directional votes. The central engine reassesses only archived specialist report objects that pass timestamp and identity checks. This explicit separation prevents the replay layer from inventing transformations that have not yet been validated.

## Crucial interpretation boundary

This phase does **not** regenerate technical, Price Action, regime, macro, news or other specialist algorithms from raw historical inputs. It reconstructs archived data/evidence and reassesses archived specialist reports. A missing historical specialist report remains missing; it is never replaced with today's report.

The source-registry observation store is point-in-time capable, but only products actually ingested into that store are available. The Phase 21–24 manual specialist observations and the Phase 27 live runtime do not imply that complete historical source snapshots exist for every domain/time. Archive coverage must be measured before calling a replay complete.

## Point-in-time controls

- All requested timestamps must be timezone-aware and normalized to UTC.
- No evaluation point may exceed the requested replay window.
- Observation effective, publication and retrieval timestamps are all bounded by the evaluation time.
- Candle revisions after the evaluation time are rolled back from append-only old-value deltas; scan overflow or non-monotonic revision timestamps fail closed for affected data.
- A candle is included only when the archive proves it had closed and been observed by the evaluation timestamp.
- News uses the latest semantic revision proven at or before the evaluation time; unprovable unchanged-refresh history is excluded and non-monotonic revision timelines make the component unavailable.
- Calendar events use first-seen time and append-only revision history; non-monotonic revision timelines make the component unavailable.
- Specialist reports with future timestamps or conflicting broker/symbol identity are rejected.
- All SQLite archive reads use read-only connections; no source logs or databases are written.

## Acceptance

- Deterministic tests for candle revision rollback, candle closure timing, revision scan overflow, publication/retrieval/effective-time gating, news/calendar revision rollback, future specialist-report rejection, replay window validation, JSONL extraction and source-log immutability.
- Full repository regression, compile checks and diff validation on the exact PR head before merge.

## Explicit non-goals / remaining gaps

- No live fetching, data backfill, archive repair, DB mutation or RAG/knowledge mutation.
- No synthetic or backdated specialist reports.
- No model training, probability calibration, source reliability weighting or automated learning.
- No strategy optimization, Fusion vote change, BUY/SELL enablement, risk change or order execution.
- No trading P/L or profitability claim.
- Full historical specialist recomputation requires point-in-time feature snapshots and deterministic versioned specialist runtimes; it remains a later phase.
- News unchanged refreshes are not fully versioned; a future append-only news observation schema should preserve every fetch/version.
- Market candle closure events are inferred conservatively from first/last-seen evidence; a dedicated append-only closed-bar observation event would remove the remaining ambiguity.
- Calendar source-health snapshots and full provider/source coverage manifests remain future work.

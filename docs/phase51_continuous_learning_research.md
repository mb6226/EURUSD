# Phase 51 — Continuous Learning & Research Governance

## Purpose
Establish a repeatable, evidence-first research loop for the comprehensive multi-domain EURUSD intelligence system. This is governance and reproducibility infrastructure, not an automatic model trainer.

## Research-cycle contract
- Join only a COMPLETE Phase45 strict system-knowledge replay, Phase49 walk-forward validation and Phase50 cross-domain attribution that share the exact replay ID and source-history SHA-256.
- Require all six Phase45 PIT integrity flags.
- Gate 15M, 1H and 4H independently. Default minimum: two non-overlapping OOS folds and 100 completed outcomes per horizon, plus at least 100 matching attribution records.
- Passing means eligible for governed research review only. It is not proof of profitability, predictive skill or permission to change live models.

## Reproducible experiment manifests
Each experiment pins a hypothesis, engine identity/version, code SHA-256, parameter SHA-256, replay ID, source-history SHA-256 and timezone-aware creation timestamp. Experiment identity is deterministic.

## Append-only research ledger
The explicit ContinuousLearningResearchStore records immutable experiment manifests, evaluation reports and human review events. It rejects replay/source mismatches, unknown experiments and unsupported promotion states. SQLite triggers prevent UPDATE/DELETE. The ledger is not created as a side effect of a blocked production preflight.

## Safety
No automatic training, parameter tuning, model promotion, probability/confidence synthesis, live model mutation, order execution or risk change. Research candidates remain RESEARCH_ONLY; human review and separate authorization are mandatory.

## Current production result
Blocked: Phase45 replay has no immutable candle-version ledger. Phase49 and Phase50 are also blocked, with no completed production replay or contemporaneous domain context. Synthetic fixtures exercise logic only and are not represented as EURUSD performance.

## Related infrastructure work
scripts/migrate_market_archive_v4.py provides a read-only default preflight and explicit backup-first schema-v3 to v4 migration. It preserves existing legacy candles as unversioned and does not fabricate historical versions. A controlled v4 monitor restart and fresh-ingestion verification remain necessary after migration.


## Live archive activation verification

- The schema-v3 archive was backed up and migrated atomically to schema v4. The backup remains schema v3 and passes SQLite integrity validation.
- Existing 1,180 legacy candles at migration time remain unversioned; zero legacy rows were promoted or assigned invented observation timestamps.
- The alert-only monitor was restarted using the v4 ingestion code. Fresh MT5_COPY_RATES runs are now appending immutable M1/M5 candle versions for Headway-Real EURUSD. The live archive integrity check passes.
- A bounded, non-persisted Phase45 smoke replay over the first v4 observation window produced 2 forecast cutoffs and 6 baseline forecast records from real versioned MT5 evidence. Zero target outcomes had matured at the smoke evaluation cutoff, so no error, walk-forward or attribution metrics are claimed.
- Production Phase45 report is now REPLAY_WINDOW_REQUIRED rather than CANDLE_VERSION_LEDGER_UNAVAILABLE. A complete scored replay still requires a specified window and sufficient future time for target candles to close and be observed, especially the 1H/4H horizons.


## Replay-to-evaluation integration hardening

Phase45 keeps compact report files and stores full completed forecast records in its immutable research ledger. A new read-only ForecastReplayLedger.load_run(replay_id) restores the exact replay payload from that ledger without creating or mutating it. Phase47/48/49/50 runners now load the full immutable records by replay ID when the compact Phase45 report is COMPLETE; if the ledger is absent or the replay/source binding is invalid, downstream evaluation fails closed rather than analyzing a five-record preview or silently missing records.


### Final verification snapshot (2026-11-20)

- Market archive: schema v4, SQLite integrity ok, 1,024 immutable candle versions across Headway-Real EURUSD M1 (517) and M5 (507), across 330 ingestion runs at report time.
- Pre-migration v3 backup: schema v3, 1,180 candles, integrity ok. The current latest-candle projection has 1,194 rows; zero pre-migration rows were promoted into the version ledger.
- Phase45 bounded smoke: 2 cutoffs, 6 forecasts, 0 matured outcomes, not persisted.
- Full repository suite: 820 tests passed; Phase51 focused suite: 13 passed; replay ledger round-trip/read-only tests: 2 passed; compileall and diff checks passed.
- Phase45/47/48/49/50/51 production evaluation remains blocked pending a defined replay window and matured outcomes; no live learning or metrics were applied.

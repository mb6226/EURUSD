# Phase 33 — Immutable Specialist Execution Provenance & Feature Snapshot Fingerprints

## North Star

Strengthen the historical research loop for the comprehensive multi-domain EURUSD intelligence system. Every replayed specialist conclusion must be attributable to the exact reconstructed market features, reconstructed evidence bundle, report payload and engine source file that were used at that historical evaluation timestamp.

## Repository gap

Phase 32 re-executes deterministic specialists from Phase 31 point-in-time evidence, but its output did not carry immutable fingerprints for the feature snapshot, reconstructed evidence, specialist report or engine implementation source. Algorithm and parameter labels alone are not sufficient to distinguish changed inputs or changed code behind an unchanged version label.

## Implementation

Each specialist report emitted by `DeterministicHistoricalSpecialistReplayEngine` now includes an `execution_provenance` object containing:

- A versioned provenance schema and specialist identity.
- Original evaluation timestamp, engine module and class.
- SHA-256 of the engine's implementation source file when accessible.
- Declared algorithm and parameter versions when supplied by the engine/report.
- SHA-256 of a canonical M1/M5 MarketSnapshot payload, including OHLCV, broker/symbol identity, timestamps and quality state.
- SHA-256 of the Phase 31 M1/M5 reconstructed evidence reports.
- SHA-256 of the specialist report payload before provenance is attached.
- Input provenance scope and an explicit `historical_version_parity=NOT_CLAIMED` marker.

Canonical JSON serialization uses sorted keys and stable separators. Fingerprints are deterministic for identical inputs and change when the reconstructed candle feature payload changes. Quality-blocked and not-configured specialists also retain explicit provenance status; no specialist is executed when snapshot quality is invalid.

## Integration

The provenance is attached directly to each specialist report before it is passed to `CentralScenarioIntelligenceEngine`. It therefore remains visible in the central evidence ledger and the JSONL replay output. No separate database, source archive, RAG store or persistent registry is created or mutated.

## Limitations

- The implementation hash covers the individual engine source file, not its complete transitive dependency closure or Python environment.
- The current algorithm and parameter versions are recorded; this phase does not dynamically load historical code or select historical parameter sets.
- Fundamental specialists' provenance is bounded by the point-in-time observation/report fields exposed by their current contracts. Raw observation snapshots are not copied into the replay.
- A fingerprint proves identity of captured bytes/payloads; it does not prove source correctness, model quality, scenario accuracy or trading profitability.
- Exact historical code/parameter parity still requires an immutable algorithm registry, archived dependency/build manifests and feature/observation snapshots.

## Acceptance

- Deterministic fingerprints for identical replay inputs.
- Feature fingerprint changes when reconstructed OHLCV input changes.
- Per-specialist provenance includes implementation, version, feature, evidence and output fingerprints where available.
- Invalid snapshot quality continues to block all specialist execution.
- Focused Phase 33 tests, full repository regression, compile checks and `git diff --check` on the exact PR head.

## Non-goals

No live data fetching, archive repair, database/RAG mutation, historical code checkout, model training, probability calibration, source reliability weighting, strategy optimization, BUY/SELL authority, risk changes or order execution.

# Phase 14 — Evidence Lineage & Research Cycle Integrity

## Objective

Make the existing M1/M5 evidence chain auditable within each monitor cycle. This is a deterministic integrity layer over the current snapshot and specialist payloads, not a new signal generator.

## Evidence identity

A candle ID uses the existing EvidenceRef identity format:

`broker_server|symbol|timeframe|UTC-open-time`

The runtime constructs an ephemeral inventory from the immutable MarketSnapshot. Each record carries broker, symbol, timeframe, open time, and close time. No database schema or stored market data is changed.

## Specialist lineage contracts

- Technical analysis and Fusion references must resolve to M5 evidence.
- Setup-pattern references must resolve to M1 evidence.
- Market-regime and Price Action lifecycle references may resolve to M1 and/or M5 evidence according to their existing contracts.
- Every referenced candle must exist in the current snapshot inventory.
- Evidence objects with explicit candle metadata must match the inventory identity and timeframe; confirmation must occur no earlier than candle close and no later than the cycle timestamp.
- Missing or unavailable specialists are reported as unavailable/partial; an explicit reference that cannot be resolved is a lineage violation.

## Output

A top-level `evidence_lineage` report contains:

- status: `TRACEABLE`, `PARTIAL`, or `DEGRADED`;
- deterministic inventory counts and SHA-256 digest;
- per-specialist reference counts, resolved references, and reason codes;
- total reference coverage and orphaned inventory count;
- explicit assessment-only / no-trade / no-order authority flags.

Orphaned candles are informational and do not fail the audit. The inventory digest covers sorted candle IDs only; it is not a cryptographic signature of OHLC values or source authenticity.

## Runtime and safety boundaries

The report is built from the same in-memory MarketSnapshot already used by existing engines. It is published beside the original specialist payloads. It performs no network or database I/O and writes no data. It does not modify Fusion, setup, session eligibility, risk, SL/TP, legacy decision evaluation, MT5 connectivity, RAG, or learning. A traceable lineage report is not an entry signal or execution permission.

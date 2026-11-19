# Phase 20 — Point-in-Time ECB/Fed Policy-Rate Differential Specialist

## North Star capability

Gate 2 — Macro/Fundamental Intelligence, built on the Gate 1 canonical point-in-time data plane. This is a cross-currency fundamental feature, not a Price Action component.

## Gap addressed

Phases 17 and 19 provide ECB policy-rate and Fed target-range observations; Phases 15–16 preserve publication, retrieval, effective timestamps and immutable revisions. The repository lacked a deterministic specialist to align those two sources as-of a historical decision time.

## Deliverable

`PolicyRateDifferentialEngine` consumes stored observations from the ECB deposit-facility product and the Fed target-range product. It selects the latest eligible effective observation on each side, requires known publication and retrieval timestamps no later than the requested cutoff, enforces a caller-configured maximum effective age, and calculates:

`USD minus EUR = Fed target range − ECB deposit-facility rate`

The Fed range remains a range after subtraction. No midpoint is fabricated. The report contains both source identities, timestamps, record identifiers and payload hashes. Missing or stale evidence returns explicit UNAVAILABLE/STALE status; malformed identity, unit, timestamp or numeric values fail closed.

## Why these instruments

The ECB deposit-facility rate is explicitly chosen as the EUR reference because it is the ECB's deposit-facility policy rate; it is not silently interchanged with the main refinancing or marginal lending rates. The Fed's target is a range, so the output remains an interval. This is a transparent reference spread, not a claim that both central-bank frameworks are identical.

## Acceptance

- Exact point-in-time filtering for effective, publication and retrieval timestamps.
- Latest eligible effective observation and latest known revision selected.
- Missing, unknown-publication, future, stale, malformed, wrong-unit and wrong-identity evidence never produces an available spread.
- Decimal arithmetic preserves the Fed range without midpoint conversion.
- Provenance records both input sources and payload hashes.
- Deterministic tests cover valid, missing, stale, revision, malformed and look-ahead cases.

## Explicit non-goals

No automatic runtime invocation, provider activation, HTTP fetch, source scraping, historical backfill, policy-path expectation, yield-curve analysis, macro-surprise model, directional EURUSD forecast, probability, signal, strategy, risk change, BUY/SELL, MT5 execution, or RAG/knowledge DB mutation. This is an assessment-only input for a future fundamental specialist.

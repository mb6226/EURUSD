# Phase 13.4 — Research Source Provenance Validation

## Purpose

Harden the boundary between the eight specialist outputs produced during one runtime cycle and the Phase 13 unified research report. The runtime must not make incomplete provenance appear valid by substituting the cycle timestamp for a specialist timestamp or by overwriting an explicit specialist identity with the outer cycle identity.

## Source envelope

`build_research_intelligence_sources` is the single adapter for the eight Phase 13 sources:

- fusion assessment;
- market regime intelligence;
- price-action lifecycle;
- setup assessment;
- session eligibility;
- setup outcome observation;
- statistical outcome evaluation;
- regime-conditioned outcome evaluation.

For each source it preserves the specialist payload and its explicit `evaluated_at_utc`. A missing timestamp remains missing and is passed to `ResearchIntelligenceEngine`, which marks the synthesis `DEGRADED` with a source-specific timestamp reason. The adapter never substitutes the cycle timestamp.

The broker and symbol envelope uses explicit payload identity when the specialist publishes it. That identity is not overwritten; a mismatch is detected by the synthesis engine. Components that do not publish their own identity inherit the broker and symbol of the runtime cycle that invoked them.

## Runtime integration

`main.py` delegates source-envelope construction to the adapter and continues to pass the same eight specialist payloads to the Phase 13 engine. The original specialist outputs remain published unchanged alongside `research_intelligence`.

## Validation guarantees

- Exactly eight named source entries are constructed in a stable order.
- A missing or malformed specialist timestamp cannot be disguised as fresh evidence.
- Explicit broker/symbol identity mismatches remain visible to the engine.
- Invalid cycle identity is rejected at the adapter boundary.
- Historical reports remain subject to report-evaluation freshness, not the age of underlying historical observations.
- Research output remains assessment-only; no signal, trade authority, or order execution is introduced.

## Non-goals

No strategy, risk reservation, persistence schema, RAG store, learning behavior, MT5 connector, or live order behavior is changed. This phase validates source provenance only; it does not claim live-runtime or MT5 acceptance.

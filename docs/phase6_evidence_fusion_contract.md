# Phase 6 — Evidence-Based Intelligence Fusion

## Purpose and safety boundary

Phase 6 introduces a deterministic, typed contract for combining specialist evidence. It does **not** implement the user's complete Trend → Correction → Rejection → Pullback → Entry strategy and does not issue BUY/SELL signals, calculate orders, or execute trades.

The existing legacy evaluator remains the authoritative published decision path during this phase. Fusion is published beside it as an assessment-only diagnostic so that its behavior can be reviewed without changing existing alert semantics.

## Specialist contracts

| Specialist | Directional vote | Required interpretation |
|---|---:|---|
| Technical | Yes | Closed-candle M5 structure: UP, DOWN, NEUTRAL (range/unknown) |
| Price Action | Yes, only for confirmed active correction lifecycle | Underlying trend direction; candidate, absent, terminal, or blocked lifecycle is not a vote |
| Macro Calendar | No | Source health and high-impact event context only |
| News | No | Official-source health and article context only; no sentiment inference |

Macro and News are structurally prevented from casting a directional vote. Statistical, fundamental, vision, and session specialists are not fabricated or silently treated as neutral; they remain out of scope until their own contracts and validated evidence sources exist.

## Freshness, provenance, and failure behavior

Each specialist contributes a status, evaluation timestamp, source identifiers, evidence identifiers, reason codes, and context flags. The fusion engine rejects missing, unavailable, degraded, stale, or future-dated specialist evidence. The default maximum age is 300 seconds and is configurable when constructing the engine.

Evidence IDs are opaque references supplied by the caller. The fusion engine does not rewrite, infer, or manufacture provenance. Duplicate specialists are rejected. Missing or degraded evidence fails closed.

## Directional agreement

Only Technical and confirmed Price Action evidence vote direction. Two aligned votes produce an assessment bias and READY_FOR_RULES. Opposing votes produce CONFLICT. A missing/non-directional vote produces INCOMPLETE. These are evidence classifications, not calibrated probabilities or trade recommendations.

No confidence probability is emitted: the current project has no calibrated confidence model or sufficient outcome dataset. Agreement is not presented as probability.

## Runtime integration

The monitor publishes `fusion_assessment` alongside the existing `decision`. The legacy evaluator and its WAIT behavior remain unchanged. A READY_FOR_RULES result means only that the four configured specialist evidence contracts passed this phase's checks; it does not mean a setup is tradable.

## Explicit non-goals

- No BUY/SELL generation or order execution.
- No LLM decision authority.
- No news sentiment/directional vote.
- No automatic risk parameter changes.
- No online learning or RAG mutation.
- No statistical/fundamental/vision evidence until independently implemented and validated.
- No change to the legacy evaluator's decision output.

## Deterministic test coverage

Tests cover alignment, conflict, insufficient direction, missing/degraded/unavailable evidence, stale and future timestamps, source-role restrictions, duplicate/unknown specialists, provenance preservation, deterministic serialization, and the permanent WAIT/no-trade boundary.

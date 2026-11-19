# Phase 25 — Central Research Source-Envelope Completion

## North Star
Cross-domain central intelligence: ensure every specialist already recognized by the research synthesis contract can pass through the canonical source envelope with identity and timestamps intact.

## Concrete gap
After Phase 24, `ResearchIntelligenceEngine` recognized `liquidity_microstructure_intelligence` as an optional current-cycle source, but `RESEARCH_SOURCE_NAMES` in `research_intelligence_sources.py` did not include it. A caller could supply the specialist payload and the source-envelope builder silently omitted it. The engine then reported it as missing rather than consuming the supplied evidence.

## Change
- Add liquidity microstructure to the canonical research source-envelope names.
- Preserve the supplied payload, broker/symbol identity, and specialist evaluation timestamp through the same validation path as other specialists.
- Preserve explicit absence as a `None` payload with cycle identity; absence is not fabricated availability.
- Add regression coverage for both supplied and missing optional liquidity evidence.

## Integration
This closes the Phase 24 → source envelope → ResearchIntelligenceEngine contract gap. It does not activate the specialist in the live monitoring loop. The runtime still has no live liquidity sampling, and missing evidence remains visibly missing.

## Acceptance
- Supplied liquidity payload survives envelope construction with timestamp and identity unchanged.
- Missing liquidity payload remains explicit and does not become an available assessment.
- Existing source identity, timestamp, and research synthesis tests remain green.
- Full repository regression suite passes on the exact PR head SHA.

## Non-goals
- No MT5 live sampling or automatic source ingestion.
- No Fusion directional vote or signal authority.
- No changes to strategy, risk, WAIT behavior, or order execution.
- No RAG/knowledge database mutation.
- No claim that all macro, quantitative, intermarket, positioning, and liquidity specialists are runtime-integrated.

## Next architectural priority
Move from isolated specialist foundations toward a controlled central-integration vertical slice: inventory each specialist's actual runtime availability, define applicability and freshness contracts, and connect only evidence that is genuinely produced in the cycle. Keep absent providers explicit; do not create synthetic payloads to make the report look complete.

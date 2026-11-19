# Phase 13.5 — Research Authority Consistency Audit

## Purpose

Add a deterministic audit to the Phase 13 research synthesis boundary. The audit detects explicit authority claims in any of the eight Phase 6–12 specialist payloads that contradict the research-only architecture.

## Contract

For every source payload, validate authority fields only when explicitly present:

- `decision_authority`: `ASSESSMENT_ONLY` or `CONTEXT_ONLY`
- `trade_authority`: `NONE`
- `order_execution`: `DISABLED`
- `trade_execution`: `DISABLED`
- `entry_eligibility`: `BLOCKED`
- `decision`: `WAIT`

Missing fields are not interpreted as permission and do not by themselves fail the audit. Values are normalized by trimming whitespace and comparing case-insensitively. Unknown or escalated values are violations.

## Output

The unified report adds:

- `authority_audit.status`: `PASS` or `VIOLATION`
- `authority_audit.violations`: deterministic source/field/actual/expected records
- Per-source `source_manifest[].authority_violations`
- Stable reason code `<SOURCE>_AUTHORITY_CONTRACT_VIOLATION`

Any explicit authority violation forces the overall research report to `DEGRADED`. The audit never repairs, rewrites, or overrides the specialist payload. The original source payload remains available in the runtime publication.

## Safety boundaries

This phase adds no signal logic, strategy rules, order functions, MT5 calls, risk changes, database writes, learning, or RAG changes. It is a read-only integrity check. It cannot grant trade authority; the unified report continues to publish `decision_authority=ASSESSMENT_ONLY`, `trade_authority=NONE`, and `order_execution=DISABLED`.

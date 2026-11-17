# Integration notes

- This package is intentionally an add-on. It does not modify the existing v1 `main.py`,
  MT5 connector, signal manager, or screenshot exporter.
- Call `from knowledge_v2.answer import ask` from another module when ready.
- The return value is `{ "answer": str, "sources": [...] }`.
- Do not let RAG output directly trigger BUY/SELL. The decision engine must independently
  validate claims against current MT5 data, spread, session, event risk, and user rules.
- For the next iteration, add source-specific fetchers with explicit rate limits, source
  timestamps, licensing checks, and data freshness monitoring.

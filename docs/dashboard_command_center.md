# EURUSD Command Center Dashboard

Read-only local dashboard for the EURUSD-AI-Intelligent-Market-Brain project.

## Run
Use the repository's existing Python environment:
```powershell
& "C:\Users\mahdi\Downloads\eurusd_ai_monitor_starter_v1\.venv\Scripts\python.exe" scripts\dashboard_server.py --host 127.0.0.1 --port 8765
```
Open http://127.0.0.1:8765

## Monitoring coverage
- Latest live monitor record; all top-level payload keys are discovered and rendered automatically.
- Specialist reports emitted by the live monitor, including fusion, central scenarios, market regime, statistics, liquidity, macro, policy-rate differential, intermarket, positioning, calendar, news, technical and setup/session outputs when present.
- Recent monitor history (bounded tail read; 10 records) with decision, fusion/scenario status and market-quality validity timeline.
- EURUSD M1 recent close chart.
- All JSON reports in reports/ (Phase 37–51), with raw payload inspection.
- Market archive integrity/table counts plus read-only integrity, row counts and source/product coverage for the raw provider snapshot archive, PIT observation store and economic calendar store.
- Runtime config, Python process list and monitor log metadata.

## Performance and truthfulness
- Monitor logs can become large; the dashboard reads a bounded tail only and never loads the entire JSONL file into memory.
- Refresh interval: 10 seconds.
- Missing live payload fields are omitted or marked unavailable; status is derived from the emitted payload, not guessed.
- Research report statuses are shown as recorded. A completed smoke test is not represented as production validation.

## Safety
The dashboard is read-only. It does not place trades, modify risk, activate external fetching, or mutate RAG/research stores.

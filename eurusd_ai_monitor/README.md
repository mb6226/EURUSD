# EURUSD AI Monitor — Starter v1

Alert-only starter for MetaTrader 5 + Python. It monitors EURUSD on M1 and M5.

## Important status
- MT5 data connector: implemented.
- M1/M5 OHLC retrieval and CSV snapshots: implemented.
- Basic provisional range comparison: implemented for diagnostics only.
- Chart screenshot exporter EA: included; attach it to one EURUSD M1 chart and one EURUSD M5 chart.
- Actual vision-model interpretation: NOT YET CONNECTED.
- Technical structure and the persisted Price Action lifecycle are implemented with fail-closed recovery.
- Phase 6 Evidence Fusion is integrated as an assessment-only diagnostic; the legacy decision path remains unchanged and WAIT-only.
- Macro calendar ingestion is implemented for official BLS, BEA, ECB, and Federal Reserve schedule sources; it is context-only and has no trade authority.
- Official-source News Intelligence is implemented as context-only RSS/Atom ingestion; general fundamental analysis, statistical research, and learning modules remain scaffolds.
- User's full Trend → Correction → Rejection → Pullback rules: NOT YET CODED.
- BUY/SELL signal generation and order execution: DISABLED. The rules engine intentionally returns WAIT.

Do not use this starter as a trading system or assume it has validated profitability.

## Project layout
- `engines/`: MT5 data, market context, Technical Engine, Price Action lifecycle/runtime, macro calendar context, screenshot validation, and remaining analysis-engine placeholders.
- `alerts/`: JSONL signal logging.
- `data/`: market snapshots, independent SQLite macro calendar and news stores, screenshot, and historical-data folders.
- `knowledge/`: reserved for reviewed rules and analysis references.
- `memory/`: reserved for future SQLite stores and analysis history.
- `learning/`: feedback and evaluation placeholders; no online learning is active.
- `logs/`: monitor output.
- `mt5_ea/`: MetaTrader screenshot-exporter EA.

The knowledge folders remain placeholders. The macro calendar uses its own SQLite database under `data/calendar`; it does not share or mutate the market-data or RAG databases. Screenshots continue to be read from MT5's `MQL5/Files` directory; they are not currently copied into `data/screenshots`.

## Requirements
- Windows desktop with MetaTrader 5 installed and logged in to a demo account.
- Python 3.10+ (64-bit recommended).
- MT5 terminal must be running.

## Setup
1. Extract the ZIP to a normal folder, e.g. `C:\EURUSD_AI_Monitor`.
2. Install Python 3.10+ (64-bit recommended) if it is not already installed. On Windows, select **Add python.exe to PATH** in the installer.
3. Open a new PowerShell terminal in that folder and verify Python is available:
   `python --version`
   If this opens the Microsoft Store or Python is not found, install Python from [python.org](https://www.python.org/downloads/windows/) and, if needed, turn off the `python.exe` and `python3.exe` app execution aliases in **Settings → Apps → Advanced app settings → App execution aliases**.
4. Create and activate a virtual environment:
   `python -m venv .venv`
   `.\.venv\Scripts\Activate.ps1`
5. Install dependencies:
   `python -m pip install -r requirements.txt`
6. In MT5, log in and make sure EURUSD is visible in Market Watch.
7. Copy `mt5_ea/ChartScreenshotExporter.mq5` into MT5: File → Open Data Folder → MQL5 → Experts.
8. Open MetaEditor, compile the EA, then attach one instance to EURUSD M1 and another to EURUSD M5. Enable Algo Trading if MT5 requires it for the EA timer. This EA only captures chart images; it does not trade.
9. Run:
   `python main.py`

## Outputs
- `data/market/EURUSD_M1.csv`, `data/market/EURUSD_M5.csv`
- `logs/monitor-YYYY-MM-DD.jsonl`
- screenshots in MT5's `MQL5/Files` folder.

## Next implementation steps
1. Confirm broker symbol spelling (some brokers use EURUSD., EURUSDm, etc.).
2. Validate data timestamps, broker server time, spread, and pip conversion.
3. Validate official macro-calendar source freshness and feed compatibility during local operation.
4. Expand reviewed news coverage and implement the remaining fundamental intelligence layer with official, provenance-preserving sources.
5. Connect a vision provider only after its structured evidence contract is reviewed.
6. Implement the validated Trend → Correction → Rejection → Pullback → Entry decision contract; Phase 6 fusion is not a tradable strategy.
7. Complete outcome tracking, replay/backtests and forward testing in alert-only mode.

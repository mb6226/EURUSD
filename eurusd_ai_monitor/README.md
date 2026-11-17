# EURUSD AI Monitor — Starter v1

Alert-only starter for MetaTrader 5 + Python. It monitors EURUSD on M1 and M5.

## Important status
- MT5 data connector: implemented.
- M1/M5 OHLC retrieval and CSV snapshots: implemented.
- Basic provisional range comparison: implemented for diagnostics only.
- Chart screenshot exporter EA: included; attach it to one EURUSD M1 chart and one EURUSD M5 chart.
- Actual vision-model interpretation: NOT YET CONNECTED.
- Technical, news, calendar, fundamental, statistical, and learning modules are scaffolds only.
- User's full Trend → Correction → Rejection → Pullback rules: NOT YET CODED.
- BUY/SELL signal generation and order execution: DISABLED. The rules engine intentionally returns WAIT.

Do not use this starter as a trading system or assume it has validated profitability.

## Project layout
- `engines/`: MT5 data, screenshot validation, provisional price-action summary, decision engine, and future analysis-engine placeholders.
- `alerts/`: JSONL signal logging.
- `data/`: market snapshots and reserved news, calendar, screenshot, and historical-data folders.
- `knowledge/`: reserved for reviewed rules and analysis references.
- `memory/`: reserved for future SQLite stores and analysis history.
- `learning/`: feedback and evaluation placeholders; no online learning is active.
- `logs/`: monitor output.
- `mt5_ea/`: MetaTrader screenshot-exporter EA.

The empty knowledge/data folders are placeholders. Screenshots continue to be read from MT5's `MQL5/Files` directory; they are not currently copied into `data/screenshots`. The memory database files are not created until their schemas are implemented.

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
3. Connect a vision provider and make it return structured observations with evidence.
4. Translate the user's exact entry rules into deterministic tests.
5. Run replay/backtests and forward-test in alert-only mode before considering any order automation.

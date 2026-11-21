# EURUSD Modular AI

A modular EURUSD research framework. Each subject-specific AI module lives in its own top-level folder under Modules/.

## Shared market data

All modules use the canonical shared market-data directory: data/. The one-year EURUSD M1 Dukascopy dataset, its manifest, and resampled M5, M15, H1, H4 and D1 files are shared across modules. Python modules resolve these files through eurusd_ai.data_catalog and load them through eurusd_ai.market_data.

## Module layout

Modules/Elliott_Waves/ is the first independent analysis module. It contains Detection/, Training/, Data/, Dataset/, Models/ and Evaluation/. The CLI and shared candle reader remain in src/eurusd_ai/ as framework infrastructure.

## Elliott Wave development status

### Stage 1 — Elliott Intelligence Core

Implemented:
- confirmed multi-threshold ZigZag / directional-change pivot extraction;
- optional provisional latest pivot;
- rolling impulse (1-2-3-4-5) candidate generation;
- basic ABC correction and flat-like candidate generation;
- hard-rule checks, heuristic ranking and human-readable reasons;
- JSON reports for M5, M15, H1, H4 and D1.

Run the multi-timeframe Stage-1 analysis from the project root:

```powershell
py -3 scripts\run_elliott_stage1.py
```

Reports are saved under Modules/Elliott_Waves/Evaluation/stage1/. Read Modules/Elliott_Waves/README.md for current assumptions and limitations.

### Next stages

Stage 2 will create a human-reviewable dataset and chart labelling workflow. Stage 3 will train and evaluate ML ranking models on reviewed examples. The system must not treat its own unreviewed predictions as ground truth.

## Setup (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e .
py -m pip install -e ".[ml,dev]"
```

## Commands

```powershell
eurusd-ai inspect-csv path\to\EURUSD_M1.csv
eurusd-ai detect-waves path\to\EURUSD_M1.csv --pip-size 0.0001 --min-leg-pips 5
eurusd-ai analyze-elliott data\eurusd-15min-bid-2025-11-20-2026-11-20.csv --min-leg-pips 15 --top 25
eurusd-ai train-elliott path\to\elliott_training_labels.csv
py -m pytest -q
```

This is a research tool, not a trading signal generator. The current Elliott scores are heuristic rankings, not probabilities. Validate detector logic and models out of sample before use.

## Daily Automation Pipeline

Run `scripts/run_daily_automation.ps1` to download a rolling 10-day EURUSD M1 BID overlap from Dukascopy, merge it into the validated five-year canonical CSV (incremental rows replace duplicate timestamps), rebuild M5/M15/H1/H4/D1, rebuild the causal Stage-2 dataset, refresh Stage-4 multi-timeframe scenarios, and generate the Stage-7 daily forecast. Logs and the latest run summary are stored under `Modules/Elliott_Waves/Evaluation/automation/`.

Windows Task Scheduler task: `EURUSD-AI-Daily-Automation`, daily at 07:30 in the computer's configured timezone (currently Iran Standard Time, UTC+03:30). It is configured to start when available, wake the computer, ignore overlapping instances, allow up to three hours, and retry failures twice at 30-minute intervals. It runs in the interactive user session. The computer must be logged in and the local SOCKS5 proxy/VPN must be available on `127.0.0.1:10808`; if it is unavailable, the run records an error and does not reuse an old download. The daily pipeline intentionally does not retrain Stage 3 or rerun Stage 5/6; those are separate historical training/governance workflows.

Smoke integration test completed through merge, resampling, Stage 2, Stage 4 and Stage 7. The smoke input duplicated the final historical candle, so it did not update market freshness; Stage 7 correctly abstained because the real latest candle remained 2026-11-19 23:58 UTC. Live Dukascopy download remains to be verified when the proxy is running.

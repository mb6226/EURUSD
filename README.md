# EURUSD Precision Research

Research project for testing EURUSD entry patterns with a 2-pip stop loss, 200-pip take profit, and 1-pip spread assumption.

## Research rules
- Analyze both BUY and SELL setups.
- Use M1 for entry sequencing and M5 for context.
- Do not claim a strategy works until it passes a chronological out-of-sample test.
- Use Bid/Ask data when available; do not subtract spread twice.
- If SL and TP are both touched inside one bar and ordering is unknown, mark the outcome ambiguous or use the conservative SL-first assumption.

## Run locally
```bash
python -m pip install -r requirements.txt
python scripts/backtest.py --input data/eurusd_m1.csv --output reports/results.csv
```

Expected input CSV columns: `timestamp,open,high,low,close` in mid prices. For executable bid/ask tests, use `bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close` instead. M1 and M5 are expected to be separate files; M5 is used as context, M1 for stop/target simulation.

Data downloads are deliberately not automated until a reliable source and its licensing/access rules are confirmed. Do not commit licensed market data to the repository unless redistribution is allowed.

#!/usr/bin/env python3
"""Exploratory diagnostics; future excursion labels are descriptive, not signals."""
import argparse
from pathlib import Path
import pandas as pd

PIP = 0.0001
OHLC = ("open", "high", "low", "close")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="reports/pattern_diagnostics.csv")
    a = p.parse_args()
    d = pd.read_csv(a.input)
    if not set(OHLC).issubset(d.columns) and all(f"bid_{c}" in d.columns for c in OHLC):
        for c in OHLC:
            d[c] = d[f"bid_{c}"]
    needed = {"timestamp", *OHLC}
    if needed - set(d):
        raise SystemExit("Missing columns: " + str(sorted(needed - set(d))))
    d["timestamp"] = pd.to_datetime(d.timestamp, utc=True)
    d = d.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    d["range_pips"] = (d.high - d.low) / PIP
    d["body_pips"] = (d.close - d.open).abs() / PIP
    d["hour_utc"] = d.timestamp.dt.hour
    d["weekday"] = d.timestamp.dt.day_name()
    d["return_5m_pips"] = (d.close - d.close.shift(5)) / PIP
    d["return_15m_pips"] = (d.close - d.close.shift(15)) / PIP
    d["return_60m_pips"] = (d.close - d.close.shift(60)) / PIP
    highs, lows, closes = d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy()
    up, down = [], []
    for i in range(len(d)):
        h, e = i + 1, min(len(d), i + 1441)
        up.append(bool(h < e and highs[h:e].max() >= closes[i] + 200 * PIP))
        down.append(bool(h < e and lows[h:e].min() <= closes[i] - 200 * PIP))
    d["future_up_200_within_1d"] = up
    d["future_down_200_within_1d"] = down
    hourly = d.groupby("hour_utc").agg(
        bars=("close", "size"), avg_range_pips=("range_pips", "mean"),
        median_range_pips=("range_pips", "median"),
        future_up_rate=("future_up_200_within_1d", "mean"),
        future_down_rate=("future_down_200_within_1d", "mean"),
    ).reset_index()
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(a.output, index=False)
    print(hourly.to_string(index=False))
    print("Saved", a.output, "(future excursion rates are descriptive only)")


if __name__ == "__main__":
    main()

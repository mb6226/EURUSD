#!/usr/bin/env python3
"""Download one year of EURUSD M1 bid/ask OHLCV data from Dukascopy.

The Dukascopy Node CLI writes CSV columns: timestamp,open,high,low,close,volume.
Timestamps are Unix milliseconds (UTC). Output is normalized to data/eurusd_m1.csv
with timestamp, bid_*, ask_* columns so backtests can use executable-side prices.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run_download(side: str, start: str, end: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "npx", "--yes", "dukascopy-node",
        "-i", "eurusd", "-from", start, "-to", end,
        "-t", "m1", "-p", side, "-f", "csv",
        "-dir", str(out_dir), "-v",
        "-bs", "5", "-bp", "1500",
    ]
    print("Running:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
    candidates = sorted(out_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"Dukascopy CLI produced no CSV in {out_dir}")
    return candidates[0]


def load_side(path: Path, side: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"Unexpected CSV columns in {path}: {list(df.columns)}")
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    # Dukascopy output uses Unix milliseconds; accept seconds too for resilience.
    unit = "ms" if ts.dropna().median() > 10**11 else "s"
    df["timestamp"] = pd.to_datetime(ts, unit=unit, utc=True, errors="coerce")
    out = pd.DataFrame({"timestamp": df["timestamp"]})
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            out[f"{side}_{col}"] = pd.to_numeric(df[col], errors="coerce")
    out = out.dropna(subset=["timestamp"]).drop_duplicates("timestamp").sort_values("timestamp")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True, help="Start date YYYY-MM-DD (UTC)")
    parser.add_argument("--to", dest="end", required=True, help="End date YYYY-MM-DD (UTC; exclusive)")
    parser.add_argument("--output", default="data/eurusd_m1.csv")
    args = parser.parse_args()

    raw = ROOT / "data" / "raw" / "dukascopy"
    bid_file = run_download("bid", args.start, args.end, raw / "bid")
    ask_file = run_download("ask", args.start, args.end, raw / "ask")
    bid = load_side(bid_file, "bid")
    ask = load_side(ask_file, "ask")
    merged = bid.merge(ask, on="timestamp", how="inner", validate="one_to_one")
    merged = merged.sort_values("timestamp").drop_duplicates("timestamp")
    if merged.empty:
        raise RuntimeError("No overlapping bid/ask candles downloaded.")
    # ISO-8601 UTC timestamps are easy to read and unambiguous.
    merged["timestamp"] = merged["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output, index=False)
    print(f"Saved {len(merged):,} overlapping M1 candles to {output}")
    print(f"Range: {merged['timestamp'].iloc[0]} -> {merged['timestamp'].iloc[-1]}")
    print("Columns:", ", ".join(merged.columns))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Download and normalize EURUSD M1 BID/ASK candles from Dukascopy.

Uses the Python dukascopy-downloader client as an alternative to dukascopy-node,
whose browser-based WAF token acquisition can fail in GitHub Actions.
"""
from __future__ import annotations

import argparse
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True, help="Start date YYYY-MM-DD UTC")
    parser.add_argument("--to", dest="end", required=True, help="End date YYYY-MM-DD UTC, exclusive")
    parser.add_argument("--output", default="data/eurusd_m1.csv")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end_exclusive = date.fromisoformat(args.end)
    if end_exclusive <= start:
        raise ValueError("--to must be later than --from")
    # duka CLI's --to is inclusive; convert the workflow's exclusive end date.
    end_inclusive = end_exclusive - timedelta(days=1)
    raw_dir = ROOT / "data" / "raw" / "dukascopy"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    download_cmd = [
        "duka", "download", "EURUSD",
        "--from", start.isoformat(),
        "--to", end_inclusive.isoformat(),
        "--tf", "m1",
        "--side", "both",
        "--data-dir", str(raw_dir),
        "--rate", "5",
    ]
    print("Running:", " ".join(download_cmd), flush=True)
    subprocess.run(download_cmd, cwd=ROOT, check=True)

    export_cmd = [
        "duka", "export", "EURUSD",
        "--from", start.isoformat(),
        "--to", end_inclusive.isoformat(),
        "--tf", "m1",
        "--side", "both",
        "--data-dir", str(raw_dir),
        "-o", str(output),
    ]
    print("Running:", " ".join(export_cmd), flush=True)
    subprocess.run(export_cmd, cwd=ROOT, check=True)

    df = pd.read_csv(output)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "timestamp" not in df.columns:
        for candidate in ("time", "datetime", "date"):
            if candidate in df.columns:
                df = df.rename(columns={candidate: "timestamp"})
                break
    if "timestamp" not in df.columns:
        raise ValueError(f"Could not identify timestamp column. Found: {list(df.columns)}")

    rename = {}
    for col in list(df.columns):
        for side in ("bid", "ask"):
            for field in ("open", "high", "low", "close", "volume"):
                if col in (f"{side}_{field}", f"{field}_{side}", f"{side}{field}"):
                    rename[col] = f"{side}_{field}"
    df = df.rename(columns=rename)

    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    if ts.isna().all():
        raise ValueError("Could not parse any timestamps from exported data.")
    df["timestamp"] = ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    required = {
        "timestamp",
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Exporter did not produce separate BID/ASK OHLC columns. Missing {sorted(missing)}; "
            f"available columns: {list(df.columns)}"
        )
    df = df.dropna(subset=["timestamp"]).drop_duplicates("timestamp").sort_values("timestamp")
    df = df[(df["timestamp"] >= start.isoformat() + "T00:00:00Z") &
            (df["timestamp"] < end_exclusive.isoformat() + "T00:00:00Z")]
    if len(df) < 1000:
        raise RuntimeError(f"Too few M1 candles after download/export: {len(df)}")
    df.to_csv(output, index=False)
    print(f"Saved {len(df):,} EURUSD M1 candles to {output}", flush=True)
    print(f"Range: {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}", flush=True)
    print("Columns:", ", ".join(df.columns), flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
SOURCE = DATA / "eurusd-m1-bid-2021-11-20-2026-11-20.csv"
TIMEFRAMES = [
    ("M5", 5, "5min"),
    ("M15", 15, "15min"),
    ("H1", 60, "1h"),
    ("H4", 240, "4h"),
    ("D1", 1440, "1d"),
]

def resample(minutes: int, suffix: str) -> tuple[int, int, Path]:
    seconds = minutes * 60
    output = DATA / f"eurusd-{suffix}-bid-2021-11-20-2026-11-20.csv"
    source_rows = 0
    bars = 0
    current_bucket = None
    bar = None

    with SOURCE.open("r", newline="", encoding="utf-8-sig") as src, output.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        expected = {"timestamp", "open", "high", "low", "close", "volume"}
        if not expected.issubset(reader.fieldnames or []):
            raise ValueError(f"Unexpected source columns: {reader.fieldnames}")
        writer = csv.writer(dst)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])

        for row in reader:
            ts = int(row["timestamp"])
            bucket = (ts // (seconds * 1000)) * (seconds * 1000)
            o, h, l, c, v = (float(row[k]) for k in ("open", "high", "low", "close", "volume"))

            if current_bucket is None or bucket != current_bucket:
                if bar is not None:
                    writer.writerow([current_bucket, *bar])
                    bars += 1
                current_bucket = bucket
                bar = [o, h, l, c, v]
            else:
                bar[1] = max(bar[1], h)
                bar[2] = min(bar[2], l)
                bar[3] = c
                bar[4] += v
            source_rows += 1

        if bar is not None:
            writer.writerow([current_bucket, *bar])
            bars += 1

    return source_rows, bars, output

def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Missing source dataset: {SOURCE}")
    print(f"Source: {SOURCE}")
    print(f"Source size: {SOURCE.stat().st_size:,} bytes")
    for label, minutes, suffix in TIMEFRAMES:
        rows, bars, output = resample(minutes, suffix)
        print(f"{label}: {bars:,} candles | {output.name} | {output.stat().st_size:,} bytes | source rows={rows:,}")
    print("Done. Timestamps are UTC bucket-open times; volume is summed from source M1 candles.")

if __name__ == "__main__":
    main()


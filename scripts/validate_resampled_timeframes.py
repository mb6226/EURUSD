import csv
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MANIFEST = DATA / "dataset_manifest.json"
START = "2021-11-20"
END = "2026-11-20"
M1_NAME = f"eurusd-m1-bid-{START}-{END}.csv"
FILES = {
    "M5": (f"eurusd-5min-bid-{START}-{END}.csv", 300),
    "M15": (f"eurusd-15min-bid-{START}-{END}.csv", 900),
    "H1": (f"eurusd-1h-bid-{START}-{END}.csv", 3600),
    "H4": (f"eurusd-4h-bid-{START}-{END}.csv", 14400),
    "D1": (f"eurusd-1d-bid-{START}-{END}.csv", 86400),
}
EXPECTED = ["timestamp", "open", "high", "low", "close", "volume"]

def validate(filename, seconds=None):
    path = DATA / filename
    if not path.is_file() or path.stat().st_size < 1000:
        raise RuntimeError(f"Missing, incomplete or unexpectedly small dataset: {filename}")
    count = duplicates = nonmono = bad_ohlc = bad_volume = 0
    first = last = previous = None
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != EXPECTED:
            raise RuntimeError(f"{filename}: bad header {reader.fieldnames}")
        for row in reader:
            ts = int(row["timestamp"])
            o, h, l, c, v = (float(row[k]) for k in EXPECTED[1:])
            if seconds and ts % (seconds * 1000):
                raise RuntimeError(f"{filename}: unaligned timestamp {ts}")
            if previous is not None:
                duplicates += int(ts == previous)
                nonmono += int(ts < previous)
            bad_ohlc += int(h < max(o, c) or l > min(o, c) or h < l)
            bad_volume += int(v < 0)
            first = ts if first is None else first
            last = ts
            previous = ts
            count += 1
    if not count or duplicates or nonmono or bad_ohlc or bad_volume:
        raise RuntimeError(f"{filename}: rows={count}, duplicates={duplicates}, nonmono={nonmono}, bad_ohlc={bad_ohlc}, bad_volume={bad_volume}")
    result = {
        "filename": filename, "row_count": count, "file_size_bytes": path.stat().st_size,
        "timestamp_unit": "milliseconds", "timezone": "UTC",
        "first_timestamp_utc": datetime.fromtimestamp(first/1000, timezone.utc).isoformat(),
        "last_timestamp_utc": datetime.fromtimestamp(last/1000, timezone.utc).isoformat(),
        "duplicate_timestamps": duplicates, "non_monotonic_timestamps": nonmono,
        "invalid_ohlc_rows": bad_ohlc, "negative_volume_rows": bad_volume,
        "validation_status": "passed"
    }
    if seconds:
        result["bucket_alignment_seconds"] = seconds
    return result

def main():
    m1 = validate(M1_NAME, 60)
    print(f"M1: PASS | {m1['row_count']:,} rows | {m1['file_size_bytes']:,} bytes")
    derived = {}
    for label, (filename, seconds) in FILES.items():
        derived[label] = validate(filename, seconds)
        print(f"{label}: PASS | {derived[label]['row_count']:,} rows | {derived[label]['file_size_bytes']:,} bytes")
    manifest = {
        "dataset_id": f"eurusd_m1_bid_utc_{START}_{END}",
        "status": "ready", "source": "Dukascopy", "instrument": "EURUSD",
        "timeframe": "M1", "from_utc_inclusive": f"{START}T00:00:00Z",
        "to_utc_exclusive": f"{END}T00:00:00Z", "price_side": "BID",
        "columns": EXPECTED, "timestamp_unit": "milliseconds",
        "volume_enabled": True, "utc_offset_minutes": 0,
        "include_flat_candles": False, "format": "CSV", "filename": M1_NAME,
        "shared_by_all_modules": True, "validation_status": "passed",
        "validation": m1, "derived_timeframes": derived,
        "derived_timeframes_generated_at_utc": datetime.now(timezone.utc).isoformat()
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Manifest rebuilt for the five-year dataset. All six timeframes passed validation.")

if __name__ == "__main__":
    main()

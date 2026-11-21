from __future__ import annotations
import argparse, csv, os, tempfile
from pathlib import Path

def merge_files(base: Path, incoming: Path) -> dict:
    if not base.is_file() or not incoming.is_file():
        raise FileNotFoundError("Base or incremental CSV is missing")
    rows = {}
    fields = ["timestamp", "open", "high", "low", "close", "volume"]
    for path in (base, incoming):
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not set(fields).issubset(reader.fieldnames or []):
                raise ValueError(f"Invalid CSV header in {path}: {reader.fieldnames}")
            for row in reader:
                ts = int(row["timestamp"])
                vals = [float(row[k]) for k in fields[1:]]
                o,h,l,c,v = vals
                if not (l <= min(o,c) <= max(o,c) <= h) or v < 0:
                    raise ValueError(f"Invalid OHLCV at timestamp {ts} in {path}")
                rows[ts] = [str(ts), *[row[k] for k in fields[1:]]]
    ordered = sorted(rows)
    if not ordered: raise ValueError("Merged dataset is empty")
    fd, temp_name = tempfile.mkstemp(prefix=base.name+".", suffix=".tmp", dir=base.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(fields)
            for ts in ordered: w.writerow(rows[ts])
            f.flush(); os.fsync(f.fileno())
        os.replace(temp_name, base)
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)
    return {"rows":len(ordered),"first_timestamp_ms":ordered[0],"last_timestamp_ms":ordered[-1],"base":str(base),"incremental":str(incoming)}

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--base",required=True,type=Path); p.add_argument("--incremental",required=True,type=Path)
    a=p.parse_args(); print(merge_files(a.base,a.incremental))

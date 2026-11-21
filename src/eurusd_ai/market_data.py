"""Shared, dependency-free OHLCV CSV ingestion for every EURUSD-AI module."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

@dataclass(frozen=True)
class Candle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self):
        if self.high < max(self.open, self.close, self.low):
            raise ValueError(f'Invalid high at {self.time}')
        if self.low > min(self.open, self.close, self.high):
            raise ValueError(f'Invalid low at {self.time}')

def _timestamp_to_utc(value: str) -> str:
    number = float(value)
    seconds = number / 1000.0 if abs(number) >= 100_000_000_000 else number
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()

def load_ohlcv_csv(path: str | Path) -> list[Candle]:
    '''Load normalized time CSV or Dukascopy timestamp CSV (Unix milliseconds).'''
    p = Path(path)
    with p.open('r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fields = {x.strip().lower() for x in (reader.fieldnames or [])}
        required = {'open', 'high', 'low', 'close'}
        missing = required - fields
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
        if 'time' not in fields and 'timestamp' not in fields:
            raise ValueError('CSV must contain either time or Dukascopy timestamp')
        rows: list[Candle] = []
        for raw in reader:
            row = {str(k).strip().lower(): (v or '').strip() for k, v in raw.items() if k is not None}
            time_value = row.get('time') or _timestamp_to_utc(row['timestamp'])
            rows.append(Candle(time_value, *(float(row[k]) for k in ('open', 'high', 'low', 'close')), float(row.get('volume') or 0.0)))
    if not rows:
        raise ValueError('CSV contains no candle rows')
    return rows

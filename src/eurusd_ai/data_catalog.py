"""Canonical paths for shared market datasets used by every module."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_DATA_DIR = PROJECT_ROOT / "data"
# The active research dataset is the validated five-year UTC BID history.
EURUSD_M1_BID_UTC = SHARED_DATA_DIR / "eurusd-m1-bid-2021-11-20-2026-11-20.csv"
EURUSD_TIMEFRAMES = {
    "M1": EURUSD_M1_BID_UTC,
    "M5": SHARED_DATA_DIR / "eurusd-5min-bid-2021-11-20-2026-11-20.csv",
    "M15": SHARED_DATA_DIR / "eurusd-15min-bid-2021-11-20-2026-11-20.csv",
    "H1": SHARED_DATA_DIR / "eurusd-1h-bid-2021-11-20-2026-11-20.csv",
    "H4": SHARED_DATA_DIR / "eurusd-4h-bid-2021-11-20-2026-11-20.csv",
    "D1": SHARED_DATA_DIR / "eurusd-1d-bid-2021-11-20-2026-11-20.csv",
}

def require_dataset(path: str | Path = EURUSD_M1_BID_UTC) -> Path:
    """Return an existing dataset path or raise a helpful error."""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    if not resolved.is_file():
        raise FileNotFoundError(f"Shared dataset not found: {resolved}")
    return resolved

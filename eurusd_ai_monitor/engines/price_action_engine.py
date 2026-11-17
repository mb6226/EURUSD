from __future__ import annotations
import pandas as pd

def summarize_structure(df: pd.DataFrame, lookback: int = 20) -> dict:
    """
    Transparent starter heuristic, NOT the user's final trading rules.
    Uses completed candles only (excludes the currently forming last bar).
    """
    if len(df) < lookback + 3:
        return {"status": "INSUFFICIENT_DATA", "bias": "UNKNOWN"}

    closed = df.iloc[:-1].copy()
    recent = closed.tail(lookback)
    prior = closed.iloc[-(lookback * 2):-lookback]

    if len(prior) < lookback:
        return {"status": "INSUFFICIENT_DATA", "bias": "UNKNOWN"}

    recent_high = float(recent["high"].max())
    recent_low = float(recent["low"].min())
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    last_close = float(closed.iloc[-1]["close"])

    # A deliberately conservative range comparison, not a complete swing algorithm.
    if recent_high > prior_high and recent_low > prior_low:
        bias = "BULLISH"
    elif recent_high < prior_high and recent_low < prior_low:
        bias = "BEARISH"
    else:
        bias = "RANGE / MIXED"

    return {
        "status": "OK",
        "bias": bias,
        "last_closed_candle_utc": closed.iloc[-1]["time"].isoformat(),
        "last_close": last_close,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "prior_high": prior_high,
        "prior_low": prior_low,
        "method": "20-closed-bar range comparison; provisional only",
    }

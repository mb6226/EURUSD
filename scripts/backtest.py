#!/usr/bin/env python3
"""Conservative EURUSD bar-based backtest; research baseline, not a profit claim."""
import argparse
from pathlib import Path
import pandas as pd

PIP = 0.0001
OHLC = ("open", "high", "low", "close")


def load_data(path):
    df = pd.read_csv(path)
    # Dukascopy download has executable bid/ask columns but no generic OHLC.
    if not set(OHLC).issubset(df.columns) and all(f"bid_{c}" in df.columns for c in OHLC):
        for c in OHLC:
            df[c] = df[f"bid_{c}"]
    required = {"timestamp", *OHLC}
    if required - set(df.columns):
        raise ValueError("Missing columns: " + str(sorted(required - set(df.columns))))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if df.empty:
        raise ValueError("Input CSV has no candles.")
    return df


def add_context(df):
    x = df.set_index("timestamp")
    m5 = x[list(OHLC)].resample("5min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna().reset_index()
    m5["m5_trend"] = (m5.close > m5.open).map({True: "bull", False: "bear"})
    m5["m5_range_pips"] = (m5.high - m5.low) / PIP
    return pd.merge_asof(
        df.sort_values("timestamp"),
        m5[["timestamp", "m5_trend", "m5_range_pips"]].sort_values("timestamp"),
        on="timestamp", direction="backward", allow_exact_matches=True,
    )


def run(df, family, spread):
    df = add_context(df)
    df["prev_up"] = df.close.shift(1) > df.open.shift(1)
    df["prev_down"] = df.close.shift(1) < df.open.shift(1)
    df["prior_hi"] = df.high.shift(1).rolling(20).max()
    df["prior_lo"] = df.low.shift(1).rolling(20).min()
    if family == "momentum":
        buys = df.prev_up & (df.m5_trend == "bull")
        sells = df.prev_down & (df.m5_trend == "bear")
    else:
        buys = (df.close > df.prior_hi) & (df.m5_trend == "bull")
        sells = (df.close < df.prior_lo) & (df.m5_trend == "bear")

    has_ba = all(f"{s}_{c}" in df.columns for s in ("bid", "ask") for c in OHLC)
    out = []
    i = 25
    while i < len(df) - 1:
        side = "BUY" if bool(buys.iloc[i]) else ("SELL" if bool(sells.iloc[i]) else None)
        if not side:
            i += 1
            continue
        ei = i + 1
        b = df.iloc[ei]
        entry = float(b.ask_open if side == "BUY" else b.bid_open) if has_ba else float(b.open) + (spread * PIP / 2 if side == "BUY" else -spread * PIP / 2)
        sl = entry + (-2 if side == "BUY" else 2) * PIP
        tp = entry + (200 if side == "BUY" else -200) * PIP
        result, exit_price, exit_time, xi = "OPEN_AT_END", float("nan"), pd.NaT, len(df) - 1
        for j in range(ei, len(df)):
            bar = df.iloc[j]
            if has_ba:
                hi = float(bar.bid_high if side == "BUY" else bar.ask_high)
                lo = float(bar.bid_low if side == "BUY" else bar.ask_low)
            else:
                half = spread * PIP / 2
                hi = float(bar.high - half if side == "BUY" else bar.high + half)
                lo = float(bar.low - half if side == "BUY" else bar.low + half)
            sh = lo <= sl if side == "BUY" else hi >= sl
            th = hi >= tp if side == "BUY" else lo <= tp
            if sh and th:
                result, exit_price = "SL_AMBIGUOUS_CONSERVATIVE", sl
            elif sh:
                result, exit_price = "SL", sl
            elif th:
                result, exit_price = "TP", tp
            else:
                continue
            exit_time, xi = bar.timestamp, j
            break
        pnl = ((exit_price - entry) if side == "BUY" else (entry - exit_price)) / PIP
        if result == "OPEN_AT_END":
            pnl = float("nan")
        out.append({
            "signal": family, "direction": side, "signal_time": df.iloc[i].timestamp,
            "entry_time": b.timestamp, "entry": entry, "stop": sl, "target": tp,
            "exit_time": exit_time, "exit_price": exit_price, "outcome": result,
            "pnl_pips": pnl, "bars_held": xi - ei, "m5_trend": df.iloc[i].m5_trend,
            "m5_range_pips": df.iloc[i].m5_range_pips,
            "price_mode": "bid_ask" if has_ba else "mid_with_assumed_spread",
        })
        i = max(ei + 1, xi + 1)
    return pd.DataFrame(out)


def summarize(trades):
    rows = []
    if trades.empty:
        return pd.DataFrame(columns=["signal", "trades", "closed", "open_at_end", "wins", "losses", "win_rate_pct", "net_pips", "max_drawdown_pips"])
    for signal, group in trades.groupby("signal", sort=True):
        closed = group[group.outcome != "OPEN_AT_END"].sort_values("exit_time")
        wins = int((closed.outcome == "TP").sum())
        losses = int(closed.outcome.str.startswith("SL").sum())
        pnl = closed.pnl_pips.fillna(0.0)
        equity = pnl.cumsum()
        peak = equity.cummax().clip(lower=0)
        drawdown = peak - equity
        rows.append({
            "signal": signal, "trades": len(group), "closed": len(closed),
            "open_at_end": int((group.outcome == "OPEN_AT_END").sum()),
            "wins": wins, "losses": losses,
            "win_rate_pct": round(100 * wins / len(closed), 2) if len(closed) else 0.0,
            "net_pips": round(float(pnl.sum()), 1),
            "max_drawdown_pips": round(float(drawdown.max()), 1) if len(drawdown) else 0.0,
        })
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="reports/results.csv")
    p.add_argument("--summary-output", default="reports/summary.csv")
    p.add_argument("--spread-pips", type=float, default=1.0)
    p.add_argument("--signal", choices=["both", "momentum", "breakout"], default="both")
    p.add_argument("--train-cutoff", default="")
    a = p.parse_args()
    df = load_data(a.input)
    if len(df) < 100:
        raise SystemExit("Not enough M1 bars.")
    families = ["momentum", "breakout"] if a.signal == "both" else [a.signal]
    r = pd.concat([run(df.copy(), f, a.spread_pips) for f in families], ignore_index=True)
    if a.train_cutoff:
        cutoff = pd.Timestamp(a.train_cutoff, tz="UTC")
        r["period"] = r.entry_time.map(lambda t: "train" if t < cutoff else "test")
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    r.to_csv(a.output, index=False)
    s = summarize(r)
    Path(a.summary_output).parent.mkdir(parents=True, exist_ok=True)
    s.to_csv(a.summary_output, index=False)
    print(f"Bars: {len(df):,}; signal timeframe: M1; context/filter: completed M5 candle; spread: {a.spread_pips:g} pip")
    if s.empty:
        print("No trades generated.")
    else:
        print(s.to_string(index=False))
    print("Saved", a.output, "and", a.summary_output)


if __name__ == "__main__":
    main()

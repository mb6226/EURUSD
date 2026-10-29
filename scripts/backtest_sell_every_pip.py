#!/usr/bin/env python3
"""Backtest a sell-on-each-1-pip-price-move grid on EURUSD M1 Bid/Ask candles.

Approximation: a trigger is detected from consecutive M1 closes. Each crossed
1-pip threshold schedules one SELL for the next candle's Bid open. Every
position is independent, with a 2-pip stop and 60-pip target. Intrabar
SL/TP collisions are resolved conservatively as SL.
"""
import argparse
from pathlib import Path
import math
import pandas as pd

PIP = 0.0001


def load_data(path):
    d = pd.read_csv(path)
    required = {"timestamp", "bid_open", "bid_high", "bid_low", "bid_close",
                "ask_open", "ask_high", "ask_low", "ask_close"}
    missing = required - set(d.columns)
    if missing:
        raise ValueError(f"Missing Bid/Ask columns: {sorted(missing)}")
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d = d.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if d.empty:
        raise ValueError("Input CSV has no candles")
    return d


def backtest(d, step_pips=1.0, sl_pips=2.0, tp_pips=60.0):
    active = []
    trades = []
    anchor = float(d.iloc[0].bid_close)
    max_open = 0
    total_triggers = 0

    for i in range(1, len(d)):
        bar = d.iloc[i]
        ts = bar.timestamp
        remaining = []
        # Resolve all previously opened positions using executable ASK prices
        # to close short positions.
        for t in active:
            sl_hit = float(bar.ask_high) >= t["stop"]
            tp_hit = float(bar.ask_low) <= t["target"]
            if sl_hit or tp_hit:
                if sl_hit:  # conservative if both levels were touched in one M1 bar
                    outcome, exit_price = ("SL_AMBIGUOUS_CONSERVATIVE" if tp_hit else "SL"), t["stop"]
                else:
                    outcome, exit_price = "TP", t["target"]
                t.update(exit_time=ts, exit_price=exit_price, outcome=outcome,
                         pnl_pips=(t["entry"] - exit_price) / PIP,
                         bars_held=i - t["entry_i"])
                trades.append(t)
            else:
                remaining.append(t)
        active = remaining

        # Detect threshold crossings using the previous close-to-close move.
        # A crossing creates one independent sell per full pip crossed.
        close = float(bar.bid_close)
        delta = close - anchor
        steps = int(math.floor(abs(delta) / (step_pips * PIP) + 1e-9)) if i < len(d) - 1 else 0
        if steps:
            direction = 1 if delta > 0 else -1
            total_triggers += steps
            for k in range(steps):
                # The threshold is recorded for audit; execution is next M1 open.
                level = anchor + direction * (k + 1) * step_pips * PIP
                active.append({
                    "signal_time": ts,
                    "entry_time": pd.NaT,
                    "trigger_level": level,
                    "entry": math.nan, "stop": math.nan, "target": math.nan,
                    "exit_time": pd.NaT, "exit_price": math.nan, "outcome": "PENDING",
                    "pnl_pips": math.nan, "bars_held": math.nan, "entry_i": i + 1,
                    "direction": "SELL",
                })
            anchor += direction * steps * step_pips * PIP

        # Pending entries from the prior candle are filled at this candle's Bid open.
        # New triggers at this candle's close remain pending until next candle.
        for t in active:
            if t["outcome"] == "PENDING" and t["entry_i"] == i:
                entry = float(bar.bid_open)
                t.update(entry_time=ts, entry=entry, stop=entry + sl_pips * PIP,
                         target=entry - tp_pips * PIP, outcome="OPEN")
        # Any entries scheduled for this bar should be checked against its range.
        still = []
        for t in active:
            if t["outcome"] != "OPEN":
                still.append(t)
                continue
            # Avoid checking positions on their entry candle if entry was just filled:
            # OHLC cannot reveal whether the high/low occurred before or after entry.
            if t["entry_i"] == i:
                still.append(t)
                continue
            sl_hit = float(bar.ask_high) >= t["stop"]
            tp_hit = float(bar.ask_low) <= t["target"]
            if sl_hit or tp_hit:
                if sl_hit:
                    outcome, exit_price = ("SL_AMBIGUOUS_CONSERVATIVE" if tp_hit else "SL"), t["stop"]
                else:
                    outcome, exit_price = "TP", t["target"]
                t.update(exit_time=ts, exit_price=exit_price, outcome=outcome,
                         pnl_pips=(t["entry"] - exit_price) / PIP,
                         bars_held=i - t["entry_i"])
                trades.append(t)
            else:
                still.append(t)
        active = still
        max_open = max(max_open, len(active))

    for t in active:
        t["outcome"] = "OPEN_AT_END"
        t["exit_time"] = pd.NaT
        t["exit_price"] = math.nan
        t["pnl_pips"] = math.nan
        t["bars_held"] = len(d) - 1 - t["entry_i"]
        t.pop("entry_i", None)
    # Remove internal field for closed positions too.
    for t in trades:
        t.pop("entry_i", None)
    result = pd.DataFrame(trades + active)
    if not result.empty:
        result = result.drop(columns=[], errors="ignore")
    return result, total_triggers, max_open


def summarize(trades, triggers, max_open, step_pips, sl_pips, tp_pips):
    closed = trades[trades.outcome != "OPEN_AT_END"].copy() if not trades.empty else trades.copy()
    wins = closed[closed.outcome == "TP"]
    losses = closed[closed.outcome.str.startswith("SL")] if not closed.empty else closed
    pnl = closed.pnl_pips.fillna(0.0) if not closed.empty else pd.Series(dtype=float)
    ordered = closed.sort_values("exit_time") if not closed.empty else closed
    equity = ordered.pnl_pips.fillna(0).cumsum() if not ordered.empty else pd.Series(dtype=float)
    peak = equity.cummax().clip(lower=0) if not equity.empty else equity
    dd = peak - equity if not equity.empty else equity
    gross_profit = float(wins.pnl_pips.sum()) if not wins.empty else 0.0
    gross_loss = abs(float(losses.pnl_pips.sum())) if not losses.empty else 0.0
    hold = closed.bars_held.dropna() if not closed.empty else pd.Series(dtype=float)
    row = {
        "trigger_count": triggers, "total_trades_including_open": len(trades),
        "closed_trades": len(closed), "open_at_end": int((trades.outcome == "OPEN_AT_END").sum()) if not trades.empty else 0,
        "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(closed), 4) if len(closed) else 0.0,
        "net_pips": round(float(pnl.sum()), 2),
        "gross_profit_pips": round(gross_profit, 2), "gross_loss_pips": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "expectancy_pips_per_closed_trade": round(float(pnl.mean()), 4) if len(pnl) else 0.0,
        "avg_win_pips": round(float(wins.pnl_pips.mean()), 2) if not wins.empty else 0.0,
        "avg_loss_pips": round(float(losses.pnl_pips.mean()), 2) if not losses.empty else 0.0,
        "max_drawdown_pips_realized": round(float(dd.max()), 2) if not dd.empty else 0.0,
        "avg_bars_held": round(float(hold.mean()), 2) if len(hold) else 0.0,
        "median_bars_held": round(float(hold.median()), 2) if len(hold) else 0.0,
        "max_simultaneous_open_positions": max_open,
        "step_pips": step_pips, "sl_pips": sl_pips, "tp_pips": tp_pips,
    }
    return pd.DataFrame([row])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="reports/sell_every_pip_trades.csv")
    p.add_argument("--summary-output", default="reports/sell_every_pip_summary.csv")
    p.add_argument("--step-pips", type=float, default=1.0)
    p.add_argument("--sl-pips", type=float, default=2.0)
    p.add_argument("--tp-pips", type=float, default=60.0)
    a = p.parse_args()
    if min(a.step_pips, a.sl_pips, a.tp_pips) <= 0:
        raise SystemExit("step, SL and TP must all be positive")
    d = load_data(a.input)
    trades, triggers, max_open = backtest(d, a.step_pips, a.sl_pips, a.tp_pips)
    summary = summarize(trades, triggers, max_open, a.step_pips, a.sl_pips, a.tp_pips)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.summary_output).parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(a.output, index=False)
    summary.to_csv(a.summary_output, index=False)
    print(f"Bars: {len(d):,}; data: {d.timestamp.min()} -> {d.timestamp.max()}")
    print("Rule: sell once per full 1-pip close-to-close move, next M1 Bid open; all trades independent.")
    print("Execution: short entry Bid, short exits Ask; 1-pip spread embedded in Bid/Ask.")
    print("Intrabar SL/TP collision: conservative SL; entry-bar exits ignored due to unknown intrabar order.")
    print(summary.to_string(index=False))
    print(f"Saved {a.output} and {a.summary_output}")


if __name__ == "__main__":
    main()

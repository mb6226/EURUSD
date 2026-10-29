#!/usr/bin/env python3
"""Backtest EURUSD sell-limit grid on M1 Bid/Ask candles.

A fixed grid is spaced every step_pips. A level becomes eligible only after
Bid has fallen at least arm_drop_pips below it; then a SELL LIMIT is placed at
that level and remains pending until filled. At most one pending order or open
position may exist at a level. After a trade closes, that level cannot arm
again until price has returned to the level, then fallen the required distance
again. SL/TP collisions within one candle are resolved as SL conservatively.
"""
import argparse
import math
from pathlib import Path

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


def backtest(d, step_pips=1.0, sl_pips=2.0, tp_pips=60.0, arm_drop_pips=60.0):
    step = step_pips * PIP
    arm_drop = arm_drop_pips * PIP
    first = float(d.iloc[0].bid_close)
    low_all = float(d.bid_low.min())
    high_all = float(d.bid_high.max())
    # Fixed price levels, aligned to the first observed price and spaced evenly.
    low_idx = math.floor((low_all - arm_drop - first) / step) - 1
    high_idx = math.ceil((high_all - first) / step) + 1
    levels = {k: {
        "level": first + k * step,
        "state": "READY",  # READY, PENDING, OPEN, WAIT_RESET
        "armed_time": pd.NaT,
        "entry_time": pd.NaT,
        "entry_i": None,
        "entry": math.nan,
        "stop": math.nan,
        "target": math.nan,
        "trade_no": 0,
    } for k in range(low_idx, high_idx + 1)}

    trades = []
    total_armed = 0
    total_filled = 0
    max_open = 0

    for i in range(1, len(d)):
        bar = d.iloc[i]
        ts = bar.timestamp
        bid_o, bid_h, bid_l = float(bar.bid_open), float(bar.bid_high), float(bar.bid_low)
        ask_h, ask_l = float(bar.ask_high), float(bar.ask_low)

        # 1) Manage positions that were already open before this candle.
        for info in levels.values():
            if info["state"] != "OPEN":
                continue
            sl_hit = ask_h >= info["stop"]
            tp_hit = ask_l <= info["target"]
            if not (sl_hit or tp_hit):
                continue
            if sl_hit:
                outcome = "SL_AMBIGUOUS_CONSERVATIVE" if tp_hit else "SL"
                exit_price = info["stop"]
            else:
                outcome, exit_price = "TP", info["target"]
            trades.append({
                "level": info["level"], "signal_time": info["armed_time"],
                "entry_time": info["entry_time"], "entry": info["entry"],
                "stop": info["stop"], "target": info["target"],
                "exit_time": ts, "exit_price": exit_price, "outcome": outcome,
                "pnl_pips": (info["entry"] - exit_price) / PIP,
                "bars_held": i - info["entry_i"], "direction": "SELL",
                "trade_number_at_level": info["trade_no"],
            })
            info.update(state="WAIT_RESET", entry_time=pd.NaT, entry_i=None,
                        entry=math.nan, stop=math.nan, target=math.nan)

        # 2) Fill pending sell limits armed on an earlier candle.
        # Sell limits execute at the limit, or at a better price if the market
        # opens above the limit. The OHLC data cannot reveal exact intrabar order.
        for info in levels.values():
            if info["state"] != "PENDING":
                continue
            level = info["level"]
            if bid_o >= level:
                entry = bid_o
            elif bid_h >= level:
                entry = level
            else:
                continue
            info.update(state="OPEN", entry_time=ts, entry_i=i, entry=entry,
                        stop=entry + sl_pips * PIP, target=entry - tp_pips * PIP)
            total_filled += 1

        # 3) Check positions filled this candle against its remaining OHLC range.
        # Conservative handling: if both SL and TP are touched, count SL.
        for info in levels.values():
            if info["state"] != "OPEN" or info["entry_i"] != i:
                continue
            sl_hit = ask_h >= info["stop"]
            tp_hit = ask_l <= info["target"]
            if not (sl_hit or tp_hit):
                continue
            if sl_hit:
                outcome = "SL_AMBIGUOUS_CONSERVATIVE" if tp_hit else "SL"
                exit_price = info["stop"]
            else:
                outcome, exit_price = "TP", info["target"]
            trades.append({
                "level": info["level"], "signal_time": info["armed_time"],
                "entry_time": info["entry_time"], "entry": info["entry"],
                "stop": info["stop"], "target": info["target"],
                "exit_time": ts, "exit_price": exit_price, "outcome": outcome,
                "pnl_pips": (info["entry"] - exit_price) / PIP,
                "bars_held": 0, "direction": "SELL",
                "trade_number_at_level": info["trade_no"],
            })
            info.update(state="WAIT_RESET", entry_time=pd.NaT, entry_i=None,
                        entry=math.nan, stop=math.nan, target=math.nan)

        # 4) A closed level must first recover to its level before it can be
        # armed again. Do not re-arm on the same candle as the reset.
        for info in levels.values():
            if info["state"] == "WAIT_RESET" and bid_h >= info["level"]:
                info["state"] = "READY"

        # 5) Arm levels only after Bid has dropped the full required distance.
        # Newly armed limits cannot fill until a later candle.
        if i < len(d) - 1:
            for info in levels.values():
                if info["state"] == "READY" and bid_l <= info["level"] - arm_drop:
                    info.update(state="PENDING", armed_time=ts)
                    total_armed += 1

        max_open = max(max_open, sum(v["state"] == "OPEN" for v in levels.values()))

    # Report positions and pending limit orders still alive at the end of data.
    for info in levels.values():
        if info["state"] == "OPEN":
            trades.append({
                "level": info["level"], "signal_time": info["armed_time"],
                "entry_time": info["entry_time"], "entry": info["entry"],
                "stop": info["stop"], "target": info["target"],
                "exit_time": pd.NaT, "exit_price": math.nan, "outcome": "OPEN_AT_END",
                "pnl_pips": math.nan, "bars_held": len(d) - 1 - info["entry_i"],
                "direction": "SELL", "trade_number_at_level": info["trade_no"],
            })
        elif info["state"] == "PENDING":
            trades.append({
                "level": info["level"], "signal_time": info["armed_time"],
                "entry_time": pd.NaT, "entry": math.nan, "stop": math.nan,
                "target": math.nan, "exit_time": pd.NaT, "exit_price": math.nan,
                "outcome": "PENDING_AT_END", "pnl_pips": math.nan,
                "bars_held": math.nan, "direction": "SELL",
                "trade_number_at_level": info["trade_no"],
            })

    cols = ["level", "signal_time", "entry_time", "entry", "stop", "target",
            "exit_time", "exit_price", "outcome", "pnl_pips", "bars_held",
            "direction", "trade_number_at_level"]
    result = pd.DataFrame(trades, columns=cols)
    stats = {"levels_checked": len(levels), "limits_placed": total_armed,
             "limits_filled": total_filled, "max_simultaneous_open_positions": max_open}
    return result, stats


def summarize(trades, stats, step_pips, arm_drop_pips, sl_pips, tp_pips):
    closed = trades[trades.outcome.isin(["TP", "SL", "SL_AMBIGUOUS_CONSERVATIVE"])].copy()
    wins = closed[closed.outcome == "TP"]
    losses = closed[closed.outcome.str.startswith("SL")] if not closed.empty else closed
    pnl = closed.pnl_pips if not closed.empty else pd.Series(dtype=float)
    ordered = closed.sort_values("exit_time") if not closed.empty else closed
    equity = ordered.pnl_pips.cumsum() if not ordered.empty else pd.Series(dtype=float)
    peak = equity.cummax().clip(lower=0) if not equity.empty else equity
    dd = peak - equity if not equity.empty else equity
    gross_profit = float(wins.pnl_pips.sum()) if not wins.empty else 0.0
    gross_loss = abs(float(losses.pnl_pips.sum())) if not losses.empty else 0.0
    hold = closed.bars_held.dropna() if not closed.empty else pd.Series(dtype=float)
    row = {
        **stats,
        "closed_trades": len(closed),
        "open_at_end": int((trades.outcome == "OPEN_AT_END").sum()) if not trades.empty else 0,
        "pending_limits_at_end": int((trades.outcome == "PENDING_AT_END").sum()) if not trades.empty else 0,
        "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(closed), 4) if len(closed) else 0.0,
        "net_pips": round(float(pnl.sum()), 2),
        "gross_profit_pips": round(gross_profit, 2), "gross_loss_pips": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "expectancy_pips_per_closed_trade": round(float(pnl.mean()), 4) if len(pnl) else 0.0,
        "max_drawdown_pips_realized": round(float(dd.max()), 2) if not dd.empty else 0.0,
        "avg_bars_held": round(float(hold.mean()), 2) if len(hold) else 0.0,
        "median_bars_held": round(float(hold.median()), 2) if len(hold) else 0.0,
        "step_pips": step_pips, "arm_drop_pips": arm_drop_pips,
        "sl_pips": sl_pips, "tp_pips": tp_pips,
    }
    return pd.DataFrame([row])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="reports/sell_every_pip_trades.csv")
    p.add_argument("--summary-output", default="reports/sell_every_pip_summary.csv")
    p.add_argument("--step-pips", type=float, default=1.0)
    p.add_argument("--arm-drop-pips", type=float, default=60.0)
    p.add_argument("--sl-pips", type=float, default=2.0)
    p.add_argument("--tp-pips", type=float, default=60.0)
    a = p.parse_args()
    if min(a.step_pips, a.arm_drop_pips, a.sl_pips, a.tp_pips) <= 0:
        raise SystemExit("grid step, arm drop, SL and TP must all be positive")
    d = load_data(a.input)
    trades, stats = backtest(d, a.step_pips, a.sl_pips, a.tp_pips, a.arm_drop_pips)
    summary = summarize(trades, stats, a.step_pips, a.arm_drop_pips, a.sl_pips, a.tp_pips)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.summary_output).parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(a.output, index=False)
    summary.to_csv(a.summary_output, index=False)
    print(f"Bars: {len(d):,}; data: {d.timestamp.min()} -> {d.timestamp.max()}")
    print(f"Rule: fixed {a.step_pips:g}-pip levels; wait for a {a.arm_drop_pips:g}-pip fall below each level, then place a SELL LIMIT at that level.")
    print("Constraint: at most one pending order or open position per level; after close, level must recover to itself before re-arming.")
    print("Execution: sell limit uses Bid; short exits use Ask. Same-candle SL/TP ambiguity is resolved as SL.")
    print(summary.to_string(index=False))
    print(f"Saved {a.output} and {a.summary_output}")


if __name__ == "__main__":
    main()

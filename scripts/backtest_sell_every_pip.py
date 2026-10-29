#!/usr/bin/env python3
"""Backtest EURUSD sell-limit grid on M1 Bid/Ask candles.

Each fixed price level is spaced step_pips apart. The price must cross down
through (level - arm_drop_pips) from above before a SELL LIMIT is placed at
the level. The limit remains pending until filled. Each level may have at most
one pending order or open trade. After a trade closes, the price must recover
to the level and subsequently fall the required distance again before re-arming.
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
    low_idx = math.floor((low_all - arm_drop - first) / step) - 2
    high_idx = math.ceil((high_all - first) / step) + 2
    levels = {}
    for k in range(low_idx, high_idx + 1):
        levels[k] = {
            "level": first + k * step, "state": "READY",
            "armed_time": pd.NaT, "entry_time": pd.NaT, "entry_i": None,
            "entry": math.nan, "stop": math.nan, "target": math.nan,
            "trade_no": 0, "ready_after": 0,
        }

    trades = []
    total_armed = 0
    total_filled = 0
    max_open = 0
    active_ids = set()
    pending_ids = set()
    reset_ids = set()

    def close_trade(info, ts, i, outcome, exit_price):
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
                    entry=math.nan, stop=math.nan, target=math.nan,
                    ready_after=i + 1)

    for i in range(1, len(d)):
        bar = d.iloc[i]
        ts = bar.timestamp
        bid_o, bid_h, bid_l = float(bar.bid_open), float(bar.bid_high), float(bar.bid_low)
        ask_h, ask_l = float(bar.ask_high), float(bar.ask_low)
        prev_close = float(d.iloc[i - 1].bid_close)

        # Manage previously open positions.
        for k in list(active_ids):
            info = levels[k]
            sl_hit = ask_h >= info["stop"]
            tp_hit = ask_l <= info["target"]
            if sl_hit or tp_hit:
                if sl_hit:
                    outcome = "SL_AMBIGUOUS_CONSERVATIVE" if tp_hit else "SL"
                    exit_price = info["stop"]
                else:
                    outcome, exit_price = "TP", info["target"]
                close_trade(info, ts, i, outcome, exit_price)
                active_ids.remove(k)
                reset_ids.add(k)

        # Fill SELL LIMIT orders placed on earlier candles.
        for k in list(pending_ids):
            info = levels[k]
            level = info["level"]
            if bid_o >= level:
                entry = bid_o  # favorable gap above the limit
            elif bid_h >= level:
                entry = level
            else:
                continue
            info.update(state="OPEN", entry_time=ts, entry_i=i, entry=entry,
                        stop=entry + sl_pips * PIP, target=entry - tp_pips * PIP)
            pending_ids.remove(k)
            active_ids.add(k)
            total_filled += 1

        # Entry-candle exit check. Intrabar order is unknown; SL wins collisions.
        for k in list(active_ids):
            info = levels[k]
            if info["entry_i"] != i:
                continue
            sl_hit = ask_h >= info["stop"]
            tp_hit = ask_l <= info["target"]
            if sl_hit or tp_hit:
                if sl_hit:
                    outcome = "SL_AMBIGUOUS_CONSERVATIVE" if tp_hit else "SL"
                    exit_price = info["stop"]
                else:
                    outcome, exit_price = "TP", info["target"]
                close_trade(info, ts, i, outcome, exit_price)
                active_ids.remove(k)
                reset_ids.add(k)

        # A closed level resets only after Bid returns to that level.
        for k in list(reset_ids):
            info = levels[k]
            if bid_h >= info["level"]:
                info["state"] = "READY"
                reset_ids.remove(k)

        # Arm only levels whose drop threshold was crossed from above during
        # this bar. This avoids falsely arming levels already below price at
        # the start of the dataset. New limits cannot fill until a later bar.
        if i < len(d) - 1 and prev_close > bid_l:
            k_min = math.ceil((bid_l + arm_drop - first) / step - 1e-10)
            k_max = math.ceil((prev_close + arm_drop - first) / step - 1e-10) - 1
            for k in range(k_min, k_max + 1):
                if k not in levels:
                    continue
                info = levels[k]
                if info["state"] == "READY" and i >= info["ready_after"]:
                    info.update(state="PENDING", armed_time=ts, trade_no=info["trade_no"] + 1)
                    pending_ids.add(k)
                    total_armed += 1

        max_open = max(max_open, len(active_ids))

    # Include live positions and unfilled limits at the dataset boundary.
    for k in active_ids:
        info = levels[k]
        trades.append({
            "level": info["level"], "signal_time": info["armed_time"],
            "entry_time": info["entry_time"], "entry": info["entry"],
            "stop": info["stop"], "target": info["target"],
            "exit_time": pd.NaT, "exit_price": math.nan, "outcome": "OPEN_AT_END",
            "pnl_pips": math.nan, "bars_held": len(d) - 1 - info["entry_i"],
            "direction": "SELL", "trade_number_at_level": info["trade_no"],
        })
    for k in pending_ids:
        info = levels[k]
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

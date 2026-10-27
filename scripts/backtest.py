#!/usr/bin/env python3
"""Conservative EURUSD bar-based backtest; research baseline, not a profit claim."""
import argparse
from pathlib import Path
import pandas as pd
PIP = 0.0001

def load_data(path):
    df = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    if required - set(df.columns): raise ValueError("Missing columns: " + str(sorted(required - set(df.columns))))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)

def add_context(df):
    x = df.set_index("timestamp")
    m5 = x[["open","high","low","close"]].resample("5min").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna().reset_index()
    m5["m5_trend"] = (m5.close > m5.open).map({True:"bull",False:"bear"})
    m5["m5_range_pips"] = (m5.high-m5.low)/PIP
    return pd.merge_asof(df.sort_values("timestamp"),m5[["timestamp","m5_trend","m5_range_pips"]].sort_values("timestamp"),on="timestamp",direction="backward",allow_exact_matches=False)

def run(df,family,spread):
    df=add_context(df)
    df["prev_up"]=df.close.shift(1)>df.open.shift(1)
    df["prev_down"]=df.close.shift(1)<df.open.shift(1)
    df["prior_hi"]=df.high.shift(1).rolling(20).max()
    df["prior_lo"]=df.low.shift(1).rolling(20).min()
    if family=="momentum":
        buys=df.prev_up&(df.m5_trend=="bull"); sells=df.prev_down&(df.m5_trend=="bear")
    else:
        buys=(df.close>df.prior_hi)&(df.m5_trend=="bull"); sells=(df.close<df.prior_lo)&(df.m5_trend=="bear")
    has_ba=all(f"{s}_{c}" in df.columns for s in ("bid","ask") for c in ("open","high","low","close"))
    out=[]; i=25
    while i<len(df)-1:
        side="BUY" if bool(buys.iloc[i]) else ("SELL" if bool(sells.iloc[i]) else None)
        if not side: i+=1; continue
        ei=i+1; b=df.iloc[ei]
        entry=float((b.ask_open if side=="BUY" else b.bid_open)) if has_ba else float(b.open)+(spread*PIP/2 if side=="BUY" else -spread*PIP/2)
        sl=entry+(-2 if side=="BUY" else 2)*PIP; tp=entry+(200 if side=="BUY" else -200)*PIP
        result="OPEN_AT_END"; exit_price=float("nan"); exit_time=pd.NaT; xi=len(df)-1
        for j in range(ei,len(df)):
            bar=df.iloc[j]
            if has_ba:
                hi=float(bar.bid_high if side=="BUY" else bar.ask_high); lo=float(bar.bid_low if side=="BUY" else bar.ask_low)
            else:
                half=spread*PIP/2; hi=float(bar.high-half if side=="BUY" else bar.high+half); lo=float(bar.low-half if side=="BUY" else bar.low+half)
            sh=lo<=sl if side=="BUY" else hi>=sl; th=hi>=tp if side=="BUY" else lo<=tp
            if sh and th: result,exit_price="SL_AMBIGUOUS_CONSERVATIVE",sl
            elif sh: result,exit_price="SL",sl
            elif th: result,exit_price="TP",tp
            else: continue
            exit_time,xi=bar.timestamp,j; break
        pnl=((exit_price-entry) if side=="BUY" else (entry-exit_price))/PIP
        if result=="OPEN_AT_END": pnl=float("nan")
        out.append({"signal":family,"direction":side,"signal_time":df.iloc[i].timestamp,"entry_time":b.timestamp,"entry":entry,"stop":sl,"target":tp,"exit_time":exit_time,"exit_price":exit_price,"outcome":result,"pnl_pips":pnl,"bars_held":xi-ei,"m5_trend":df.iloc[i].m5_trend,"m5_range_pips":df.iloc[i].m5_range_pips,"price_mode":"bid_ask" if has_ba else "mid_with_assumed_spread"})
        i=max(ei+1,xi+1)
    return pd.DataFrame(out)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--output",default="reports/results.csv"); p.add_argument("--spread-pips",type=float,default=1.0); p.add_argument("--signal",choices=["both","momentum","breakout"],default="both"); p.add_argument("--train-cutoff",default=""); a=p.parse_args()
    df=load_data(a.input)
    if len(df)<100: raise SystemExit("Not enough M1 bars.")
    families=["momentum","breakout"] if a.signal=="both" else [a.signal]
    r=pd.concat([run(df.copy(),f,a.spread_pips) for f in families],ignore_index=True)
    if a.train_cutoff:
        cutoff=pd.Timestamp(a.train_cutoff,tz="UTC"); r["period"]=r.entry_time.map(lambda t:"train" if t<cutoff else "test")
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); r.to_csv(a.output,index=False)
    print("M1 bars:",len(df),"trades:",len(r))
    if len(r):
        groups=["signal"]+(["period"] if "period" in r else [])
        for key,g in r.groupby(groups):
            c=g[g.outcome!="OPEN_AT_END"]; wins=int((c.outcome=="TP").sum()); losses=int(c.outcome.str.startswith("SL").sum())
            print(key,"closed",len(c),"TP",wins,"SL",losses,"win_rate",round(100*wins/max(1,len(c)),2),"net_pips",round(c.pnl_pips.sum(),1))
    print("Saved",a.output)
if __name__=="__main__": main()

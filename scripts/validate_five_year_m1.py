import csv, datetime, json, os
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"data"/"eurusd-m1-bid-2021-11-20-2026-11-20.csv"
n=dup=nonmono=bad=neg=0
first=last=prev=None
with p.open(newline="",encoding="utf-8-sig") as f:
    rd=csv.DictReader(f)
    expected=["timestamp","open","high","low","close","volume"]
    assert rd.fieldnames==expected, rd.fieldnames
    for r in rd:
        t=int(r["timestamp"])
        o,h,l,c,v=(float(r[k]) for k in expected[1:])
        n+=1
        first=t if first is None else first
        last=t
        if prev is not None:
            dup += int(t==prev)
            nonmono += int(t<prev)
        bad += int(h<max(o,c) or l>min(o,c) or h<l)
        neg += int(v<0)
        prev=t
result={"rows":n,"first_utc":datetime.datetime.fromtimestamp(first/1000,datetime.timezone.utc).isoformat(),"last_utc":datetime.datetime.fromtimestamp(last/1000,datetime.timezone.utc).isoformat(),"duplicates":dup,"non_monotonic":nonmono,"invalid_ohlc":bad,"negative_volume":neg,"bytes":os.path.getsize(p)}
print(json.dumps(result,indent=2))
assert n>1_000_000 and dup==nonmono==bad==neg==0

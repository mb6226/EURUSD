from __future__ import annotations
import csv,json,re
from bisect import bisect_left
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
EXT=ROOT/"Modules"/"Elliott_Waves"/"Dataset"/"external_references"
IMG=EXT/"chart_image_extractions.jsonl"; ARTICLES=EXT/"collected_analyses.jsonl"
OUT=EXT/"chart_wave_mappings.jsonl"; REPORT=EXT/"chart_wave_mapping_report.md"; DATA=ROOT/"data"
MONTHS={m.lower():i for i,m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),1)}
FILES={"M5":"eurusd-5min-bid-2025-11-20-2026-11-20.csv","M15":"eurusd-15min-bid-2025-11-20-2026-11-20.csv","H1":"eurusd-1h-bid-2025-11-20-2026-11-20.csv","H4":"eurusd-4h-bid-2025-11-20-2026-11-20.csv"}
ALIASES={"5M":"M5","15M":"M15","1H":"H1","4H":"H4"}
def read_jsonl(path):
    rows=[]
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try: rows.append(json.loads(line))
            except json.JSONDecodeError: pass
    return rows
def parse_anchors(tokens,published):
    try: pub=datetime.fromisoformat((published or "").replace("Z","+00:00"))
    except ValueError:return [],"missing_article_date"
    months=[];days=[]
    for t in tokens:
        s=str(t.get("text","")).strip();x=float(t.get("x_normalized",-1));conf=float(t.get("confidence",0))
        if not 0<=x<=1 or conf<.5:continue
        if s.lower() in MONTHS:months.append((x,MONTHS[s.lower()]))
        elif re.fullmatch(r"\d{1,2}",s) and 1<=int(s)<=31:days.append((x,int(s)))
    if not months or len(days)<2:return [],"insufficient_date_ticks"
    months.sort();pts=[]
    for x,day in days:
        prior=[m for m in months if m[0]<=x]
        month=(prior[-1] if prior else months[0])[1];year=pub.year
        if month>pub.month+6:year-=1
        elif month<pub.month-6:year+=1
        try:ts=int(datetime(year,month,day,tzinfo=timezone.utc).timestamp()*1000)
        except ValueError:continue
        pts.append((x,ts))
    pts.sort();clean=[]
    for p in pts:
        if clean and (p[0]-clean[-1][0]<.015 or p[1]<=clean[-1][1]):continue
        clean.append(p)
    return (clean,"approximate_date_axis") if len(clean)>=2 else ([],"date_ticks_not_monotonic")
def timestamp_at_x(x,anchors):
    if len(anchors)<2:return None
    xs=[p[0] for p in anchors];i=bisect_left(xs,x)
    a,b=(anchors[0],anchors[1]) if i==0 else (anchors[-2],anchors[-1]) if i>=len(anchors) else (anchors[i-1],anchors[i])
    return int(a[1]+(x-a[0])/(b[0]-a[0])*(b[1]-a[1])) if b[0]!=a[0] else None
def load_candles(tf):
    rows=[]
    with (DATA/FILES[tf]).open(encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            try:rows.append({"timestamp":int(r["timestamp"]),**{k:float(r[k]) for k in ("open","high","low","close")}})
            except (ValueError,KeyError):pass
    return rows
def nearest_ohlc(c,p):return min(((k,c[k]) for k in ("open","high","low","close")),key=lambda z:abs(z[1]-p))
def map_image(im,article,cache):
    raw=[str(x).upper() for x in im.get("timeframes_detected",[])]
    tf=next((ALIASES.get(x,x) for x in raw if ALIASES.get(x,x) in FILES),None)
    out={"schema_version":1,"image_id":im.get("image_id"),"record_id":im.get("record_id"),"article_url":im.get("article_url"),"article_title":article.get("title"),"published_at":article.get("published_at"),"timeframe":tf,"pair":"EURUSD","mapping_status":"unmapped","review_status":"needs_visual_review","training_eligible":False,"wave_points":[],"wave_segments":[],"mapping_warnings":[]}
    if im.get("ocr_status")!="completed":out["mapping_warnings"].append("OCR_not_completed");return out
    if im.get("image_classification")!="eurusd_chart_candidate":out["mapping_status"]="excluded_non_chart";return out
    if not tf:out["mapping_warnings"].append("unsupported_or_missing_timeframe");return out
    candles=cache.setdefault(tf,load_candles(tf));times=[c["timestamp"] for c in candles]
    cal=im.get("price_axis_calibration") or {};fit=cal.get("price_from_y") if cal.get("status")=="approximate_linear" else None
    anchors,date_status=parse_anchors(im.get("date_axis_tokens",[]),article.get("published_at"))
    out["price_axis_status"]=cal.get("status","missing");out["time_axis_status"]=date_status
    if not fit:out["mapping_warnings"].append("price_axis_not_calibrated")
    if len(anchors)<2:out["mapping_warnings"].append("time_axis_not_calibrated")
    for n,label in enumerate(im.get("possible_wave_labels",[]),1):
        xy=label.get("center_normalized",[None,None]);x,y=xy
        if x is None or y is None:continue
        price=float(fit["intercept"])+float(fit["slope"])*float(y) if fit else None
        if price is not None and not .8<price<1.3:price=None
        ts=timestamp_at_x(float(x),anchors) if len(anchors)>=2 else None
        point={"point_id":f"{im.get('image_id')}_{n}","label":label.get("wave_label_candidate") or label.get("text"),"image_x":round(float(x),6),"image_y":round(float(y),6),"ocr_confidence":label.get("confidence"),"estimated_chart_price":round(price,5) if price is not None else None,"estimated_timestamp_utc":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat() if ts else None,"matched_candle_timestamp_utc":None,"matched_candle_price":None,"matched_ohlc_field":None,"time_distance_minutes":None,"price_delta_pips":None,"point_status":"unresolved"}
        if ts is not None and candles:
            i=bisect_left(times,ts);ix=min((j for j in (i-1,i) if 0<=j<len(candles)),key=lambda j:abs(times[j]-ts));c=candles[ix]
            point["matched_candle_timestamp_utc"]=datetime.fromtimestamp(c["timestamp"]/1000,timezone.utc).isoformat();point["time_distance_minutes"]=round(abs(c["timestamp"]-ts)/60000,2)
            if price is not None:
                field,val=nearest_ohlc(c,price);point["matched_candle_price"]=round(val,5);point["matched_ohlc_field"]=field;point["price_delta_pips"]=round(abs(val-price)*10000,2);point["point_status"]="approximate_candle_match" if point["price_delta_pips"]<=25 else "price_mismatch"
            else:point["point_status"]="time_only"
        elif price is not None:point["point_status"]="price_only"
        out["wave_points"].append(point)
    ordered=sorted((p for p in out["wave_points"] if p["point_status"]=="approximate_candle_match" and p["estimated_timestamp_utc"] and p["estimated_chart_price"] is not None),key=lambda p:p["estimated_timestamp_utc"])
    for a,b in zip(ordered,ordered[1:]):
        d=round((b["estimated_chart_price"]-a["estimated_chart_price"])*10000,2)
        out["wave_segments"].append({"segment_id":a["point_id"]+"__"+b["point_id"],"start_label":a["label"],"end_label":b["label"],"start_timestamp_utc":a["estimated_timestamp_utc"],"end_timestamp_utc":b["estimated_timestamp_utc"],"start_price":a["estimated_chart_price"],"end_price":b["estimated_chart_price"],"direction":"up" if d>0 else "down" if d<0 else "flat","price_change_pips":d,"start_candle_price":a["matched_candle_price"],"end_candle_price":b["matched_candle_price"],"segment_status":"approximate_needs_visual_review"})
    if any(p["point_status"]=="price_mismatch" for p in out["wave_points"]):out["mapping_warnings"].append("Price-to-candle discrepancy exceeds 25 pips; candidate excluded from segment construction.")
    out["mapping_status"]="mapped_approximate" if out["wave_segments"] and not out["mapping_warnings"] else "partial_mapping" if out["wave_points"] else "no_wave_labels_detected"
    if not fit or len(anchors)<2:out["mapping_warnings"].append("Incomplete time-price calibration; never treat as ground truth.")
    return out
def run():
    articles={r.get("record_id"):r for r in read_jsonl(ARTICLES)}
    latest={r.get("image_id"):r for r in read_jsonl(IMG) if r.get("image_id")}
    cache={};results=[map_image(im,articles.get(im.get("record_id"),{}),cache) for im in latest.values()]
    OUT.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in results),encoding="utf-8")
    counts={}
    for r in results:counts[r["mapping_status"]]=counts.get(r["mapping_status"],0)+1
    points=sum(len(r["wave_points"]) for r in results);segments=sum(len(r["wave_segments"]) for r in results)
    lines=["# Chart-to-Wave Mapping Report","",f"- Images considered: {len(results)}",f"- Wave points: {points}",f"- Proposed segments: {segments}",f"- Status counts: {json.dumps(counts)}","- Supported datasets: EURUSD M5, M15, H1 and H4.","- All mappings are approximate and require visual review.","- No record is training-eligible until human confirmation.","","## Per image",""]
    for r in results:lines += [f"### {r.get('image_id')} — {r['mapping_status']}",f"- {r.get('article_title') or 'Untitled'} | {r.get('timeframe') or 'unknown'}",f"- {len(r['wave_points'])} points; {len(r['wave_segments'])} segments",f"- Warnings: {', '.join(r['mapping_warnings']) or 'none'}",""]
    REPORT.write_text("\n".join(lines),encoding="utf-8")
    return {"images":len(results),"points":points,"segments":segments,"statuses":counts}

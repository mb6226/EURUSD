from __future__ import annotations
import json,sqlite3,csv,subprocess,argparse
from pathlib import Path
from datetime import datetime,timezone
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]; APP=ROOT/"eurusd_ai_monitor"; REPORTS=ROOT/"reports"; LOGS=APP/"logs"; DB=APP/"data"/"market"/"market_data.sqlite"; RAW_DB=ROOT/"source_registry"/"operational"/"raw_snapshots.sqlite"; OBS_DB=ROOT/"source_registry"/"operational"/"observations.sqlite"; CALENDAR_DB=APP/"data"/"calendar"/"macro_calendar.sqlite"
def readj(p):
 try:return json.loads(p.read_text(encoding="utf-8"))
 except Exception as e:return {"_error":str(e)}
def tail_records(path, max_records=10, max_bytes=2*1024*1024):
 try:
  size=path.stat().st_size
  with path.open("rb") as f:
   f.seek(max(0,size-max_bytes))
   raw=f.read(max_bytes)
  lines=raw.splitlines()
  if size>max_bytes and lines: lines=lines[1:]
  out=[]
  for line in reversed(lines):
   if not line.strip(): continue
   try: out.append(json.loads(line.decode("utf-8")))
   except Exception: continue
   if len(out)>=max_records: break
  return list(reversed(out))
 except Exception: return []
def latest():
 for p in sorted(LOGS.glob("monitor-*.jsonl"),key=lambda x:x.stat().st_mtime,reverse=True):
  rows=tail_records(p,1)
  if rows:return rows[-1],p.name
 return None,None
def recent_history(max_records=24):
 rows=[]
 for p in sorted(LOGS.glob("monitor-*.jsonl"),key=lambda x:x.stat().st_mtime):
  rows.extend(tail_records(p,max_records))
 rows.sort(key=lambda x:str(x.get("created_at_utc","")))
 return rows[-max_records:]
def archive():
 d={"exists":DB.exists(),"integrity":"UNKNOWN","tables":{}}
 if not DB.exists():return d
 try:
  c=sqlite3.connect("file:"+str(DB)+"?mode=ro",uri=True,timeout=2);d["integrity"]=c.execute("PRAGMA integrity_check").fetchone()[0]
  ts=[x[0] for x in c.execute("select name from sqlite_master where type='table'")]
  for t in ts:
   if not t.startswith("sqlite_"):
    try:d["tables"][t]=c.execute('select count(*) from "'+t.replace('"','""')+'"').fetchone()[0]
    except Exception:pass
  d["table_names"]=ts;c.close()
 except Exception as e:d["error"]=str(e)
 return d
def inspect_store(path, groups=None):
 d={"exists":path.exists(),"integrity":"UNKNOWN","tables":{}}
 if not path.exists():return d
 try:
  c=sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True,timeout=2)
  d["integrity"]=c.execute("PRAGMA integrity_check").fetchone()[0]
  ts=[x[0] for x in c.execute("select name from sqlite_master where type='table'")]
  for t in ts:
   if not t.startswith("sqlite_"):
    try:d["tables"][t]=c.execute('select count(*) from "'+t.replace('"','""')+'"').fetchone()[0]
    except Exception:pass
  for name,(table,sql) in (groups or {}).items():
   if table in ts:
    cur=c.execute(sql);cols=[x[0] for x in cur.description];rows=cur.fetchall()
    if name=="summary" and rows:d.update(dict(zip(cols,rows[0])))
    else:d[name]=[dict(zip(cols,row)) for row in rows]
  d["status"]="HEALTHY" if d["integrity"]=="ok" else "BLOCKED"
  c.close()
 except Exception as e:d["error"]=str(e)
 return d
def data_archives():
 return {
  "raw_snapshots":inspect_store(RAW_DB,{
   "summary":("raw_snapshots","select count(*) as snapshots,coalesce(sum(payload_bytes),0) as payload_bytes from raw_snapshots"),
   "by_source":("raw_snapshots","select source_id,count(*) as snapshots,coalesce(sum(payload_bytes),0) as payload_bytes from raw_snapshots group by source_id order by source_id"),
   "by_product":("raw_snapshots","select source_id,product_id,count(*) as snapshots,max(retrieved_at_utc) as latest from raw_snapshots group by source_id,product_id order by source_id,product_id")}),
  "observations":inspect_store(OBS_DB,{
   "summary":("observations","select count(*) as observations from observations"),
   "by_product":("observations","select source_id,product_id,count(*) as observations,min(effective_at_utc) as first_effective,max(effective_at_utc) as last_effective,min(published_at_utc) as first_published,max(published_at_utc) as last_published from observations group by source_id,product_id order by source_id,product_id")}),
  "calendar":inspect_store(CALENDAR_DB,{
   "summary":("macro_events","select count(*) as events from macro_events"),
   "by_source":("macro_events","select source_id,count(*) as events,min(scheduled_date) as first_date,max(scheduled_date) as last_date from macro_events group by source_id order by source_id")})
 }
def collect():
 l,lf=latest();rs={p.stem:readj(p) for p in REPORTS.glob("*.json")}
 pts=[];p=APP/"data"/"market"/"EURUSD_M1.csv"
 try:
  with p.open(encoding="utf-8-sig",newline="") as f:
   for r in list(csv.DictReader(f))[-180:]:
    v=next((r[k] for k in ("close","Close","CLOSE") if k in r),None)
    if v is not None:pts.append({"time":r.get("time",r.get("Time","")),"close":float(v)})
 except Exception:pass
 try:procs=subprocess.run(["tasklist","/FI","IMAGENAME eq python.exe","/FO","CSV","/NH"],capture_output=True,text=True,timeout=2).stdout.splitlines()
 except Exception:procs=[]
 hist=recent_history(10)
 return {"generated_at_utc":datetime.now(timezone.utc).isoformat(),"live":l,"live_file":lf,"history":[{"created_at_utc":x.get("created_at_utc"),"decision":x.get("decision"),"symbol":x.get("symbol"),"fusion_status":(x.get("fusion_assessment") or {}).get("status"),"scenario_status":(x.get("central_scenario_intelligence") or {}).get("status"),"quality_valid":((x.get("market_context") or {}).get("quality") or {}).get("is_valid")} for x in hist],"reports":rs,"archive":archive(),"data_archives":data_archives(),"price_series":pts,"config":readj(APP/"config.json"),"python_processes":procs,"logs":[{"name":x.name,"bytes":x.stat().st_size,"modified":datetime.fromtimestamp(x.stat().st_mtime,timezone.utc).isoformat()} for x in sorted(LOGS.glob("monitor-*.jsonl"),key=lambda x:x.stat().st_mtime,reverse=True)[:10]]}
HTML=r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EURUSD Market Brain</title><style>
:root{color-scheme:dark;--bg:#090e18;--p:#111a2a;--line:#26364d;--t:#e7eef9;--m:#91a2bb;--g:#36d399;--y:#f5b942;--r:#fb7185;--b:#60a5fa}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:14px/1.5 Segoe UI,Arial}header{position:sticky;top:0;background:#0b1220ed;border-bottom:1px solid var(--line);padding:14px 22px;display:flex;justify-content:space-between;z-index:3}.brand{font-size:18px;font-weight:800}.muted,.small{color:var(--m);font-size:12px}main{max-width:1600px;margin:auto;padding:20px}.row{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.hero,.grid{display:grid;gap:12px}.hero{grid-template-columns:repeat(5,minmax(0,1fr))}.grid{grid-template-columns:repeat(3,minmax(0,1fr))}.tile,.panel,.module{background:linear-gradient(145deg,#111a2a,#0d1523);border:1px solid var(--line);border-radius:13px;padding:14px;min-width:0}.k{font-size:11px;color:var(--m);text-transform:uppercase;letter-spacing:1px}.v{font-size:22px;font-weight:750;overflow-wrap:anywhere}.module h3{font-size:14px;margin:0}.top{display:flex;justify-content:space-between;gap:8px;align-items:center}.status{font-size:10px;font-weight:800;padding:4px 8px;border-radius:20px;background:#263246}.ok{color:var(--g);background:#0e352d}.warn{color:var(--y);background:#3b2c11}.bad{color:var(--r);background:#401c29}.info{color:var(--b);background:#172e4d}.body{font-size:12px;color:#c5d2e5;white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto;margin-top:8px}details{border-top:1px solid var(--line);margin-top:8px;padding-top:7px}summary{cursor:pointer;color:#9fc5f5;font-size:12px}.json{font:11px Consolas;white-space:pre-wrap;overflow-wrap:anywhere;max-height:480px;overflow:auto;color:#b8c8dc}.nav{display:flex;gap:7px;flex-wrap:wrap;margin:16px 0}.nav button,button{background:#17243a;border:1px solid #2a3c58;color:#dce8f8;border-radius:8px;padding:7px 11px;cursor:pointer}.nav .active{background:#24466d}.search{background:#101a2a;border:1px solid var(--line);color:var(--t);padding:9px;border-radius:8px;min-width:220px}.chart{width:100%;height:210px;background:#0b1422;border-radius:10px}.section{margin-top:24px}.hidden{display:none!important}.foot{color:#72839d;font-size:11px;margin:24px 0}@media(max-width:1050px){.grid{grid-template-columns:repeat(2,1fr)}.hero{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){main{padding:12px}.grid,.hero{grid-template-columns:1fr 1fr}}
</style></head><body><header><div><div class="brand">◈ EURUSD INTELLIGENT MARKET BRAIN</div><div class="muted">Unified monitoring · evidence-first · read-only dashboard</div></div><div><span id="conn" class="small">Connecting…</span> <button onclick="refresh()">↻ Refresh</button></div></header><main>
<div class="row"><div><h2>Command Center</h2><div id="updated" class="small"></div></div><input id="search" class="search" placeholder="Filter components…" oninput="render()"></div><div id="kpis" class="hero"></div>
<div id="nav" class="nav"></div>
<div id="overview" class="section"><h2>Live Market & Decision Pipeline</h2><div id="live" class="grid"></div><div class="panel" style="margin-top:12px"><div class="row"><b>EURUSD · M1 recent closes</b><span id="priceMeta" class="small"></span></div><svg id="chart" class="chart" viewBox="0 0 1000 210" preserveAspectRatio="none"></svg></div><div class="panel" style="margin-top:12px"><div class="row"><b>Engine / Decision Status Timeline</b><span id="historyMeta" class="small"></span></div><svg id="historyChart" class="chart" viewBox="0 0 1000 160" preserveAspectRatio="none"></svg><div id="historyTable" class="body"></div></div></div>
<div id="modules" class="section"><h2>All Intelligence Components</h2><div id="moduleGrid" class="grid"></div></div>
<div id="research" class="section"><h2>Historical Research & Validation · Phases 37–51</h2><div id="reportGrid" class="grid"></div></div>
<div id="infra" class="section"><h2>Infrastructure & Data Archive</h2><div id="infraGrid" class="grid"></div></div>
<div id="raw" class="section"><h2>Full Snapshot Inspector</h2><div class="panel"><button onclick="navigator.clipboard.writeText(JSON.stringify(D.live,null,2))">Copy JSON</button><pre id="rawJson" class="json"></pre></div></div>
<div class="foot">Read-only observability. No order placement, risk changes, source acquisition, or RAG mutation. Missing evidence stays visibly blocked.</div></main>
<script>
let D=null,tab='all';const $=x=>document.getElementById(x);
function esc(s){return String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function st(o){let s=String(o?.status||o?.state||o?.decision||'').toUpperCase();if(/BLOCK|NO_|UNAVAILABLE|INSUFFICIENT|ERROR|INVALID|FAILED|REQUIRED/.test(s))return'BLOCKED';if(/DEGRAD|WARN|PARTIAL|SKIP|PENDING|WAIT/.test(s))return'DEgraded'.toUpperCase();if(/COMPLETE|READY|HEALTHY|ANALYZED|PROCESSED|ACTIVE|PASS/.test(s))return'HEALTHY';return s||'AVAILABLE'}
function cl(s){return /BLOCK|ERROR|FAIL|INVALID/.test(s)?'bad':/DEGRAD|WARN|PENDING|WAIT|SKIP|INSUFFICIENT/.test(s)?'warn':/HEALTHY|READY|COMPLETE|PASS|ACTIVE|ANALYZED/.test(s)?'ok':'info'}
function card(title,o,group){let s=st(o),det=o?Object.entries(o).filter(([k,v])=>!['records','history'].includes(k)&&v!==null&&typeof v!=='object').slice(0,8).map(([k,v])=>k+': '+v).join('\n'):'No live output for this component';return '<article class="module" data-group="'+group+'" data-search="'+esc((title+' '+det+' '+s).toLowerCase())+'"><div class="top"><h3>'+esc(title)+'</h3><span class="status '+cl(s)+'">'+esc(s)+'</span></div><div class="body">'+esc(det)+'</div>'+(o?'<details><summary>Inspect complete payload</summary><pre class="json">'+esc(JSON.stringify(o,null,2))+'</pre></details>':'')+'</article>'}
function render(){if(!D)return;let l=D.live||{},q=l.market_context?.quality||{},a=D.archive||{};$('updated').textContent='Snapshot '+new Date(D.generated_at_utc).toLocaleString()+' · Source '+(D.live_file||'no monitor record');$('conn').textContent=l?'Monitor data loaded':'No live record';$('kpis').innerHTML=[['Symbol',l.symbol||'EURUSD'],['Decision',l.decision||'NO DATA'],['Market quality',q.is_valid===true?'VALID':q.is_valid===false?'INVALID':'UNKNOWN'],['Spread (pips)',l.market_context?.spread_pips??'—'],['Archive integrity',a.integrity||'UNKNOWN']].map(x=>'<div class="tile"><div class="k">'+esc(x[0])+'</div><div class="v">'+esc(x[1])+'</div></div>').join('');
let excluded=new Set(['symbol','created_at_utc','decision','direction','reasons','trade_execution','screenshots']);let pairs=Object.entries(l).filter(([k])=>!excluded.has(k)).map(([k,v])=>[k.replaceAll('_',' ').toUpperCase(),v]);if(l.live_specialist_reports&&typeof l.live_specialist_reports==='object'){for(const [k,v] of Object.entries(l.live_specialist_reports))pairs.push(['Specialist · '+k.replaceAll('_',' '),v])}
$('live').innerHTML=pairs.filter(x=>x[1]!==undefined).slice(0,9).map(x=>card(x[0],x[1],'live')).join('')||card('Live Monitor',null,'live');$('moduleGrid').innerHTML=pairs.map(x=>card(x[0],x[1],'modules')).join('');
let hist=D.history||[];$('historyMeta').textContent=hist.length+' recent monitor records';if(hist.length){let w=1000/(hist.length),marks=hist.map((x,i)=>{let s=String(x.fusion_status||x.scenario_status||x.decision||'').toUpperCase(),fill=/BLOCK|ERROR|FAIL/.test(s)?'#fb7185':/WARN|PARTIAL|WAIT|DEGRAD/.test(s)?'#f5b942':'#36d399';return '<rect x="'+(i*w+2)+'" y="20" width="'+Math.max(3,w-4)+'" height="100" rx="2" fill="'+fill+'"><title>'+esc(x.created_at_utc)+' · '+esc(x.decision)+' · '+esc(s)+'</title></rect>'}).join('');$('historyChart').innerHTML=marks;$('historyTable').textContent=hist.slice(-8).reverse().map(x=>(x.created_at_utc||'').replace('T',' ').slice(0,19)+' | '+(x.decision||'—')+' | Fusion '+(x.fusion_status||'—')+' | Scenario '+(x.scenario_status||'—')+' | Quality '+(x.quality_valid===true?'VALID':x.quality_valid===false?'INVALID':'UNKNOWN')).join(' | ')}else{$('historyChart').innerHTML='<text x="30" y="80" fill="#91a2bb">No bounded history records available</text>';$('historyTable').textContent='History unavailable'}
$('reportGrid').innerHTML=Object.entries(D.reports||{}).sort().map(x=>card(x[0].replaceAll('_',' '),x[1],'research')).join('');$('infraGrid').innerHTML=[['Market Archive',a],['Raw Snapshot Archive',D.data_archives?.raw_snapshots],['PIT Observation Store',D.data_archives?.observations],['Economic Calendar Store',D.data_archives?.calendar],['Python Processes',{processes:D.python_processes}],['Runtime Config',D.config],['Monitor Logs',{files:D.logs}]].map(x=>card(x[0],x[1],'infra')).join('');$('rawJson').textContent=JSON.stringify(l,null,2);
let p=D.price_series||[];$('priceMeta').textContent=p.length+' points';if(p.length>1){let v=p.map(x=>x.close),mn=Math.min(...v),mx=Math.max(...v),sp=mx-mn||1,d=v.map((x,i)=>(i?'L':'M')+(i*1000/(v.length-1)).toFixed(1)+','+(195-(x-mn)/sp*180).toFixed(1)).join(' ');$('chart').innerHTML='<path d="'+d+'" fill="none" stroke="#60a5fa" stroke-width="2.5"/>'}else $('chart').innerHTML='<text x="30" y="100" fill="#91a2bb">No recent M1 CSV data</text>';
document.querySelectorAll('.module').forEach(e=>e.classList.toggle('hidden',!(tab==='all'||e.dataset.group===tab)||!e.dataset.search.includes($('search').value.toLowerCase())))}
function refresh(){fetch('/api/status').then(r=>r.json()).then(x=>{D=x;render()}).catch(()=>{$('conn').textContent='API disconnected'})}
let tabs=[['all','All'],['live','Live pipeline'],['modules','Components'],['research','Research'],['infra','Infrastructure'],['raw','Raw JSON']];$('nav').innerHTML=tabs.map(x=>'<button data-tab="'+x[0]+'">'+x[1]+'</button>').join('');document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('active',x===b));const sectionId=tab==='live'?'overview':tab;document.querySelectorAll('.section').forEach(x=>x.classList.toggle('hidden',tab!=='all'&&x.id!==sectionId));render()});$('nav button').classList.add('active');refresh();setInterval(refresh,10000);
</script></body></html>'''
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  if urlparse(self.path).path=="/api/status":raw=json.dumps(collect(),ensure_ascii=False,default=str).encode();typ="application/json; charset=utf-8"
  else:raw=HTML.encode();typ="text/html; charset=utf-8"
  self.send_response(200);self.send_header("Content-Type",typ);self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,*args):pass
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--host",default="127.0.0.1");p.add_argument("--port",type=int,default=8765);p.add_argument("--check",action="store_true");a=p.parse_args()
 if a.check:
  d=collect();print(json.dumps({"live_record":bool(d["live"]),"live_component_count":len(d["live"] or {}),"history_records":len(d["history"]),"reports":len(d["reports"]),"archive_integrity":d["archive"].get("integrity"),"data_archives":{k:{"integrity":v.get("integrity"),"status":v.get("status"),"summary":{x:v.get(x) for x in ("snapshots","payload_bytes","observations","events")}} for k,v in d["data_archives"].items()},"price_points":len(d["price_series"]),"root":str(ROOT)},indent=2));raise SystemExit(0)
 s=ThreadingHTTPServer((a.host,a.port),H);print("EURUSD dashboard http://"+a.host+":"+str(a.port));s.serve_forever()

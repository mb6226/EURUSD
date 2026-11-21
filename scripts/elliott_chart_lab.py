from __future__ import annotations
import argparse, csv, json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
CANDIDATE_DIR=ROOT/"Modules"/"Elliott_Waves"/"Evaluation"/"stage1"
LABEL_DIR=ROOT/"Modules"/"Elliott_Waves"/"Dataset"
LABEL_DIR.mkdir(parents=True,exist_ok=True)
LABEL_FILE=LABEL_DIR/"reviewed_labels.jsonl"
TIMEFRAMES={"M5":"eurusd-5min-bid-2025-11-20-2026-11-20.csv","M15":"eurusd-15min-bid-2025-11-20-2026-11-20.csv","H1":"eurusd-1h-bid-2025-11-20-2026-11-20.csv","H4":"eurusd-4h-bid-2025-11-20-2026-11-20.csv","D1":"eurusd-1d-bid-2025-11-20-2026-11-20.csv"}
HTML=r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EURUSD Elliott Wave Chart Lab</title>
<style>
:root{color-scheme:dark;font:14px Segoe UI,Arial;background:#10151d;color:#e7edf5}body{margin:0}header{padding:14px 20px;background:#182230;border-bottom:1px solid #344255;display:flex;gap:18px;align-items:center;flex-wrap:wrap}h1{font-size:18px;margin:0}small,.muted{color:#9eacbd}.layout{display:grid;grid-template-columns:minmax(500px,1fr) 370px;gap:12px;padding:12px}.panel{background:#182230;border:1px solid #344255;border-radius:9px;padding:12px;min-width:0}canvas{width:100%;height:540px;display:block;background:#111923;border-radius:6px}button,select,textarea{background:#253448;color:#edf3fa;border:1px solid #50627a;border-radius:5px;padding:8px}button{cursor:pointer}.actions,.row{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}.row label{color:#aab8c9}#candidates{max-height:290px;overflow:auto}.candidate{padding:9px;border:1px solid #3b4b60;border-radius:6px;margin:6px 0;cursor:pointer}.candidate.active{border-color:#70b7ff;background:#20364b}.candidate b{display:block;margin-bottom:4px}textarea{width:calc(100% - 18px);min-height:65px}#status{color:#8bd5a8;min-height:20px}.warning{color:#f0c77a}@media(max-width:900px){.layout{grid-template-columns:1fr}canvas{height:420px}}
</style></head><body><header><h1>EURUSD · Elliott Wave Chart Lab</h1><span class="muted">Human-reviewed labels only · heuristic candidates are not probabilities</span><span id="meta"></span></header>
<div class="layout"><main class="panel"><div class="row"><label>Timeframe</label><select id="tf"><option>M15</option><option>M5</option><option>H1</option><option>H4</option><option>D1</option></select><label>Bars</label><select id="bars"><option>300</option><option selected>500</option><option>800</option></select><button id="reload">Load chart</button></div><canvas id="chart" width="1400" height="620"></canvas><p class="muted">OHLC candles · blue markers: detected pivots · numbered points: selected candidate pivots.</p></main>
<aside class="panel"><h3 style="margin-top:0">Candidate hypotheses</h3><div class="row"><label>Filter</label><select id="pattern"><option value="all">All patterns</option><option>impulse</option><option>zigzag</option><option>flat_candidate</option></select></div><div id="candidates">Loading…</div><hr><h3>Review selected count</h3><div id="selected" class="muted">Select a candidate.</div>
<div class="row"><label>Human verdict</label><select id="verdict"><option value="accepted">Accept</option><option value="rejected">Reject</option><option value="needs_correction">Needs correction</option></select></div><div class="row"><label>Pattern label</label><select id="label"><option value="impulse">Impulse (1-2-3-4-5)</option><option value="zigzag">Zigzag (A-B-C)</option><option value="flat">Flat (A-B-C)</option><option value="triangle">Triangle</option><option value="diagonal">Diagonal</option><option value="other">Other / unclear</option></select></div><div class="row"><label>Reviewer ID</label><input id="reviewerId" placeholder="Unique reviewer ID" required></div><div class="row"><label>Reviewer role</label><select id="reviewerRole"><option value="non_expert">Learner / non-expert</option><option value="expert">Expert reviewer (self-declared)</option></select></div><label class="muted">Qualification / experience statement (required for expert reviews)</label><textarea id="qualification" placeholder="Describe Elliott Wave review experience and relevant qualifications"></textarea><div class="row"><label><input type="checkbox" id="independentReview"> I made this judgment independently, not by copying the AI score.</label></div><label class="muted">Reviewer notes / corrected interpretation</label><textarea id="notes" placeholder="Explain why this count is valid/invalid, or describe corrected pivots…"></textarea><div class="actions"><button id="save">Save human review</button><button id="next">Next candidate</button></div><div id="status"></div><hr><div class="muted" id="labelcount">0 reviewed labels saved</div><p class="warning">Unreviewed candidates are never training ground truth. A correction note is required for “Needs correction”.</p></aside></div>
<script>
let state={data:null,candidates:[],selected:0};const $=id=>document.getElementById(id);
async function load(){let tf=$('tf').value,bars=$('bars').value;$('status').textContent='Loading…';let r=await fetch('/api/data?tf='+tf+'&bars='+bars);state.data=await r.json();state.candidates=state.data.candidates;state.selected=0;renderList();draw();$('meta').textContent=tf+' · '+state.data.candles.length+' bars · '+state.candidates.length+' candidates';$('status').textContent='Chart loaded';}
function filtered(){let p=$('pattern').value;return state.candidates.map((c,i)=>Object.assign({_i:i},c)).filter(c=>p==='all'||c.pattern===p)}
function renderList(){let a=filtered();$('candidates').innerHTML=a.map(c=>'<div class="candidate '+(c._i===state.selected?'active':'')+'" data-i="'+c._i+'"><b>'+c.pattern.toUpperCase()+' · '+c.direction+'</b><span class="muted">Score '+Number(c.score).toFixed(1)+' · '+c.pivots.length+' pivots</span><br><span class="muted">'+c.pivots[0].time+' → '+c.pivots.at(-1).time+'</span></div>').join('')||'No candidates in this window';document.querySelectorAll('.candidate').forEach(el=>el.onclick=()=>select(+el.dataset.i));renderSelected();}
function select(i){state.selected=i;renderList();draw()}
function renderSelected(){let c=state.candidates[state.selected];if(!c){$('selected').textContent='No candidate selected';return}$('selected').innerHTML='<b>'+c.pattern+' / '+c.direction+'</b><br>Heuristic score: '+Number(c.score).toFixed(2)+'<br>'+(c.reasons||[]).join('<br>')+'<br><small>'+c.pivots.map((p,i)=>(i+1)+'. '+p.kind+' '+p.price).join(' · ')+'</small>';$('label').value=c.pattern==='flat_candidate'?'flat':c.pattern;}
function draw(){let cv=$('chart'),ctx=cv.getContext('2d'),d=state.data;if(!d)return;let cs=d.candles,w=cv.width,h=cv.height;ctx.clearRect(0,0,w,h);let lo=Math.min(...cs.map(x=>x.low)),hi=Math.max(...cs.map(x=>x.high)),pad=(hi-lo)*.08||.001;lo-=pad;hi+=pad;let y=p=>h-35-(p-lo)/(hi-lo)*(h-65),step=w/cs.length,cw=Math.max(1,step*.65);ctx.strokeStyle='#29384a';for(let k=0;k<=5;k++){let yy=30+k*(h-65)/5;ctx.beginPath();ctx.moveTo(0,yy);ctx.lineTo(w,yy);ctx.stroke();ctx.fillStyle='#91a1b4';ctx.fillText((hi-(hi-lo)*k/5).toFixed(5),5,yy-4)}
cs.forEach((c,i)=>{let x=i*step+step/2,up=c.close>=c.open;ctx.strokeStyle=up?'#57c69a':'#e47e83';ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.moveTo(x,y(c.high));ctx.lineTo(x,y(c.low));ctx.stroke();let top=y(Math.max(c.open,c.close)),bottom=y(Math.min(c.open,c.close));ctx.fillRect(x-cw/2,top,cw,Math.max(1,bottom-top))});
let start=d.start_index;d.pivots.forEach(p=>{let ix=p.index-start;if(ix<0||ix>=cs.length)return;ctx.fillStyle='#69aef5';ctx.beginPath();ctx.arc(ix*step+step/2,y(p.price),2.4,0,Math.PI*2);ctx.fill()});
let c=state.candidates[state.selected];if(c){ctx.strokeStyle='#ffd166';ctx.lineWidth=2;ctx.beginPath();let valid=true;c.pivots.forEach((p,i)=>{let ix=p.index-start;if(ix<0||ix>=cs.length){valid=false;return}let x=ix*step+step/2,yy=y(p.price);if(i===0)ctx.moveTo(x,yy);else ctx.lineTo(x,yy)});if(valid)ctx.stroke();c.pivots.forEach((p,i)=>{let ix=p.index-start;if(ix<0||ix>=cs.length)return;let x=ix*step+step/2,yy=y(p.price);ctx.fillStyle='#ffd166';ctx.beginPath();ctx.arc(x,yy,6,0,Math.PI*2);ctx.fill();ctx.fillStyle='#10151d';ctx.font='bold 10px Arial';ctx.fillText(c.pattern==='impulse'?String(i+1):'ABC'[i]||'',x-3,yy+3)})}
ctx.fillStyle='#91a1b4';ctx.fillText(cs[0].time,8,h-8);ctx.fillText(cs.at(-1).time,w-170,h-8)}
async function save(){let c=state.candidates[state.selected];if(!c)return;let verdict=$('verdict').value,notes=$('notes').value.trim();if(verdict==='needs_correction'&&!notes){$('status').textContent='Add a correction note before saving.';return}let reviewerId=$('reviewerId').value.trim(),reviewerRole=$('reviewerRole').value,qualification=$('qualification').value.trim(),independent=$('independentReview').checked;if(!reviewerId){$('status').textContent='Enter a unique reviewer ID.';return}if(!independent){$('status').textContent='Confirm that the judgment is independent.';return}if(reviewerRole==='expert'&&qualification.length<12){$('status').textContent='Expert reviews require a qualification statement.';return}let body={candidate_id:state.data.timeframe+':'+c.pattern+':'+c.pivots[0].time+'-'+c.pivots.at(-1).time,symbol:'EURUSD',timeframe:state.data.timeframe,verdict:verdict,label:$('label').value,notes:notes,candidate:c,reviewed_at:new Date().toISOString(),reviewer_id:reviewerId,reviewer_role:reviewerRole,reviewer_qualification:qualification,independent_review:independent};let r=await fetch('/api/labels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let x=await r.json();$('status').textContent=x.ok?'Review saved to reviewed_labels.jsonl':x.error;$('labelcount').textContent=x.count+' reviewed labels saved'}
$('reload').onclick=load;$('pattern').onchange=renderList;$('save').onclick=save;$('next').onclick=()=>{if(state.candidates.length)select((state.selected+1)%state.candidates.length)};$('tf').onchange=load;$('bars').onchange=load;load().catch(e=>$('status').textContent='Error: '+e);
</script></body></html>"""

def load_candles(tf,count):
    path=DATA/TIMEFRAMES[tf]
    with path.open("r",newline="",encoding="utf-8-sig") as f: allrows=list(csv.DictReader(f))
    start=max(0,len(allrows)-count); rows=allrows[start:]; out=[]
    for r in rows:
        ts=float(r["timestamp"]); dt=datetime.fromtimestamp(ts/(1000 if ts>100_000_000_000 else 1),timezone.utc)
        out.append({"time":dt.strftime("%Y-%m-%d %H:%M"),**{k:float(r[k]) for k in ("open","high","low","close","volume")}})
    return out,start,len(allrows)

def get_payload(tf,bars):
    candles,start,total=load_candles(tf,bars)
    # Re-detect on the visible window so the chart always has pivots and hypotheses
    # for the exact bars being displayed, even when a saved Stage 1 snapshot is older.
    from eurusd_ai.market_data import Candle
    from Modules.Elliott_Waves.Detection.detector import detect_pivots
    from Modules.Elliott_Waves.Detection.engine import ElliottEngine
    thresholds={"M5":8.0,"M15":15.0,"H1":25.0,"H4":40.0,"D1":60.0}
    bars_as_candles=[Candle(x["time"],x["open"],x["high"],x["low"],x["close"],x["volume"]) for x in candles]
    pivots=detect_pivots(bars_as_candles,thresholds[tf],0.0001)
    candidates=[x.to_dict() for x in ElliottEngine(0.0001,25.0).analyze_pivots(pivots)]
    return {"timeframe":tf,"start_index":0,"source_start_index":start,"candles":candles,
            "pivots":[x.__dict__ for x in pivots],"candidates":candidates[:150]}

class Handler(BaseHTTPRequestHandler):
    def send_json(self,code,obj):
        data=json.dumps(obj,ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(data)
    def do_GET(self):
        u=urlparse(self.path)
        if u.path=="/":
            b=HTML.encode();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
        if u.path=="/api/data":
            q=parse_qs(u.query);tf=q.get("tf",["M15"])[0].upper();bars=max(100,min(1200,int(q.get("bars",["500"])[0])))
            if tf not in TIMEFRAMES:return self.send_json(400,{"error":"Unsupported timeframe"})
            try:return self.send_json(200,get_payload(tf,bars))
            except Exception as e:return self.send_json(500,{"error":str(e)})
        if u.path=="/api/labels":
            n=sum(1 for _ in LABEL_FILE.open(encoding="utf-8")) if LABEL_FILE.exists() else 0
            return self.send_json(200,{"count":n})
        return self.send_json(404,{})
    def do_POST(self):
        if self.path!="/api/labels":return self.send_json(404,{})
        try:
            item=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
            required={"candidate_id","timeframe","verdict","label","candidate","reviewed_at","reviewer_id","reviewer_role","reviewer_qualification","independent_review"}
            if not required.issubset(item):raise ValueError("Missing required review fields")
            if item["verdict"] not in {"accepted","rejected","needs_correction"}:raise ValueError("Invalid verdict")
            if item["timeframe"] not in TIMEFRAMES:raise ValueError("Invalid timeframe")
            if item["reviewer_role"] not in {"expert","non_expert"}:raise ValueError("Invalid reviewer role")
            if not str(item["reviewer_id"]).strip():raise ValueError("Reviewer ID is required")
            if item["independent_review"] is not True:raise ValueError("Independent review confirmation is required")
            if item["reviewer_role"]=="expert" and len(str(item["reviewer_qualification"]).strip())<12:raise ValueError("Expert qualification statement is required")
            if item["verdict"]=="needs_correction" and len(str(item.get("notes","")).strip())<10:raise ValueError("Correction notes are required")
            if LABEL_FILE.exists():
                for line in LABEL_FILE.read_text(encoding="utf-8").splitlines():
                    try:
                        old=json.loads(line)
                        if old.get("candidate_id")==item["candidate_id"] and old.get("reviewer_id")==item["reviewer_id"]:
                            raise ValueError("This reviewer has already reviewed this candidate")
                    except json.JSONDecodeError:continue
            with LABEL_FILE.open("a",encoding="utf-8") as f:f.write(json.dumps(item,ensure_ascii=False)+"\\n")
            n=sum(1 for _ in LABEL_FILE.open(encoding="utf-8"));return self.send_json(200,{"ok":True,"count":n})
        except Exception as e:return self.send_json(400,{"ok":False,"error":str(e)})
    def log_message(self,fmt,*args):print("%s - %s"%(self.log_date_time_string(),fmt%args))

def main():
    p=argparse.ArgumentParser(description="Local Elliott Wave chart and human-review lab")
    p.add_argument("--host",default="127.0.0.1");p.add_argument("--port",type=int,default=8765)
    a=p.parse_args();print("EURUSD Elliott Chart Lab: http://%s:%s"%(a.host,a.port));print("Human labels: "+str(LABEL_FILE))
    ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()
if __name__=="__main__":main()

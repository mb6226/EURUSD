import json, sqlite3
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from eurusd_ai_monitor.models.news_item import NewsItem
DEFAULT_DB=Path(__file__).resolve().parents[1]/"data"/"news"/"news.sqlite"
class NewsStore:
    """Separate news database; never touches market, macro or RAG storage."""
    def __init__(self,db_path=DEFAULT_DB):
        self.path=Path(db_path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self._connect()) as db:
            with db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS news_items(item_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,published_at_utc TEXT NOT NULL,retrieved_at_utc TEXT NOT NULL,payload_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at_utc DESC);
                CREATE TABLE IF NOT EXISTS news_revisions(revision_id INTEGER PRIMARY KEY AUTOINCREMENT,item_id TEXT NOT NULL,observed_at_utc TEXT NOT NULL,previous_payload_json TEXT NOT NULL,new_payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS news_source_state(source_id TEXT PRIMARY KEY,status TEXT NOT NULL,last_attempt_at_utc TEXT,last_success_at_utc TEXT,last_item_count INTEGER NOT NULL DEFAULT 0,last_error TEXT,updated_at_utc TEXT NOT NULL);
                """)
    def _connect(self):
        db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row; return db
    def upsert_items(self,items):
        changed=0
        with closing(self._connect()) as db:
            with db:
                for item in items:
                    data=item.to_dict(); payload=json.dumps(data,sort_keys=True,separators=(",",":"))
                    row=db.execute("SELECT payload_json FROM news_items WHERE item_id=?",(item.item_id,)).fetchone()
                    old=json.loads(row["payload_json"]) if row else None
                    sem=lambda d:{k:v for k,v in d.items() if k!="retrieved_at_utc"}
                    diff=sem(old)!=sem(data) if old else True
                    if row and diff: db.execute("INSERT INTO news_revisions(item_id,observed_at_utc,previous_payload_json,new_payload_json) VALUES(?,?,?,?)",(item.item_id,item.retrieved_at_utc.isoformat(),row["payload_json"],payload))
                    changed+=int(diff)
                    db.execute("""INSERT INTO news_items VALUES(?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET retrieved_at_utc=excluded.retrieved_at_utc,payload_json=excluded.payload_json""",(item.item_id,item.source_id,item.published_at_utc.isoformat(),item.retrieved_at_utc.isoformat(),payload))
        return changed
    def record_attempt(self,sid,at):
        stamp=at.astimezone(timezone.utc).isoformat()
        with closing(self._connect()) as db:
            with db: db.execute("""INSERT INTO news_source_state(source_id,status,last_attempt_at_utc,updated_at_utc) VALUES(?,'DEGRADED',?,?) ON CONFLICT(source_id) DO UPDATE SET last_attempt_at_utc=excluded.last_attempt_at_utc,updated_at_utc=excluded.updated_at_utc""",(sid,stamp,stamp))
    def record_success(self,sid,at,count):
        stamp=at.astimezone(timezone.utc).isoformat()
        with closing(self._connect()) as db:
            with db: db.execute("UPDATE news_source_state SET status='ACTIVE',last_success_at_utc=?,last_item_count=?,last_error=NULL,updated_at_utc=? WHERE source_id=?",(stamp,count,stamp,sid))
    def record_failure(self,sid,at,error):
        with closing(self._connect()) as db:
            with db: db.execute("UPDATE news_source_state SET status='FAILED',last_error=?,updated_at_utc=? WHERE source_id=?",(error[:500],at.astimezone(timezone.utc).isoformat(),sid))
    def get_source_state(self,sid):
        with closing(self._connect()) as db: row=db.execute("SELECT * FROM news_source_state WHERE source_id=?",(sid,)).fetchone()
        return dict(row) if row else {}
    def list_source_states(self):
        with closing(self._connect()) as db: return [dict(x) for x in db.execute("SELECT * FROM news_source_state ORDER BY source_id")]
    def list_recent(self,now,lookback_hours,limit=15):
        if lookback_hours<1 or not 1<=limit<=100: raise ValueError("invalid news context window")
        cutoff=(now.astimezone(timezone.utc)-timedelta(hours=lookback_hours)).isoformat()
        with closing(self._connect()) as db: rows=db.execute("SELECT payload_json FROM news_items WHERE published_at_utc>=? AND published_at_utc<=? ORDER BY published_at_utc DESC LIMIT ?",(cutoff,now.astimezone(timezone.utc).isoformat(),limit)).fetchall()
        out=[]
        for row in rows:
            d=json.loads(row["payload_json"]); d["published_at_utc"]=datetime.fromisoformat(d["published_at_utc"]); d["retrieved_at_utc"]=datetime.fromisoformat(d["retrieved_at_utc"])
            for k in ("categories","currencies","topics"): d[k]=tuple(d[k])
            out.append(NewsItem(**d))
        return out

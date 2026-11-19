import hashlib, json, re, urllib.error, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from eurusd_ai_monitor.models.news_item import NewsItem
from eurusd_ai_monitor.storage.news_store import NewsStore

DEFAULT_CONFIG=Path(__file__).resolve().parents[1]/"news_sources.json"
MAX_FEED_BYTES=2_000_000

def _local(tag): return tag.rsplit("}",1)[-1].casefold()
def _text(node,names):
    for child in list(node):
        if _local(child.tag) in names: return " ".join("".join(child.itertext()).split())
    return ""
def _date(value):
    try: dt=datetime.fromisoformat(value.strip().replace("Z","+00:00"))
    except ValueError: dt=parsedate_to_datetime(value.strip())
    if dt.tzinfo is None or dt.utcoffset() is None: raise ValueError("publication time lacks timezone")
    return dt.astimezone(timezone.utc)

def parse_feed(xml_text,source,retrieved_at_utc):
    if not isinstance(xml_text,str) or not xml_text.strip(): raise ValueError("empty feed")
    if len(xml_text.encode("utf-8"))>MAX_FEED_BYTES or "<!DOCTYPE" in xml_text.upper() or "<!ENTITY" in xml_text.upper(): raise ValueError("feed too large or DTD/entity forbidden")
    root=ET.fromstring(xml_text)
    entries=[x for x in root.iter() if _local(x.tag)=="item"] or [x for x in root.iter() if _local(x.tag)=="entry"]
    output=[]; host=urlsplit(source["url"]).hostname
    for e in entries:
        title=_text(e,("title",)); guid=_text(e,("guid","id")); link=""
        for child in list(e):
            if _local(child.tag)=="link":
                href=child.attrib.get("href")
                if href and child.attrib.get("rel","alternate") in ("alternate",""): link=href; break
                if child.text and child.text.strip(): link=child.text.strip(); break
        link=link or (guid if guid.startswith("https://") else "")
        published=_text(e,("pubdate","published","updated","date")); summary=_text(e,("description","summary","content","encoded"))
        if not title or not link or not published: continue
        u=urlsplit(link)
        if u.scheme!="https" or u.hostname!=host or u.username or u.password: continue
        iid=hashlib.sha256((source["source_id"]+"|"+(guid or link)).encode()).hexdigest()
        clean=lambda s,n: " ".join(unescape(re.sub(r"<[^>]*>"," ",s)).split())[:n]
        output.append(NewsItem(iid,source["source_id"],source["name"],source["publisher_role"],source["authority_tier"],clean(title,300),link,_date(published),retrieved_at_utc,clean(summary,1200),tuple(source.get("categories",[])),tuple(source.get("currencies",[])),tuple(source.get("topics",[]))))
    if entries and not output: raise ValueError("feed entries failed article validation")
    return tuple(sorted(output,key=lambda x:x.published_at_utc,reverse=True))

class NewsEngine:
    """Official RSS/Atom reader. News remains context-only."""
    def __init__(self,store:NewsStore,config_path=DEFAULT_CONFIG,fetcher=None,clock=None):
        self.store=store; self.config_path=Path(config_path); self.fetcher=fetcher or self._fetch
        self.clock=clock or (lambda:datetime.now(timezone.utc)); self.lock=Lock()
        doc=json.loads(self.config_path.read_text(encoding="utf-8"))
        if doc.get("schema_version")!=1 or not isinstance(doc.get("sources"),list): raise ValueError("invalid news config")
        self.sources=doc["sources"]; seen=set()
        for s in self.sources:
            u=urlsplit(s["url"])
            if u.scheme!="https" or not u.hostname or u.username or u.password: raise ValueError("feed URL must be credential-free HTTPS")
            if s["source_id"] in seen or not isinstance(s["refresh_seconds"],int) or s["refresh_seconds"]<60: raise ValueError("duplicate source or invalid interval")
            if s["publisher_role"] not in {"OFFICIAL_PRIMARY","REGULATOR"} or s["authority_tier"] not in {"A","B"}: raise ValueError("invalid source authority")
            seen.add(s["source_id"])
    @staticmethod
    def _fetch(source):
        req=urllib.request.Request(source["url"],headers={"User-Agent":"EURUSD-AI-Monitor/1.0","Accept":"application/rss+xml, application/atom+xml, application/xml"})
        try:
            with urllib.request.urlopen(req,timeout=8) as response:
                final=urlsplit(response.geturl())
                if final.scheme!="https" or final.hostname!=urlsplit(source["url"]).hostname: raise ValueError("redirect left configured host")
                body=response.read(MAX_FEED_BYTES+1)
        except (urllib.error.URLError,TimeoutError) as exc: raise RuntimeError(f"feed transport failed: {type(exc).__name__}") from exc
        if len(body)>MAX_FEED_BYTES: raise ValueError("feed response too large")
        return body.decode("utf-8-sig")
    def refresh_due(self):
        if not self.lock.acquire(blocking=False): return {"status":"BUSY"}
        results={}
        try:
            now=self.clock().astimezone(timezone.utc)
            for s in self.sources:
                if not s.get("enabled",False): continue
                state=self.store.get_source_state(s["source_id"]); last=state.get("last_attempt_at_utc")
                if last and (now-datetime.fromisoformat(last)).total_seconds()<s["refresh_seconds"]: continue
                self.store.record_attempt(s["source_id"],now)
                try:
                    items=parse_feed(self.fetcher(s),s,self.clock()); self.store.upsert_items(items)
                    self.store.record_success(s["source_id"],self.clock(),len(items)); results[s["source_id"]]="OK"
                except Exception as exc:
                    self.store.record_failure(s["source_id"],self.clock(),f"{type(exc).__name__}: {exc}"); results[s["source_id"]]="FAILED"
            return results
        finally: self.lock.release()
    def build_context(self,now_utc,lookback_hours=72,limit=15):
        now=now_utc.astimezone(timezone.utc); items=self.store.list_recent(now,lookback_hours,limit)
        stored={x["source_id"]:x for x in self.store.list_source_states()}
        states=[]
        for source in self.sources:
            if not source.get("enabled",False): continue
            state=dict(stored.get(source["source_id"],{"source_id":source["source_id"],"status":"NOT_CONNECTED","last_success_at_utc":None,"last_error":None,"last_item_count":0}))
            success=state.get("last_success_at_utc")
            stale_after=max(1800,source["refresh_seconds"]*3)
            if state["status"]=="ACTIVE" and (not success or (now-datetime.fromisoformat(success)).total_seconds()>stale_after):
                state["status"]="STALE"
            states.append(state)
        stale=[x["source_id"] for x in states if x["status"]!="ACTIVE"]
        return {"status":"DEGRADED" if stale else ("ACTIVE" if states else "NOT_CONFIGURED"),"evaluated_at_utc":now.isoformat(),
        "lookback_hours":lookback_hours,"source_states":states,"stale_sources":stale,"article_count":len(items),
        "articles":[x.to_dict() for x in items],"interpretation":"HEADLINES_AND_SOURCE_CONTEXT_ONLY","decision_authority":"CONTEXT_ONLY","trade_authority":"NONE"}

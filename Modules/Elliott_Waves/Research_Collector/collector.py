from __future__ import annotations
import hashlib, json, re, time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen
from .image_extractor import extract_chart_image

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "Modules/Elliott_Waves/Research_Collector/sources.json"
OUTPUT = ROOT / "Modules/Elliott_Waves/Dataset/external_references/collected_analyses.jsonl"
REPORT = ROOT / "Modules/Elliott_Waves/Dataset/external_references/latest_report.md"
PAIR = re.compile(r"\bEUR\s?[/\-]?\s?USD\b|\bEURUSD\b|\bEURO\s*/\s*DOLLAR\b", re.I)
EW = re.compile(r"elliott\s?wave|wave\s?(count|analysis|structure)|wave\s+[1-5ivxabc]", re.I)

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.meta={}; self.links=[]; self.images=[]
        self.href=None; self.parts=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="meta":
            k=(a.get("property") or a.get("name") or "").lower(); v=(a.get("content") or "").strip()
            if k and v: self.meta[k]=v
        elif tag=="link" and "canonical" in (a.get("rel") or "").lower() and a.get("href"):
            self.meta["canonical"]=a["href"]
        elif tag=="a": self.href=a.get("href"); self.parts=[]
        elif tag=="img":
            src=a.get("src") or a.get("data-src") or a.get("data-lazy-src")
            if src: self.images.append(src)
            srcset=a.get("srcset") or a.get("data-srcset") or ""
            if srcset:
                for entry in srcset.split(","):
                    candidate=entry.strip().split(" ")[0]
                    if candidate: self.images.append(candidate)
    def handle_data(self, data):
        if self.href is not None and data.strip(): self.parts.append(" ".join(data.split()))
    def handle_endtag(self, tag):
        if tag=="a" and self.href is not None:
            self.links.append((self.href," ".join(self.parts))); self.href=None; self.parts=[]

def fetch(url, agent, timeout, accept="text/html,application/xhtml+xml"):
    req=Request(url,headers={"User-Agent":agent,"Accept":accept})
    with urlopen(req,timeout=timeout) as res:
        if "html" not in res.headers.get("Content-Type","").lower():
            raise ValueError("Non-HTML response")
        return res.read(2_000_000).decode(res.headers.get_content_charset() or "utf-8",errors="replace"),res.geturl()

def parse(html):
    p=Parser(); p.feed(html); return p

def clean_url(url):
    p=urlparse(url); return urlunparse((p.scheme,p.netloc.lower(),p.path.rstrip("/"),"","",""))

def candidate(url,label,domain):
    p=urlparse(url)
    if p.scheme not in ("http","https") or not (p.hostname or "").lower().endswith(domain): return False
    return bool(PAIR.search(url+" "+label) and EW.search(url+" "+label))

def extract(title,desc):
    s=title+". "+desc
    tf=sorted(set(re.findall(r"\b(?:M\d+|H\d+|D1|W1|daily|weekly|4\s?hour|1\s?(?:minute|hour|day|week))\b",s,re.I)))
    bias="bullish" if re.search(r"\bbullish\b",s,re.I) else ("bearish" if re.search(r"\bbearish\b",s,re.I) else None)
    waves=sorted(set(re.findall(r"\b(?:wave\s*)?(?:\(\(?[ivxabc1-5]+\)?\)?|[ivxabc1-5])\b",s,re.I)))
    levels=sorted(set(re.findall(r"\b1\.\d{3,5}\b",s)))
    return {"timeframes_mentioned":tf,"bias_mentioned":bias,"wave_labels_mentioned":waves,
            "eurusd_price_levels_mentioned":levels,
            "extraction_note":"Pattern-based hints only; human verification required."}

def read_ids(path):
    ids=set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try: ids.add(json.loads(line).get("record_id"))
            except Exception: pass
    return ids

def collect():
    cfg=json.loads(CONFIG.read_text(encoding="utf-8")); OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    known=read_ids(OUTPUT); added=[]; errors=[]; checked=0; images_saved=0
    now=datetime.now(timezone.utc).isoformat()
    for src in cfg.get("sources",[]):
        if not src.get("enabled",True): continue
        sid,domain=src["id"],src["allowed_domain"]
        try:
            html,listing_url=fetch(src["listing_url"],cfg["user_agent"],int(cfg.get("request_timeout_seconds",20)))
            p=parse(html); urls={}
            for href,label in p.links:
                absolute=urljoin(listing_url,href)
                if candidate(absolute,label,domain): urls.setdefault(clean_url(absolute),label)
            for url,label in list(urls.items())[:int(cfg.get("max_articles_per_source",12))]:
                checked+=1
                try:
                    article,final=fetch(url,cfg["user_agent"],int(cfg.get("request_timeout_seconds",20)))
                    a=parse(article); canonical=clean_url(urljoin(final,a.meta.get("canonical",final)))
                    title=(a.meta.get("og:title") or a.meta.get("twitter:title") or a.meta.get("title") or label).strip()
                    desc=(a.meta.get("og:description") or a.meta.get("description") or a.meta.get("twitter:description") or "").strip()
                    if not PAIR.search(title+" "+desc+" "+url) or not EW.search(title+" "+desc+" "+url): continue
                    rid=hashlib.sha256((sid+"|"+canonical).encode()).hexdigest()[:20]
                    if rid in known: continue
                    image_urls=[]
                    for key in ("og:image","og:image:url","twitter:image","twitter:image:src"):
                        if a.meta.get(key): image_urls.append(urljoin(final,a.meta[key]))
                    image_urls.extend(urljoin(final,x) for x in a.images)
                    # Only download images hosted by the source's own domain.
                    image_domains=src.get("image_allowed_domains",[domain])
                    unique_images=list(dict.fromkeys(image_urls))[:int(cfg.get("max_images_per_article",2))]
                    rec={"schema_version":1,"record_id":rid,"source_id":sid,"source_name":src["name"],
                         "publisher_domain":domain,"url":canonical,"title":title,
                         "author":a.meta.get("author") or a.meta.get("article:author"),
                         "published_at":a.meta.get("article:published_time") or a.meta.get("date") or a.meta.get("pubdate"),
                         "modified_at":a.meta.get("article:modified_time"),"collected_at":now,
                         "description_excerpt":desc[:700],"pair":"EURUSD","automatic_extraction":extract(title,desc),
                         "chart_image_urls":unique_images,"chart_image_alt_text":a.meta.get("og:image:alt") or a.meta.get("twitter:image:alt"),"chart_images_extracted":0,
                         "review_status":"unreviewed","training_eligible":False,
                         "usage_note":"Metadata and short description only; chart image copies are local for private analysis. Check source terms and applicable rights; no public redistribution."}
                    for image_url in unique_images:
                        extracted=extract_chart_image(image_url,rec,image_domains,cfg["user_agent"],int(cfg.get("request_timeout_seconds",20)))
                        if extracted:
                            rec["chart_images_extracted"]+=1; images_saved+=1
                    added.append(rec); known.add(rid)
                except (HTTPError,URLError,TimeoutError,ValueError) as e: errors.append(f"{sid}: {url}: {type(e).__name__}: {e}")
                time.sleep(.4)
        except (HTTPError,URLError,TimeoutError,ValueError,KeyError) as e:
            errors.append(f"{sid}: listing: {type(e).__name__}: {e}")
    if added:
        with OUTPUT.open("a",encoding="utf-8") as f:
            for rec in added: f.write(json.dumps(rec,ensure_ascii=False)+"\n")
    lines=["# EURUSD Elliott Wave Research Collector","",f"- Run time (UTC): {now}",f"- Article pages checked: {checked}",
           f"- New references saved: {len(added)}",f"- Chart images locally extracted: {images_saved}",
           f"- Known references: {len(known)-len(added)}",f"- Errors: {len(errors)}","","## New references"]
    lines += ([f"- [{r['title']}]({r['url']}) — {r['source_name']} — {r.get('published_at') or 'date not detected'} — chart images: {r['chart_images_extracted']}" for r in added]
              if added else ["- No new matching public EURUSD Elliott Wave references found."])
    if errors: lines += ["","## Source errors"]+["- "+e for e in errors]
    lines += ["","## Data quality","- OCR detections are tentative and must be visually checked.",
              "- Text coordinates are normalized image coordinates, not candle time/price calibration.",
              "- References are unreviewed, not expert-confirmed ground truth.",
              "- Training eligibility remains false until review and rights checks.",
              "- No full article text is stored.",""]
    REPORT.write_text("\n".join(lines),encoding="utf-8")
    return {"checked":checked,"added":len(added),"images_saved":images_saved,"errors":errors,"output":str(OUTPUT),"report":str(REPORT)}

if __name__=="__main__": print(json.dumps(collect(),ensure_ascii=False,indent=2))

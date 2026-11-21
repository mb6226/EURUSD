from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from Modules.Elliott_Waves.Research_Collector.collector import fetch, parse
from Modules.Elliott_Waves.Research_Collector.image_extractor import extract_chart_image

BASE=ROOT/"Modules/Elliott_Waves/Dataset/external_references"
INDEX=BASE/"collected_analyses.jsonl"
CONFIG=ROOT/"Modules/Elliott_Waves/Research_Collector/sources.json"

def main():
    cfg=json.loads(CONFIG.read_text(encoding="utf-8"))
    sources={s["id"]:s for s in cfg.get("sources",[])}
    records=[json.loads(x) for x in INDEX.read_text(encoding="utf-8").splitlines() if x.strip()]
    extraction_index=BASE/"chart_image_extractions.jsonl"
    image_states={}
    if extraction_index.exists():
        for line in extraction_index.read_text(encoding="utf-8").splitlines():
            try:
                item=json.loads(line); image_states.setdefault(item.get("record_id"),{})[item.get("image_id")]=item
            except Exception: pass
    done=0; errors=[]; skipped=0
    for rec in records:
        prior=list(image_states.get(rec["record_id"],{}).values())
        if prior and all(x.get("ocr_status")=="completed" and x.get("extractor_version")==3 for x in prior):
            skipped+=1; continue
        src=sources.get(rec["source_id"])
        if not src: continue
        try:
            html,final=fetch(rec["url"],cfg["user_agent"],int(cfg.get("request_timeout_seconds",20)))
            page=parse(html)
            rec["chart_image_alt_text"]=page.meta.get("og:image:alt") or page.meta.get("twitter:image:alt")
            urls=[]
            for key in ("og:image","og:image:url","twitter:image","twitter:image:src"):
                if page.meta.get(key): urls.append(page.meta[key])
            from urllib.parse import urljoin
            urls += [urljoin(final,u) for u in page.images]
            for url in list(dict.fromkeys(urls))[:int(cfg.get("max_images_per_article",2))]:
                item=extract_chart_image(url,rec,src.get("image_allowed_domains",[src["allowed_domain"]]),
                                         cfg["user_agent"],int(cfg.get("request_timeout_seconds",20)))
                if item: done+=1
            time.sleep(.3)
        except Exception as exc:
            errors.append(f"{rec['record_id']}: {type(exc).__name__}: {exc}")
    print(f"Articles indexed: {len(records)}")
    print(f"Articles skipped (OCR complete): {skipped}")
    print(f"Chart images extracted or reprocessed: {done}")
    print(f"Errors: {len(errors)}")
    for error in errors: print("WARNING:",error)
if __name__=="__main__": main()

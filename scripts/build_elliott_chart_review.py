from __future__ import annotations
import html, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"Modules/Elliott_Waves/Dataset/external_references"
INDEX=BASE/"chart_image_extractions.jsonl"
OUT=BASE/"chart_review.html"

def main():
    records={}
    if INDEX.exists():
        for line in INDEX.read_text(encoding="utf-8").splitlines():
            try:
                item=json.loads(line); records[item["image_id"]]=item
            except Exception: pass
    cards=[]
    candidates=[item for item in records.values() if item.get("chart_candidate")]
    excluded=len(records)-len(candidates)
    for item in candidates:
        rel="chart_images/"+Path(item["local_image_path"]).name
        labels=", ".join(x.get("text","") for x in item.get("possible_wave_labels",[])) or "No wave labels OCR'd yet"
        prices=", ".join(x.get("text","") for x in item.get("possible_price_labels",[])) or "No price labels OCR'd yet"
        status=item.get("ocr_status","unknown")
        article=html.escape(item.get("article_url",""))
        title=html.escape(item.get("image_alt_text") or item.get("source_id","Chart image"))
        detections=[]
        for d in item.get("ocr_detections",[]):
            x,y=d.get("center_normalized",[0,0])
            detections.append(f"<li>{html.escape(d.get('text',''))} — conf {d.get('confidence',0):.2f} — x={x:.3f}, y={y:.3f}</li>")
        cards.append(f"""
        <article class="card">
          <h2>{title}</h2>
          <a href="{article}" target="_blank" rel="noreferrer">Open source article</a>
          <p>Status: <b>{html.escape(status)}</b> · Review: {html.escape(item.get('review_status',''))}</p>
          <img src="{html.escape(rel)}" alt="{title}">
          <p><b>Possible wave labels:</b> {html.escape(labels)}</p>
          <p><b>Possible price labels:</b> {html.escape(prices)}</p>
          <details><summary>OCR detections ({len(detections)})</summary><ul>{''.join(detections)}</ul></details>
        </article>""")
    page="""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
    <title>EURUSD Elliott Wave Chart Review</title>
    <style>body{font:15px system-ui;margin:24px;background:#f5f6f8;color:#20242a}h1{font-size:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:18px}.card{background:white;border:1px solid #ddd;border-radius:12px;padding:16px;overflow:hidden}.card img{display:block;width:100%;height:auto;margin:12px 0;border:1px solid #ddd}.card h2{font-size:18px}.card p{overflow-wrap:anywhere}a{color:#145bb8}</style>
    <h1>EURUSD Elliott Wave — Local Chart Review</h1><p>OCR suggestions are not expert-confirmed labels. Check every chart visually before marking any reference as training data.</p><p>Chart candidates: {candidate_count} · Excluded non-chart/unrecognized images: {excluded_count}</p>
    <div class="grid">"""+''.join(cards)+"</div></html>"
    page=page.replace("{candidate_count}",str(len(candidates))).replace("{excluded_count}",str(excluded))
    OUT.write_text(page,encoding="utf-8")
    print(f"Review page: {OUT}")
    print(f"Images indexed: {len(records)}")
if __name__=="__main__": main()

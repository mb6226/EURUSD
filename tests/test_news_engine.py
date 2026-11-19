import json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from eurusd_ai_monitor.engines.news_engine import NewsEngine,parse_feed
from eurusd_ai_monitor.storage.news_store import NewsStore
NOW=datetime(2026,11,19,12,tzinfo=timezone.utc)
SRC={"source_id":"TEST","name":"Test","url":"https://publisher.example/feed","publisher_role":"OFFICIAL_PRIMARY","authority_tier":"A","categories":["CENTRAL_BANK"],"currencies":["EUR"],"topics":["policy"]}
RSS="""<rss><channel><item><title>ECB update</title><link>https://publisher.example/a</link><guid>a1</guid><pubDate>Thu, 19 Nov 2026 10:00:00 GMT</pubDate><description><![CDATA[<p>Policy update</p>]]></description></item></channel></rss>"""
ATOM="""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Euro area</title><id>tag:publisher.example,2026:2</id><link href="https://publisher.example/b"/><updated>2026-11-19T11:00:00Z</updated></entry></feed>"""
class NewsTests(unittest.TestCase):
 def config(self,d):
  p=Path(d)/"sources.json"; p.write_text(json.dumps({"schema_version":1,"sources":[SRC|{"enabled":True,"refresh_seconds":60}]})); return p
 def test_rss(self):
  x=parse_feed(RSS,SRC,NOW)[0]; self.assertEqual(x.published_at_utc.hour,10); self.assertIn("Policy update",x.summary)
 def test_atom(self): self.assertEqual(parse_feed(ATOM,SRC,NOW)[0].title,"Euro area")
 def test_external_link_rejected(self):
  with self.assertRaises(ValueError): parse_feed(RSS.replace("https://publisher.example/a","https://evil.example/a"),SRC,NOW)
 def test_naive_date_rejected(self):
  with self.assertRaises(ValueError): parse_feed(RSS.replace("Thu, 19 Nov 2026 10:00:00 GMT","2026-11-19T10:00:00"),SRC,NOW)
 def test_refresh_context_and_authority(self):
  with tempfile.TemporaryDirectory() as d:
   store=NewsStore(Path(d)/"news.sqlite"); engine=NewsEngine(store,self.config(d),fetcher=lambda _:RSS,clock=lambda:NOW)
   self.assertEqual(engine.refresh_due(),{"TEST":"OK"}); ctx=engine.build_context(NOW)
   self.assertEqual(ctx["article_count"],1); self.assertEqual(ctx["trade_authority"],"NONE"); self.assertEqual(ctx["decision_authority"],"CONTEXT_ONLY")
 def test_failure_keeps_last_items(self):
  with tempfile.TemporaryDirectory() as d:
   store=NewsStore(Path(d)/"news.sqlite"); path=self.config(d)
   NewsEngine(store,path,fetcher=lambda _:RSS,clock=lambda:NOW).refresh_due()
   bad=NewsEngine(store,path,fetcher=lambda _:(_ for _ in ()).throw(RuntimeError("offline")),clock=lambda:NOW.replace(minute=2))
   self.assertEqual(bad.refresh_due(),{"TEST":"FAILED"}); self.assertEqual(len(store.list_recent(NOW,72)),1)
if __name__=="__main__": unittest.main()

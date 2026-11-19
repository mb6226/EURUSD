import unittest
from datetime import datetime,timedelta,timezone
from source_registry.adapters.cftc_positioning import CFTCPositioningAdapter,SOURCE_ID
from source_registry.adapters.models import FetchRequest
from source_registry.adapters.exceptions import FetchValidationError
from eurusd_ai_monitor.engines.positioning_sentiment_intelligence_engine import PositioningSentimentIntelligenceEngine
UTC=timezone.utc
def make_row(i=0,**changes):
 d=datetime(2026,1,6,tzinfo=UTC)+timedelta(days=7*i)
 r={"report_date":d.date().isoformat(),"published_at_utc":(d+timedelta(days=3,hours=15,minutes=30)).isoformat(),"contract_market_code":"099741","open_interest":1000,"dealer_long":200,"dealer_short":300,"asset_manager_long":400,"asset_manager_short":350,"leveraged_money_long":700+i*5,"leveraged_money_short":300}
 r.update(changes); return r
class CFTCPositioningTests(unittest.TestCase):
 def test_adapter_net_percent_of_oi(self):
  p="EURO_FX_LEVERAGED_MONEY_NET_OI_PCT"; a=CFTCPositioningAdapter(product_id=p,records_provider=lambda req:[make_row()])
  self.assertEqual(a.fetch(FetchRequest(SOURCE_ID,p)).observations[0].value,40)
 def test_reject_wrong_market_and_zero_oi(self):
  for change in ({"contract_market_code":"099741X"},{"open_interest":0}):
   p="EURO_FX_DEALER_NET_OI_PCT"; a=CFTCPositioningAdapter(product_id=p,records_provider=lambda req,c=change:[make_row(**c)])
   with self.assertRaises(FetchValidationError): a.fetch(FetchRequest(SOURCE_ID,p))
 def test_engine_asof_and_percentile(self):
  p="EURO_FX_LEVERAGED_MONEY_NET_OI_PCT"; rows=[]
  for i in range(30):
   a=CFTCPositioningAdapter(product_id=p,records_provider=lambda req,i=i:[make_row(i)])
   o=a.fetch(FetchRequest(SOURCE_ID,p)).observations[0]
   rows.append({"source_id":SOURCE_ID,"product_id":p,"effective_at_utc":o.effective_at_utc.isoformat(),"published_at_utc":o.published_at_utc.isoformat(),"retrieved_at_utc":(o.published_at_utc+timedelta(minutes=1)).isoformat(),"value":str(o.value),"payload_sha256":"a"*64})
  report=PositioningSentimentIntelligenceEngine().assess(as_of_utc=datetime(2026,12,1,tzinfo=UTC),observations={p:rows})
  item=report["groups"]["LEVERAGED_MONEY"]; self.assertEqual(item["status"],"AVAILABLE"); self.assertEqual(item["interpretation"],"NET_LONG"); self.assertIn("historical_percentile",item); self.assertEqual(report["decision_authority"],"CONTEXT_ONLY")
 def test_future_published_excluded(self):
  p="EURO_FX_DEALER_NET_OI_PCT"; r=make_row(published_at_utc=datetime(2026,12,2,tzinfo=UTC).isoformat())
  a=CFTCPositioningAdapter(product_id=p,records_provider=lambda req:[r]); o=a.fetch(FetchRequest(SOURCE_ID,p)).observations[0]
  row={"source_id":SOURCE_ID,"product_id":p,"effective_at_utc":o.effective_at_utc.isoformat(),"published_at_utc":o.published_at_utc.isoformat(),"retrieved_at_utc":datetime(2026,12,3,tzinfo=UTC).isoformat(),"value":str(o.value)}
  report=PositioningSentimentIntelligenceEngine().assess(as_of_utc=datetime(2026,12,1,tzinfo=UTC),observations={p:[row]})
  self.assertEqual(report["groups"]["DEALER"]["status"],"UNAVAILABLE")
if __name__=="__main__": unittest.main()

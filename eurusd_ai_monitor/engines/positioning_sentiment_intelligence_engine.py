from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

ALGORITHM_VERSION="positioning-sentiment-v1"
PRODUCTS={"EURO_FX_DEALER_NET_OI_PCT":"DEALER","EURO_FX_ASSET_MANAGER_NET_OI_PCT":"ASSET_MANAGER","EURO_FX_LEVERAGED_MONEY_NET_OI_PCT":"LEVERAGED_MONEY"}

def _time(value: object, field: str) -> datetime:
    if not isinstance(value,str): raise ValueError(f"{field} must be ISO-8601")
    try: parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc: raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)

def _decimal(value: object) -> Decimal:
    if isinstance(value,bool): raise ValueError("positioning value must be finite decimal")
    try: result=value if isinstance(value,Decimal) else Decimal(str(value))
    except (InvalidOperation,ValueError) as exc: raise ValueError("positioning value must be finite decimal") from exc
    if not result.is_finite(): raise ValueError("positioning value must be finite decimal")
    return result

class PositioningSentimentIntelligenceEngine:
    """Descriptive point-in-time CFTC positioning context, never a trade vote."""
    def __init__(self,*,max_age_days:int=14,lookback_weeks:int=52,minimum_history:int=26):
        for name,value in (("max_age_days",max_age_days),("lookback_weeks",lookback_weeks),("minimum_history",minimum_history)):
            if isinstance(value,bool) or not isinstance(value,int) or value<1: raise ValueError(f"{name} must be positive")
        if minimum_history<2 or minimum_history>lookback_weeks: raise ValueError("minimum_history must be 2..lookback_weeks")
        self._max_age=max_age_days; self._lookback=lookback_weeks; self._minimum=minimum_history
    def assess(self,*,as_of_utc:datetime,observations:Mapping[str,Sequence[Mapping[str,Any]]])->dict[str,Any]:
        if not isinstance(as_of_utc,datetime) or as_of_utc.tzinfo is None or as_of_utc.utcoffset() is None: raise ValueError("as_of_utc must be timezone-aware")
        if not isinstance(observations,Mapping): raise TypeError("observations must be a mapping")
        cutoff=as_of_utc.astimezone(timezone.utc); groups={}; reasons=[]
        for product,category in PRODUCTS.items():
            rows=observations.get(product,())
            if isinstance(rows,(str,bytes,Mapping)): raise TypeError(f"{product} rows must be a sequence")
            selected={}
            for row in rows:
                if not isinstance(row,Mapping): raise TypeError("rows must be mappings")
                if row.get("source_id")!="CFTC_TFF_POSITIONING" or row.get("product_id")!=product: continue
                effective=_time(row.get("effective_at_utc"),"effective_at_utc")
                published=_time(row.get("published_at_utc"),"published_at_utc")
                retrieved=_time(row.get("retrieved_at_utc"),"retrieved_at_utc")
                if effective<=cutoff and published<=cutoff and retrieved<=cutoff: selected[effective]=row
            ordered=sorted(selected.items())
            if not ordered:
                groups[category]={"status":"UNAVAILABLE","reason_codes":["NO_POINT_IN_TIME_OBSERVATIONS"]}; reasons.append(category+"_UNAVAILABLE"); continue
            latest_date,latest=ordered[-1]; age=cutoff-_time(latest["published_at_utc"],"published_at_utc")
            if age.days>self._max_age:
                groups[category]={"status":"STALE","latest_report_date":latest_date.date().isoformat(),"publication_age_days":age.days,"reason_codes":["CFTC_REPORT_STALE"]}; reasons.append(category+"_STALE"); continue
            values=[_decimal(row["value"]) for _,row in ordered[-self._lookback:]]
            current=values[-1]; prior=values[-2] if len(values)>1 else None
            result={"status":"AVAILABLE","category":category,"latest_report_date":latest_date.date().isoformat(),"published_at_utc":latest["published_at_utc"],"net_position_pct_open_interest":format(current,"f"),"weekly_change_percentage_points":format(current-prior,"f") if prior is not None else None,"history_count":len(values),"interpretation":"NET_LONG" if current>0 else ("NET_SHORT" if current<0 else "BALANCED"),"limitations":["CME EURO FX futures positioning is a proxy, not total EUR spot positioning."]}
            if len(values)>=self._minimum:
                less=sum(v<current for v in values); equal=sum(v==current for v in values)
                result["historical_percentile"]=format((Decimal(less)+Decimal(equal)/2)/Decimal(len(values))*100,".2f")
            else: result["reason_codes"]=["POSITIONING_HISTORY_BELOW_PERCENTILE_MINIMUM"]
            if latest.get("payload_sha256"): result["payload_sha256"]=latest["payload_sha256"]
            groups[category]=result
        count=sum(x["status"]=="AVAILABLE" for x in groups.values())
        return {"report_type":"POSITIONING_SENTIMENT_INTELLIGENCE","algorithm_version":ALGORITHM_VERSION,"evaluated_at_utc":cutoff.isoformat(),"instrument_proxy":"CME_EURO_FX_FUTURES","contract_market_code":"099741","report_family":"CFTC_TFF_FUTURES_ONLY","report_frequency":"WEEKLY","position_as_of":"TUESDAY_CLOSE","typical_publication":"FRIDAY_15_30_AMERICA_NEW_YORK","groups":groups,"status":"AVAILABLE" if count==len(PRODUCTS) else ("PARTIAL" if count else "UNAVAILABLE"),"reason_codes":sorted(set(reasons)),"decision_authority":"CONTEXT_ONLY","trade_authority":"NONE","order_execution":"DISABLED"}

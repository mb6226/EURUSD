from __future__ import annotations
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from .base import FetchAdapter
from .exceptions import FetchParseError, FetchValidationError
from .models import FetchRequest, FetchResult, Observation

SOURCE_ID = "CFTC_TFF_POSITIONING"
PRODUCT_CATEGORIES = {"EURO_FX_DEALER_NET_OI_PCT":"dealer", "EURO_FX_ASSET_MANAGER_NET_OI_PCT":"asset_manager", "EURO_FX_LEVERAGED_MONEY_NET_OI_PCT":"leveraged_money"}
SOURCE_URL = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
RecordsProvider = Callable[[FetchRequest], Iterable[Mapping[str, Any]]]

def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str): raise FetchValidationError(f"{field} must be ISO-8601")
    try: parsed = datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc: raise FetchValidationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise FetchValidationError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)

def _integer(value: object, field: str) -> int:
    if isinstance(value,bool): raise FetchValidationError(f"{field} must be a non-negative integer")
    try: result=int(str(value).strip())
    except (TypeError,ValueError) as exc: raise FetchValidationError(f"{field} must be a non-negative integer") from exc
    if result<0 or str(result)!=str(value).strip(): raise FetchValidationError(f"{field} must be a non-negative integer")
    return result

class CFTCPositioningAdapter(FetchAdapter):
    """Normalize injected official CFTC TFF Futures-Only CME EURO FX rows; no network I/O."""
    def __init__(self, *, product_id: str, records_provider: RecordsProvider) -> None:
        if product_id not in PRODUCT_CATEGORIES: raise FetchValidationError(f"Unsupported CFTC product: {product_id}")
        if not callable(records_provider): raise TypeError("records_provider must be callable")
        self.product_id=product_id; self.category=PRODUCT_CATEGORIES[product_id]; self._provider=records_provider
    def fetch(self, request: FetchRequest) -> FetchResult:
        if (request.source_id,request.product_id)!=(SOURCE_ID,self.product_id): raise FetchValidationError("CFTC adapter identity mismatch")
        raw=self._provider(request)
        if isinstance(raw,(str,bytes,Mapping)): raise FetchParseError("CFTC records must be iterable objects")
        try: iterator=iter(raw)
        except TypeError as exc: raise FetchParseError("CFTC records must be iterable") from exc
        output={}
        required={"report_date","published_at_utc","contract_market_code","open_interest","dealer_long","dealer_short","asset_manager_long","asset_manager_short","leveraged_money_long","leveraged_money_short"}
        for index,row in enumerate(iterator):
            if not isinstance(row,Mapping): raise FetchParseError(f"CFTC record {index} must be an object")
            missing=required.difference(row)
            if missing: raise FetchParseError(f"CFTC record missing: {', '.join(sorted(missing))}")
            if str(row["contract_market_code"]).strip()!="099741": raise FetchValidationError("Expected CME EURO FX contract market code 099741")
            try: report=datetime.strptime(str(row["report_date"]),"%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError as exc: raise FetchValidationError("report_date must use YYYY-MM-DD") from exc
            if report.weekday()!=1: raise FetchValidationError("report_date must be a Tuesday CFTC position date")
            published=_timestamp(row["published_at_utc"],"published_at_utc")
            if published<report: raise FetchValidationError("publication cannot precede Tuesday report date")
            oi=_integer(row["open_interest"],"open_interest")
            if oi<=0: raise FetchValidationError("open_interest must be positive")
            long=_integer(row[f"{self.category}_long"],"long"); short=_integer(row[f"{self.category}_short"],"short")
            value=Decimal(long-short)/Decimal(oi)*Decimal(100)
            item=Observation(SOURCE_ID,self.product_id,value,"percent_of_open_interest",report,published,f"EURO_FX_099741|{report.date()}")
            if report in output: raise FetchValidationError("Duplicate CFTC report date")
            output[report]=item
        if request.since is not None: output={at:item for at,item in output.items() if at>=request.since}
        if not output and request.since is None: raise FetchValidationError("CFTC full-history response is empty")
        ordered=tuple(output[key] for key in sorted(output))
        return FetchResult(SOURCE_ID,self.product_id,ordered,SOURCE_URL,len(ordered))

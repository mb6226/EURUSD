from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

@dataclass(frozen=True)
class NewsItem:
    item_id: str
    source_id: str
    source_name: str
    publisher_role: str
    authority_tier: str
    title: str
    url: str
    published_at_utc: datetime
    retrieved_at_utc: datetime
    summary: str = ""
    categories: tuple[str, ...] = ()
    currencies: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()

    def __post_init__(self):
        for key in ("item_id","source_id","source_name","title"):
            if not isinstance(getattr(self,key),str) or not getattr(self,key).strip(): raise ValueError(f"{key} required")
        if self.publisher_role not in {"OFFICIAL_PRIMARY","REGULATOR"} or self.authority_tier not in {"A","B"}: raise ValueError("invalid publisher authority")
        u=urlsplit(self.url)
        if u.scheme!="https" or not u.hostname or u.username or u.password: raise ValueError("article URL must be HTTPS")
        for key in ("published_at_utc","retrieved_at_utc"):
            v=getattr(self,key)
            if v.tzinfo is None or v.utcoffset() is None: raise ValueError(f"{key} must be timezone-aware")
            object.__setattr__(self,key,v.astimezone(timezone.utc))
        for key in ("categories","currencies","topics"):
            values=tuple(getattr(self,key))
            if any(not isinstance(x,str) or not x.strip() for x in values): raise ValueError(f"{key} must contain non-empty strings")
            if key=="currencies": values=tuple(x.upper() for x in values)
            object.__setattr__(self,key,tuple(dict.fromkeys(values)))

    def to_dict(self):
        return {"item_id":self.item_id,"source_id":self.source_id,"source_name":self.source_name,
        "publisher_role":self.publisher_role,"authority_tier":self.authority_tier,"title":self.title,"url":self.url,
        "published_at_utc":self.published_at_utc.isoformat(),"retrieved_at_utc":self.retrieved_at_utc.isoformat(),
        "summary":self.summary,"categories":list(self.categories),"currencies":list(self.currencies),"topics":list(self.topics)}

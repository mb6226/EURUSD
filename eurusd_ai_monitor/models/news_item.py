from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


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

    def __post_init__(self) -> None:
        for name in ("item_id", "source_id", "source_name", "title"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.publisher_role not in {"OFFICIAL_PRIMARY", "REGULATOR"}:
            raise ValueError("unsupported publisher_role")
        if self.authority_tier not in {"A", "B"}:
            raise ValueError("unsupported authority_tier")
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("article URL must be absolute HTTPS")
        object.__setattr__(self, "published_at_utc", _utc(self.published_at_utc, "published_at_utc"))
        object.__setattr__(self, "retrieved_at_utc", _utc(self.retrieved_at_utc, "retrieved_at_utc"))
        for field in ("categories", "currencies", "topics"):
            values = tuple(getattr(self, field))
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field} must contain non-empty strings")
            object.__setattr__(self, field, tuple(dict.fromkeys(v.upper() if field == "currencies" else v for v in values)))

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id, "source_id": self.source_id,
            "source_name": self.source_name, "publisher_role": self.publisher_role,
            "authority_tier": self.authority_tier, "title": self.title,
            "url": self.url, "published_at_utc": self.published_at_utc.isoformat(),
            "retrieved_at_utc": self.retrieved_at_utc.isoformat(),
            "summary": self.summary, "categories": list(self.categories),
            "currencies": list(self.currencies), "topics": list(self.topics),
        }

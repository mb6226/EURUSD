from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from eurusd_ai_monitor.storage.market_data_store import Candle
from .context_quality import ContextQuality


def _require_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable point-in-time market data shared by downstream engines."""

    symbol: str
    timestamp_utc: datetime
    broker_server: str
    m1_candles: tuple[Candle, ...]
    m5_candles: tuple[Candle, ...]
    tick: Mapping[str, object] | None
    spread_pips: Decimal | None
    quality: ContextQuality
    source: str = "MT5/MarketDataStore"

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be non-empty")
        if not isinstance(self.broker_server, str) or not self.broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be non-empty")
        object.__setattr__(self, "timestamp_utc", _require_utc(self.timestamp_utc, "timestamp_utc"))
        m1 = tuple(self.m1_candles)
        m5 = tuple(self.m5_candles)
        if any(not isinstance(c, Candle) for c in m1 + m5):
            raise TypeError("snapshot candle collections must contain Candle objects")
        if any(c.timeframe != "M1" for c in m1):
            raise ValueError("m1_candles must contain only M1 candles")
        if any(c.timeframe != "M5" for c in m5):
            raise ValueError("m5_candles must contain only M5 candles")
        if any(c.symbol != self.symbol or c.broker_server != self.broker_server for c in m1 + m5):
            raise ValueError("snapshot candles must match symbol and broker_server")
        object.__setattr__(self, "m1_candles", m1)
        object.__setattr__(self, "m5_candles", m5)
        if self.tick is not None:
            if not isinstance(self.tick, Mapping):
                raise TypeError("tick must be a mapping or None")
            object.__setattr__(self, "tick", MappingProxyType(dict(self.tick)))
        if self.spread_pips is not None:
            value = self.spread_pips if isinstance(self.spread_pips, Decimal) else Decimal(str(self.spread_pips))
            if not value.is_finite() or value < 0:
                raise ValueError("spread_pips must be finite and non-negative")
            object.__setattr__(self, "spread_pips", value)
        if not isinstance(self.quality, ContextQuality):
            raise TypeError("quality must be ContextQuality")

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from eurusd_ai_monitor.models.price_action import (
    EvidenceRef,
    EvidenceRole,
    MovementDirection,
)
from eurusd_ai_monitor.storage.market_data_store import Candle


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(value: Decimal, field_name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return value


def _nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _datetime_to_string(value: datetime) -> str:
    return _utc(value, "datetime").isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be an ISO datetime string")
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")), field_name)


def _parse_decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a decimal string")
    return _decimal(Decimal(value), field_name)


def _evidence_to_dict(ref: EvidenceRef) -> dict[str, Any]:
    candle = ref.candle
    return {
        "candle": {
            "broker_server": candle.broker_server,
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "candle_open_time_utc": _datetime_to_string(candle.candle_open_time_utc),
            "open": format(candle.open, "f"),
            "high": format(candle.high, "f"),
            "low": format(candle.low, "f"),
            "close": format(candle.close, "f"),
            "tick_volume": candle.tick_volume,
            "spread": candle.spread,
            "real_volume": candle.real_volume,
        },
        "role": ref.role.value,
        "confirmed_at_utc": _datetime_to_string(ref.confirmed_at_utc),
        "algorithm_version": ref.algorithm_version,
        "parameter_version": ref.parameter_version,
        "supporting_candle_ids": list(ref.supporting_candle_ids),
    }


def _evidence_from_dict(payload: Mapping[str, Any]) -> EvidenceRef:
    candle_data = payload["candle"]
    candle = Candle(
        broker_server=candle_data["broker_server"],
        symbol=candle_data["symbol"],
        timeframe=candle_data["timeframe"],
        candle_open_time_utc=_parse_datetime(
            candle_data["candle_open_time_utc"],
            "candle_open_time_utc",
        ),
        open=_parse_decimal(candle_data["open"], "open"),
        high=_parse_decimal(candle_data["high"], "high"),
        low=_parse_decimal(candle_data["low"], "low"),
        close=_parse_decimal(candle_data["close"], "close"),
        tick_volume=candle_data["tick_volume"],
        spread=candle_data["spread"],
        real_volume=candle_data["real_volume"],
    )
    return EvidenceRef(
        candle=candle,
        role=EvidenceRole(payload["role"]),
        confirmed_at_utc=_parse_datetime(
            payload["confirmed_at_utc"],
            "confirmed_at_utc",
        ),
        algorithm_version=payload["algorithm_version"],
        parameter_version=payload["parameter_version"],
        supporting_candle_ids=tuple(payload["supporting_candle_ids"]),
    )


@dataclass(frozen=True)
class Impulse:
    """A completed, confirmed M5 impulse built from TechnicalEngine pivots.

    Pivot formation times and pivot confirmation times are deliberately kept
    separate. The model does not depend on TechnicalEngine's Pivot class.
    """

    direction: MovementDirection
    start_pivot: EvidenceRef
    end_pivot: EvidenceRef
    start_price: Decimal
    end_price: Decimal
    pip_size: Decimal
    size_pips: Decimal
    started_at_utc: datetime
    ended_at_utc: datetime
    confirmed_at_utc: datetime
    algorithm_version: str
    parameter_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.direction, MovementDirection):
            raise TypeError("direction must be a MovementDirection")
        for name, ref in (("start_pivot", self.start_pivot), ("end_pivot", self.end_pivot)):
            if not isinstance(ref, EvidenceRef):
                raise TypeError(f"{name} must be an EvidenceRef")
            if ref.candle.timeframe != "M5":
                raise ValueError(f"{name} evidence must use M5")
            if ref.role is not EvidenceRole.TREND_PIVOT:
                raise ValueError(f"{name} evidence must have the TREND_PIVOT role")

        start_candle = self.start_pivot.candle
        end_candle = self.end_pivot.candle
        if (
            start_candle.broker_server != end_candle.broker_server
            or start_candle.symbol != end_candle.symbol
        ):
            raise ValueError("impulse pivots must belong to the same broker and symbol")
        if start_candle.candle_open_time_utc >= end_candle.candle_open_time_utc:
            raise ValueError("start pivot must occur before end pivot")
        if self.start_pivot.confirmed_at_utc > self.end_pivot.confirmed_at_utc:
            raise ValueError("start pivot cannot be confirmed after end pivot")
        if (
            self.start_pivot.algorithm_version != self.end_pivot.algorithm_version
            or self.start_pivot.parameter_version != self.end_pivot.parameter_version
        ):
            raise ValueError("impulse pivots must use matching evidence versions")

        start_price = _decimal(self.start_price, "start_price", positive=True)
        end_price = _decimal(self.end_price, "end_price", positive=True)
        pip_size = _decimal(self.pip_size, "pip_size", positive=True)
        size_pips = _decimal(self.size_pips, "size_pips", positive=True)

        if self.direction is MovementDirection.UP:
            if start_price != start_candle.low or end_price != end_candle.high:
                raise ValueError("UP impulse must run from start LOW to end HIGH")
            if end_price <= start_price:
                raise ValueError("UP impulse end price must exceed start price")
        else:
            if start_price != start_candle.high or end_price != end_candle.low:
                raise ValueError("DOWN impulse must run from start HIGH to end LOW")
            if end_price >= start_price:
                raise ValueError("DOWN impulse end price must be below start price")

        expected_size = abs(end_price - start_price) / pip_size
        if size_pips != expected_size:
            raise ValueError("size_pips must equal the price distance divided by pip_size")

        started = _utc(self.started_at_utc, "started_at_utc")
        ended = _utc(self.ended_at_utc, "ended_at_utc")
        confirmed = _utc(self.confirmed_at_utc, "confirmed_at_utc")
        if started != start_candle.candle_open_time_utc:
            raise ValueError("started_at_utc must match the start pivot formation time")
        if ended != end_candle.candle_open_time_utc:
            raise ValueError("ended_at_utc must match the end pivot formation time")
        if ended <= started:
            raise ValueError("ended_at_utc must follow started_at_utc")
        if confirmed != self.end_pivot.confirmed_at_utc:
            raise ValueError("confirmed_at_utc must match end pivot confirmation")
        if confirmed < ended:
            raise ValueError("impulse cannot be confirmed before its end pivot forms")
        object.__setattr__(self, "started_at_utc", started)
        object.__setattr__(self, "ended_at_utc", ended)
        object.__setattr__(self, "confirmed_at_utc", confirmed)

        _nonempty(self.algorithm_version, "algorithm_version")
        _nonempty(self.parameter_version, "parameter_version")
        if self.algorithm_version != self.end_pivot.algorithm_version:
            raise ValueError("algorithm_version must match pivot evidence")
        if self.parameter_version != self.end_pivot.parameter_version:
            raise ValueError("parameter_version must match pivot evidence")

    @property
    def impulse_id(self) -> str:
        start = self.start_pivot.candle
        end = self.end_pivot.candle
        return (
            f"{start.broker_server}|{start.symbol}|M5|"
            f"{start.candle_open_time_utc.isoformat()}|"
            f"{end.candle_open_time_utc.isoformat()}|"
            f"{self.algorithm_version}|{self.parameter_version}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "start_pivot": _evidence_to_dict(self.start_pivot),
            "end_pivot": _evidence_to_dict(self.end_pivot),
            "start_price": format(self.start_price, "f"),
            "end_price": format(self.end_price, "f"),
            "pip_size": format(self.pip_size, "f"),
            "size_pips": format(self.size_pips, "f"),
            "started_at_utc": _datetime_to_string(self.started_at_utc),
            "ended_at_utc": _datetime_to_string(self.ended_at_utc),
            "confirmed_at_utc": _datetime_to_string(self.confirmed_at_utc),
            "algorithm_version": self.algorithm_version,
            "parameter_version": self.parameter_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Impulse:
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        return cls(
            direction=MovementDirection(payload["direction"]),
            start_pivot=_evidence_from_dict(payload["start_pivot"]),
            end_pivot=_evidence_from_dict(payload["end_pivot"]),
            start_price=_parse_decimal(payload["start_price"], "start_price"),
            end_price=_parse_decimal(payload["end_price"], "end_price"),
            pip_size=_parse_decimal(payload["pip_size"], "pip_size"),
            size_pips=_parse_decimal(payload["size_pips"], "size_pips"),
            started_at_utc=_parse_datetime(payload["started_at_utc"], "started_at_utc"),
            ended_at_utc=_parse_datetime(payload["ended_at_utc"], "ended_at_utc"),
            confirmed_at_utc=_parse_datetime(
                payload["confirmed_at_utc"],
                "confirmed_at_utc",
            ),
            algorithm_version=payload["algorithm_version"],
            parameter_version=payload["parameter_version"],
        )

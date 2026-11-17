from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_STRATEGY_CONFIG_PATH = (
    Path(__file__).resolve().parent / "strategy_config.json"
)

_DECIMAL_FIELDS = (
    "pip_size",
    "min_correction_pips",
    "max_correction_ratio",
    "min_wick_body_ratio",
    "bullish_close_location_min",
    "bearish_close_location_max",
    "pullback_tolerance_pips",
    "stop_loss_pips",
    "take_profit_pips",
)

_INTEGER_FIELDS = (
    "config_schema_version",
    "pivot_left_bars",
    "pivot_right_bars",
    "setup_expiry_bars",
)

_BOOLEAN_FIELDS = (
    "trailing_stop_enabled",
    "parameters_validated",
    "live_signals_enabled",
)


def _positive_decimal(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")


@dataclass(frozen=True)
class StrategyConfig:
    config_schema_version: int
    strategy_version: str
    algorithm_version: str
    pip_size: Decimal
    pivot_left_bars: int
    pivot_right_bars: int
    min_correction_pips: Decimal
    max_correction_ratio: Decimal
    min_wick_body_ratio: Decimal
    bullish_close_location_min: Decimal
    bearish_close_location_max: Decimal
    pullback_tolerance_pips: Decimal
    setup_expiry_bars: int
    stop_loss_pips: Decimal
    take_profit_pips: Decimal
    trailing_stop_enabled: bool
    parameters_validated: bool
    live_signals_enabled: bool
    entry_gap_policy: str | None

    def __post_init__(self) -> None:
        for field_name in ("strategy_version", "algorithm_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")

        if type(self.config_schema_version) is not int or self.config_schema_version != 1:
            raise ValueError("config_schema_version must be 1")
        for field_name in (
            "pivot_left_bars",
            "pivot_right_bars",
            "setup_expiry_bars",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        for field_name in _DECIMAL_FIELDS:
            _positive_decimal(getattr(self, field_name), field_name)

        if self.max_correction_ratio > 1:
            raise ValueError("max_correction_ratio must not exceed 1")
        for field_name in (
            "bullish_close_location_min",
            "bearish_close_location_max",
        ):
            value = getattr(self, field_name)
            if value > 1:
                raise ValueError(f"{field_name} must be at most 1")
        for field_name in _BOOLEAN_FIELDS:
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be a boolean")
        if self.take_profit_pips <= self.stop_loss_pips:
            raise ValueError("take_profit_pips must exceed stop_loss_pips")
        if self.entry_gap_policy is not None and (
            not isinstance(self.entry_gap_policy, str)
            or not self.entry_gap_policy.strip()
        ):
            raise ValueError("entry_gap_policy must be a non-empty string or None")
        if self.live_signals_enabled and not self.parameters_validated:
            raise ValueError("unvalidated parameters cannot enable live signals")
        if self.live_signals_enabled and self.entry_gap_policy is None:
            raise ValueError("live signals require an explicit entry gap policy")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> StrategyConfig:
        expected = {field.name for field in fields(cls)}
        actual = set(payload)
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            raise ValueError(
                f"strategy config fields mismatch; missing={sorted(missing)}, "
                f"extra={sorted(extra)}"
            )

        values = dict(payload)
        for field_name in _DECIMAL_FIELDS:
            raw = values[field_name]
            if not isinstance(raw, str):
                raise TypeError(f"{field_name} must be a decimal string")
            try:
                values[field_name] = Decimal(raw)
            except InvalidOperation as exc:
                raise ValueError(f"{field_name} is not a decimal value") from exc
        return cls(**values)

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_STRATEGY_CONFIG_PATH,
    ) -> StrategyConfig:
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            raise ValueError("strategy config root must be a JSON object")
        return cls.from_mapping(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            field.name: (
                format(value, "f")
                if isinstance(value := getattr(self, field.name), Decimal)
                else value
            )
            for field in fields(self)
        }

    @property
    def parameter_digest(self) -> str:
        canonical = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def load_strategy_config(
    path: str | Path = DEFAULT_STRATEGY_CONFIG_PATH,
) -> StrategyConfig:
    return StrategyConfig.load(path)

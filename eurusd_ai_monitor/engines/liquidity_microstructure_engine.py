from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from eurusd_ai_monitor.storage.market_data_store import Candle, TIMEFRAME_SECONDS


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0) or (not positive and result < 0):
        raise ValueError(f"{field} is outside its valid range")
    return result


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _percentile(values: Sequence[Decimal], percentile: int) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, (len(ordered) * percentile + 99) // 100 - 1)
    return ordered[min(index, len(ordered) - 1)]


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> str | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return format((numerator / denominator).quantize(Decimal("0.0001")), "f")


class LiquidityMicrostructureEngine:
    """Research-only broker-feed liquidity proxies from closed MT5 candles.

    Each sample is {"candle": Candle, "pip_size": Decimal, "spread_pips":
    Decimal|None, "retrieved_at_utc": aware datetime}. MT5 candle.spread is
    deliberately not converted: its point scale is broker/symbol-specific.
    """

    VERSION = "1.0.0"

    def __init__(self, *, minimum_samples: int = 20, max_age_seconds: int = 180,
                 comparison_window: int = 5) -> None:
        for name, value in (("minimum_samples", minimum_samples),
                            ("max_age_seconds", max_age_seconds),
                            ("comparison_window", comparison_window)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if comparison_window * 2 > minimum_samples:
            raise ValueError("minimum_samples must cover both comparison windows")
        self.minimum_samples = minimum_samples
        self.max_age_seconds = max_age_seconds
        self.comparison_window = comparison_window

    def analyze(self, *, evaluated_at_utc: datetime, broker_server: str,
                symbol: str, samples: Sequence[Mapping[str, Any]]) -> dict:
        evaluated = _utc(evaluated_at_utc, "evaluated_at_utc")
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
            raise TypeError("samples must be a sequence of sample mappings")

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen: set[tuple[str, datetime]] = set()
        excluded_future = 0
        for index, sample in enumerate(samples):
            if not isinstance(sample, Mapping):
                raise TypeError(f"sample {index} must be a mapping")
            candle = sample.get("candle")
            if not isinstance(candle, Candle):
                raise TypeError(f"sample {index} candle must be a Candle")
            if candle.broker_server != broker_server or candle.symbol != symbol:
                raise ValueError("sample broker/symbol identity mismatch")
            retrieved = _utc(sample.get("retrieved_at_utc"), "retrieved_at_utc")
            if retrieved > evaluated:
                raise ValueError("sample retrieval timestamp is in the future")
            close_time = candle.candle_open_time_utc + timedelta(
                seconds=TIMEFRAME_SECONDS[candle.timeframe])
            if close_time > evaluated:
                excluded_future += 1
                continue
            key = (candle.timeframe, candle.candle_open_time_utc)
            if key in seen:
                raise ValueError("duplicate candle sample timestamp")
            seen.add(key)
            pip_size = _decimal(sample.get("pip_size"), "pip_size", positive=True)
            spread_raw = sample.get("spread_pips")
            spread = None if spread_raw is None else _decimal(
                spread_raw, "spread_pips")
            if spread is not None and spread <= 0:
                raise ValueError("spread_pips must be positive when supplied")
            candle_range = (candle.high - candle.low) / pip_size
            body = abs(candle.close - candle.open) / pip_size
            grouped[candle.timeframe].append({
                "candle": candle, "close_time": close_time,
                "retrieved_at": retrieved, "spread": spread,
                "tick_volume": Decimal(candle.tick_volume),
                "range_pips": candle_range, "body_pips": body,
            })

        frames = {}
        reasons = []
        for timeframe in ("M1", "M5"):
            rows = sorted(grouped.get(timeframe, []), key=lambda row: row["close_time"])
            if not rows:
                frames[timeframe] = {"status": "MISSING", "reason_codes": ["NO_CLOSED_CANDLES"]}
                reasons.append(f"{timeframe}_NO_CLOSED_CANDLES")
                continue
            latest = rows[-1]
            age = (evaluated - latest["close_time"]).total_seconds()
            if age < 0:
                frames[timeframe] = {"status": "DEGRADED", "reason_codes": ["FUTURE_CANDLE"]}
                reasons.append(f"{timeframe}_FUTURE_CANDLE")
                continue
            if age > self.max_age_seconds:
                frames[timeframe] = {
                    "status": "STALE", "age_seconds": int(age),
                    "sample_count": len(rows), "reason_codes": ["LATEST_CANDLE_STALE"],
                }
                reasons.append(f"{timeframe}_STALE")
                continue
            if len(rows) < self.minimum_samples:
                frames[timeframe] = {
                    "status": "INSUFFICIENT_DATA", "sample_count": len(rows),
                    "required_samples": self.minimum_samples,
                    "reason_codes": ["HISTORY_BELOW_MINIMUM"],
                }
                reasons.append(f"{timeframe}_HISTORY_BELOW_MINIMUM")
                continue

            spreads = [row["spread"] for row in rows if row["spread"] is not None]
            volumes = [row["tick_volume"] for row in rows]
            ranges = [row["range_pips"] for row in rows]
            bodies = [row["body_pips"] for row in rows]
            window = self.comparison_window
            recent, baseline = rows[-window:], rows[-2 * window:-window]
            recent_volume = _median([r["tick_volume"] for r in recent])
            baseline_volume = _median([r["tick_volume"] for r in baseline])
            recent_range = _median([r["range_pips"] for r in recent])
            baseline_range = _median([r["range_pips"] for r in baseline])
            recent_spreads = [r["spread"] for r in recent if r["spread"] is not None]
            baseline_spreads = [r["spread"] for r in baseline if r["spread"] is not None]
            recent_spread = _median(recent_spreads)
            baseline_spread = _median(baseline_spreads)
            spread_available = len(spreads) == len(rows)
            status = "AVAILABLE" if spread_available else "PARTIAL"
            frame_reasons = [] if spread_available else ["SPREAD_OBSERVATIONS_MISSING"]
            frames[timeframe] = {
                "status": status,
                "sample_count": len(rows),
                "latest_closed_candle_utc": latest["close_time"].isoformat(),
                "age_seconds": int(age),
                "spread": {
                    "unit": "pips",
                    "median": None if _median(spreads) is None else format(_median(spreads), "f"),
                    "p95": None if _percentile(spreads, 95) is None else format(_percentile(spreads, 95), "f"),
                    "recent_to_baseline_median_ratio": _ratio(recent_spread, baseline_spread),
                },
                "tick_activity": {
                    "unit": "broker_tick_count_per_candle",
                    "median": format(_median(volumes), "f"),
                    "p95": format(_percentile(volumes, 95), "f"),
                    "recent_to_baseline_median_ratio": _ratio(recent_volume, baseline_volume),
                },
                "price_range": {
                    "unit": "pips_per_candle",
                    "median": format(_median(ranges), "f"),
                    "p95": format(_percentile(ranges, 95), "f"),
                    "recent_to_baseline_median_ratio": _ratio(recent_range, baseline_range),
                },
                "body_to_range_median_ratio": _ratio(_median(bodies), _median(ranges)),
                "reason_codes": frame_reasons,
                "provenance": {
                    "source": "MT5 broker feed via MarketDataStore",
                    "broker_server": broker_server,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "first_candle_open_utc": rows[0]["candle"].candle_open_time_utc.isoformat(),
                    "last_candle_open_utc": latest["candle"].candle_open_time_utc.isoformat(),
                    "retrieved_at_utc": max(r["retrieved_at"] for r in rows).isoformat(),
                },
            }
            if frame_reasons:
                reasons.extend(f"{timeframe}_{code}" for code in frame_reasons)

        present = [value for value in frames.values() if value["status"] in {"AVAILABLE", "PARTIAL"}]
        if not present:
            overall = "UNAVAILABLE"
        elif any(value["status"] in {"STALE", "DEGRADED"} for value in frames.values()):
            overall = "DEGRADED"
        elif len(present) < 2 or any(value["status"] != "AVAILABLE" for value in frames.values()):
            overall = "PARTIAL"
        else:
            overall = "AVAILABLE"
        return {
            "status": overall,
            "engine_version": self.VERSION,
            "evaluated_at_utc": evaluated.isoformat(),
            "broker_server": broker_server,
            "symbol": symbol,
            "timeframes": frames,
            "excluded_unclosed_candle_count": excluded_future,
            "reason_codes": sorted(set(reasons)),
            "interpretation_limits": [
                "Broker-specific EURUSD spot-feed proxies only; not a consolidated FX market view.",
                "Tick volume is broker tick activity, not centralized traded volume.",
                "Candle spread points are not converted; supplied spread_pips must be independently normalized.",
                "No Level 2 order book, queue position, hidden liquidity, or market-wide depth is inferred.",
                "Metrics are descriptive context, not directional signals or execution instructions.",
            ],
            "decision_authority": "CONTEXT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

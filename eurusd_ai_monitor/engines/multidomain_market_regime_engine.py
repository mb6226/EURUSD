from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping


ALGORITHM_VERSION = "multidomain-market-regime-v1"
_REQUIRED_M5_BARS = 65


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


class MultiDomainMarketRegimeEngine:
    """Quality-gated regime synthesis over a unified, strict PIT data-plane snapshot.

    This layer does not fetch data, infer missing domains, emit trade signals, or
    modify execution/risk. It deliberately keeps domain coverage separate from
    market-regime conclusions.
    """

    def assess(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise TypeError("snapshot must be a unified data-plane mapping")
        as_of = _utc(snapshot.get("as_of_utc"))
        if as_of is None:
            return self._insufficient("INVALID_OR_MISSING_AS_OF_TIMESTAMP")
        if snapshot.get("read_mode") != "STRICT_SYSTEM_KNOWLEDGE":
            return self._insufficient("NON_STRICT_READ_MODE_BLOCKED")

        domain_states = {}
        analytics = snapshot.get("analytics_domains")
        if not isinstance(analytics, Mapping):
            analytics = {}
        for domain in (
            "spot_fx", "macro_fundamentals", "monetary_policy",
            "intermarket", "positioning_sentiment",
        ):
            item = analytics.get(domain)
            if not isinstance(item, Mapping):
                domain_states[domain] = {"status": "UNAVAILABLE", "eligible_products": 0}
            else:
                domain_states[domain] = {
                    "status": str(item.get("status", "UNKNOWN")),
                    "eligible_products": int(item.get("eligible_products", 0) or 0),
                    "observation_count": int(item.get("observation_count", 0) or 0),
                }

        spot, reason = self._select_m5(snapshot, as_of)
        if spot is None:
            report = self._insufficient(reason)
            report["domain_coverage"] = domain_states
            report["snapshot_sha256"] = snapshot.get("snapshot_sha256")
            report["as_of_utc"] = as_of.isoformat().replace("+00:00", "Z")
            report["available_context_domains"] = [
                name for name, state in domain_states.items()
                if state["eligible_products"] > 0
            ]
            return report

        candles = spot
        domain_states["spot_fx"]["status"] = "ELIGIBLE"
        domain_states["spot_fx"]["eligible_m5_streams"] = 1
        if len(candles) < _REQUIRED_M5_BARS:
            report = self._insufficient("INSUFFICIENT_QUALITY_ELIGIBLE_M5_HISTORY")
            report.update({
                "available_m5_bars": len(candles),
                "required_m5_bars": _REQUIRED_M5_BARS,
                "domain_coverage": domain_states,
                "snapshot_sha256": snapshot.get("snapshot_sha256"),
                "as_of_utc": as_of.isoformat().replace("+00:00", "Z"),
            })
            return report

        closes = [row["close"] for row in candles]
        recent = candles[-20:]
        recent_closes = [row["close"] for row in recent]
        path = sum(abs(b - a) for a, b in zip(recent_closes, recent_closes[1:]))
        efficiency = 0.0 if path == 0 else min(
            1.0, abs(recent_closes[-1] - recent_closes[0]) / path
        )
        displacement = recent_closes[-1] - recent_closes[0]
        direction = "UP" if displacement > 0 else "DOWN" if displacement < 0 else "UNCONFIRMED"
        if efficiency >= 0.35 and direction in {"UP", "DOWN"}:
            structure = "TRENDING"
        elif efficiency <= 0.20:
            structure = "RANGING"
        else:
            structure = "TRANSITIONAL"

        true_ranges = []
        for index, row in enumerate(candles):
            previous_close = candles[index - 1]["close"] if index else row["close"]
            true_ranges.append(max(
                row["high"] - row["low"],
                abs(row["high"] - previous_close),
                abs(row["low"] - previous_close),
            ))
        recent_atr = sum(true_ranges[-14:]) / 14
        baseline = true_ranges[-64:-14]
        baseline_atr = sum(baseline) / len(baseline)
        ratio = recent_atr / baseline_atr if baseline_atr > 0 else None
        volatility = (
            "UNKNOWN" if ratio is None else
            "HIGH" if ratio >= 1.50 else
            "LOW" if ratio <= 0.65 else "NORMAL"
        )

        context_domains = [
            name for name, state in domain_states.items()
            if name != "spot_fx" and state["eligible_products"] > 0
        ]
        missing_domains = [
            name for name, state in domain_states.items()
            if state["status"] not in {"ELIGIBLE", "AVAILABLE"}
        ]
        return {
            "report_type": "MULTI_DOMAIN_MARKET_REGIME_INTELLIGENCE",
            "algorithm_version": ALGORITHM_VERSION,
            "status": "PARTIAL" if missing_domains else "AVAILABLE",
            "regime_status": "AVAILABLE",
            "market_regime": structure,
            "trend_direction": direction,
            "volatility_state": volatility,
            "features": {
                "directional_efficiency_ratio": round(efficiency, 8),
                "recent_atr_price_units": round(recent_atr, 10),
                "baseline_atr_price_units": round(baseline_atr, 10),
                "atr_expansion_ratio": round(ratio, 8) if ratio is not None else None,
            },
            "domain_coverage": domain_states,
            "available_context_domains": context_domains,
            "missing_or_blocked_domains": missing_domains,
            "limitations": [
                "Price regime uses only quality-eligible, closed, point-in-time M5 candles.",
                "Macro, policy, intermarket and positioning coverage are reported separately; no absent domain is imputed.",
                "Available positioning observations are context only and cannot independently determine EURUSD market regime.",
                "Labels are descriptive classifications, not probabilities, forecasts, or trading performance claims.",
                "This assessment has no trade, order, sizing, or risk authority.",
            ],
            "provenance": {
                "read_mode": snapshot.get("read_mode"),
                "snapshot_sha256": snapshot.get("snapshot_sha256"),
                "registry_sha256": snapshot.get("registry_sha256"),
                "as_of_utc": snapshot.get("as_of_utc"),
                "symbol": "EURUSD",
                "timeframe": "M5",
                "m5_candle_count": len(candles),
                "m5_version_ids": [row.get("version_id") for row in candles],
                "m5_window_start_utc": candles[0]["open_time_utc"],
                "m5_window_end_utc": candles[-1]["close_time_utc"],
            },
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _select_m5(snapshot: Mapping[str, Any], as_of: datetime):
        archive = snapshot.get("spot_market_archive")
        if not isinstance(archive, Mapping):
            return None, "SPOT_MARKET_ARCHIVE_UNAVAILABLE"
        streams = archive.get("streams")
        if not isinstance(streams, list):
            return None, "SPOT_STREAM_METADATA_UNAVAILABLE"
        eligible = []
        for stream in streams:
            if not isinstance(stream, Mapping):
                continue
            if stream.get("symbol") != "EURUSD" or stream.get("timeframe") != "M5":
                continue
            if stream.get("status") != "PASS" or stream.get("eligible_for_analytics") is not True:
                continue
            rows = stream.get("candles")
            if not isinstance(rows, list):
                continue
            parsed = []
            valid = True
            previous_open = None
            for row in rows:
                if not isinstance(row, Mapping) or not isinstance(row.get("values"), Mapping):
                    valid = False
                    break
                opened = _utc(row.get("candle_open_time_utc"))
                closed = _utc(row.get("candle_close_time_utc"))
                observed = _utc(row.get("observed_at_utc"))
                cutoff = _utc(row.get("as_of_utc"))
                values = row["values"]
                o, h, l, c = (_finite(values.get(key)) for key in ("open", "high", "low", "close"))
                if (opened is None or closed is None or observed is None or cutoff is None
                        or any(v is None for v in (o, h, l, c))
                        or closed > as_of or observed > as_of or cutoff > as_of
                        or closed <= opened or (previous_open is not None and opened <= previous_open)
                        or h < max(o, l, c) or l > min(o, h, c)
                        or not row.get("version_id")):
                    valid = False
                    break
                parsed.append({
                    "open": o, "high": h, "low": l, "close": c,
                    "open_time_utc": opened.isoformat().replace("+00:00", "Z"),
                    "close_time_utc": closed.isoformat().replace("+00:00", "Z"),
                    "version_id": row["version_id"],
                })
                previous_open = opened
            if valid and parsed:
                eligible.append(parsed)
        if not eligible:
            return None, "NO_QUALITY_ELIGIBLE_EURUSD_M5_STREAM"
        if len(eligible) != 1:
            return None, "AMBIGUOUS_MULTIPLE_ELIGIBLE_EURUSD_M5_STREAMS"
        selected = eligible[0]
        if len(selected) < _REQUIRED_M5_BARS:
            return selected, None
        recent = selected[-_REQUIRED_M5_BARS:]
        for previous, current in zip(recent, recent[1:]):
            previous_open = _utc(previous["open_time_utc"])
            current_open = _utc(current["open_time_utc"])
            if current_open - previous_open != timedelta(minutes=5):
                return None, "M5_HISTORY_CONTAINS_GAPS"
        return recent, None

    @staticmethod
    def _insufficient(reason: str) -> dict[str, Any]:
        return {
            "report_type": "MULTI_DOMAIN_MARKET_REGIME_INTELLIGENCE",
            "algorithm_version": ALGORITHM_VERSION,
            "status": "INSUFFICIENT_EVIDENCE",
            "regime_status": "INSUFFICIENT_EVIDENCE",
            "market_regime": "UNKNOWN",
            "trend_direction": "UNKNOWN",
            "volatility_state": "UNKNOWN",
            "reason_codes": [reason],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

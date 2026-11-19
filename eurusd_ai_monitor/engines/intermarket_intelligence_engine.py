from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

INTERMARKET_ALGORITHM_VERSION = "intermarket-intelligence-v1"
EURUSD_IDENTITY = ("BROKER_SPOT_REFERENCE", "EURUSD_SPOT_REFERENCE", "usd_per_eur")

# Yield series are differenced in basis points; price/index series use percent
# changes. The broad USD index is not DXY and must never be labelled as DXY.
DRIVERS = {
    "US_10Y_TREASURY_YIELD": {
        "source_id": "FRED_INTERMARKET", "unit": "percent_per_annum",
        "change_method": "YIELD_CHANGE_BP", "max_age_days": 45,
    },
    "DE_10Y_GOVERNMENT_YIELD": {
        "source_id": "ECB_INTERMARKET", "unit": "percent_per_annum",
        "change_method": "YIELD_CHANGE_BP", "max_age_days": 45,
    },
    "USD_BROAD_TRADE_WEIGHTED_INDEX": {
        "source_id": "FRED_INTERMARKET", "unit": "index_points",
        "change_method": "PERCENT_CHANGE", "max_age_days": 5,
    },
    "GOLD_USD_TROY_OUNCE": {
        "source_id": "LBMA_INTERMARKET", "unit": "usd_per_troy_ounce",
        "change_method": "PERCENT_CHANGE", "max_age_days": 5,
    },
    "SP500_INDEX": {
        "source_id": "FRED_INTERMARKET", "unit": "index_points",
        "change_method": "PERCENT_CHANGE", "max_age_days": 5,
    },
}


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{field} must be a decimal scalar")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


class IntermarketIntelligenceEngine:
    """Point-in-time, descriptive cross-market return/change relationship engine.

    It aligns only exact observation timestamps. It never forward-fills,
    interpolates, forecasts, or turns correlation into a directional vote.
    """

    def __init__(
        self, *, lookback_observations: int = 120,
        minimum_observations: int = 20,
        max_eurusd_age_days: int = 5,
    ) -> None:
        for name, value in (
            ("lookback_observations", lookback_observations),
            ("minimum_observations", minimum_observations),
            ("max_eurusd_age_days", max_eurusd_age_days),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if minimum_observations < 3 or minimum_observations > lookback_observations:
            raise ValueError("minimum_observations must be >= 3 and <= lookback_observations")
        self._lookback = lookback_observations
        self._minimum = minimum_observations
        self._eurusd_max_age = max_eurusd_age_days

    def assess(
        self, *, as_of_utc: datetime,
        eurusd_observations: Sequence[Mapping[str, Any]],
        driver_observations: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> dict[str, Any]:
        if not isinstance(as_of_utc, datetime) or as_of_utc.tzinfo is None or as_of_utc.utcoffset() is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if not isinstance(driver_observations, Mapping):
            raise TypeError("driver_observations must be a mapping")
        cutoff = as_of_utc.astimezone(timezone.utc)
        eurusd = self._select(
            eurusd_observations, *EURUSD_IDENTITY, cutoff
        )
        base = {
            "report_type": "INTERMARKET_INTELLIGENCE",
            "algorithm_version": INTERMARKET_ALGORITHM_VERSION,
            "evaluated_at_utc": cutoff.isoformat(),
            "benchmark": "EURUSD_SPOT_REFERENCE",
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        if len(eurusd) < self._minimum + 1:
            return {
                **base, "status": "UNAVAILABLE",
                "reason_codes": ["EURUSD_REFERENCE_HISTORY_INSUFFICIENT"],
                "available_eurusd_observations": len(eurusd),
                "required_eurusd_observations": self._minimum + 1,
                "drivers": {},
            }
        if self._age_days(eurusd[-1]["effective_at_utc"], cutoff) > self._eurusd_max_age:
            return {
                **base, "status": "STALE",
                "reason_codes": ["EURUSD_REFERENCE_STALE"],
                "drivers": {},
                "eurusd_latest_at_utc": eurusd[-1]["effective_at_utc"].isoformat(),
            }

        eurusd_returns = self._changes(eurusd, "PERCENT_CHANGE")
        reports: dict[str, Any] = {}
        for product_id, definition in DRIVERS.items():
            rows = driver_observations.get(product_id, ())
            selected = self._select(
                rows, definition["source_id"], product_id,
                definition["unit"], cutoff,
            )
            reports[product_id] = self._compare(
                product_id, definition, selected, eurusd_returns, cutoff
            )

        available = sum(item["status"] == "AVAILABLE" for item in reports.values())
        status = "AVAILABLE" if available == len(reports) else "PARTIAL" if available else "UNAVAILABLE"
        return {
            **base,
            "status": status,
            "reason_codes": [] if available == len(reports) else ["ONE_OR_MORE_DRIVER_SERIES_UNAVAILABLE"],
            "eurusd_observation_count": len(eurusd),
            "eurusd_return_count": len(eurusd_returns),
            "drivers": reports,
            "interpretation_limits": [
                "Correlations describe the supplied historical sample; they are not causal effects or forecasts.",
                "One-period lead/lag correlations are exploratory descriptive statistics and do not establish predictive power.",
                "Only exact common return timestamps are aligned; no forward-fill, interpolation, or synthetic observations are used.",
                "Yield changes are measured in basis points; price and index series use percentage changes.",
                "USD_BROAD_TRADE_WEIGHTED_INDEX is a broad trade-weighted USD measure, not the ICE DXY index.",
                "US and German 10-year yield products may have different source calendars and observation frequencies; sample counts expose the resulting alignment loss.",
                "No EURUSD directional vote, probability, trade setup, strategy, risk instruction, or execution authority is produced.",
            ],
            "provenance": {
                "eurusd_source_id": EURUSD_IDENTITY[0],
                "eurusd_product_id": EURUSD_IDENTITY[1],
                "eurusd_observation_ids": [item["source_record_id"] for item in eurusd[-self._lookback - 1:]],
                "eurusd_payload_sha256": [item["payload_sha256"] for item in eurusd[-self._lookback - 1:]],
                "exact_timestamp_alignment": True,
            },
        }

    def _select(
        self, rows: Sequence[Mapping[str, Any]], source_id: str,
        product_id: str, unit: str, cutoff: datetime,
    ) -> list[dict[str, Any]]:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise TypeError("intermarket observations must be a sequence")
        latest: dict[datetime, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("intermarket observation must be a mapping")
            if (row.get("source_id"), row.get("product_id"), row.get("unit")) != (source_id, product_id, unit):
                raise ValueError("intermarket observation source/product/unit mismatch")
            effective = _timestamp(row.get("effective_at_utc"), "effective_at_utc")
            published = row.get("published_at_utc")
            if published is None:
                continue
            published_at = _timestamp(published, "published_at_utc")
            retrieved_at = _timestamp(row.get("retrieved_at_utc"), "retrieved_at_utc")
            if published_at < effective:
                raise ValueError("intermarket publication timestamp cannot precede observation time")
            if published_at > retrieved_at:
                raise ValueError("intermarket publication timestamp cannot follow retrieval timestamp")
            if effective > cutoff or published_at > cutoff or retrieved_at > cutoff:
                continue
            value = _decimal(row.get("value"), "intermarket value")
            record_id = row.get("source_record_id")
            version = row.get("version")
            digest = row.get("payload_sha256")
            if not isinstance(record_id, str) or not record_id.strip():
                raise ValueError("intermarket source_record_id is required")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError("intermarket version must be a positive integer")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("intermarket payload_sha256 must be a lowercase SHA-256 digest")
            candidate = {
                "source_id": source_id, "product_id": product_id, "unit": unit,
                "value": value, "effective_at_utc": effective,
                "published_at_utc": published_at, "retrieved_at_utc": retrieved_at,
                "source_record_id": record_id, "version": version,
                "payload_sha256": digest,
            }
            previous = latest.get(effective)
            if previous is None or (retrieved_at, version) > (
                previous["retrieved_at_utc"], previous["version"]
            ):
                latest[effective] = candidate
        return sorted(latest.values(), key=lambda item: item["effective_at_utc"])[-self._lookback - 1:]

    def _compare(
        self, product_id: str, definition: Mapping[str, Any],
        observations: list[dict[str, Any]], eurusd_returns: Mapping[datetime, Decimal],
        cutoff: datetime,
    ) -> dict[str, Any]:
        if len(observations) < self._minimum + 1:
            return {
                "status": "INSUFFICIENT_DATA",
                "reason_codes": ["DRIVER_HISTORY_INSUFFICIENT"],
                "observation_count": len(observations),
                "required_observations": self._minimum + 1,
            }
        if self._age_days(observations[-1]["effective_at_utc"], cutoff) > definition["max_age_days"]:
            return {
                "status": "STALE",
                "reason_codes": ["DRIVER_SERIES_STALE"],
                "observation_count": len(observations),
                "latest_at_utc": observations[-1]["effective_at_utc"].isoformat(),
            }
        driver_returns = self._changes(observations, definition["change_method"])
        common = sorted(set(eurusd_returns).intersection(driver_returns))
        if len(common) < self._minimum:
            return {
                "status": "INSUFFICIENT_DATA",
                "reason_codes": ["COMMON_TIMESTAMP_HISTORY_INSUFFICIENT"],
                "observation_count": len(observations),
                "aligned_return_count": len(common),
                "required_aligned_returns": self._minimum,
            }
        common = common[-self._lookback:]
        contemporaneous = self._correlation(
            [eurusd_returns[at] for at in common],
            [driver_returns[at] for at in common],
        )
        if contemporaneous is None:
            return {
                "status": "INSUFFICIENT_DATA",
                "reason_codes": ["ZERO_VARIANCE_IN_ALIGNED_RETURNS"],
                "change_method": definition["change_method"],
                "observation_count": len(observations),
                "aligned_return_count": len(common),
            }
        lead_pairs = [(driver_returns[common[i - 1]], eurusd_returns[common[i]]) for i in range(1, len(common))]
        lag_pairs = [(eurusd_returns[common[i - 1]], driver_returns[common[i]]) for i in range(1, len(common))]
        return {
            "status": "AVAILABLE",
            "reason_codes": [],
            "change_method": definition["change_method"],
            "observation_count": len(observations),
            "aligned_return_count": len(common),
            "sample_start_utc": common[0].isoformat(),
            "sample_end_utc": common[-1].isoformat(),
            "contemporaneous_correlation": contemporaneous,
            "driver_leads_one_period_correlation": self._correlation(
                [pair[0] for pair in lead_pairs], [pair[1] for pair in lead_pairs]
            ) if len(lead_pairs) >= self._minimum - 1 else None,
            "eurusd_leads_one_period_correlation": self._correlation(
                [pair[0] for pair in lag_pairs], [pair[1] for pair in lag_pairs]
            ) if len(lag_pairs) >= self._minimum - 1 else None,
            "provenance": {
                "source_id": definition["source_id"],
                "product_id": product_id,
                "observation_ids": [item["source_record_id"] for item in observations],
                "payload_sha256": [item["payload_sha256"] for item in observations],
            },
        }

    @staticmethod
    def _changes(observations: list[dict[str, Any]], method: str) -> dict[datetime, Decimal]:
        result: dict[datetime, Decimal] = {}
        for previous, current in zip(observations, observations[1:]):
            before, after = previous["value"], current["value"]
            if method == "PERCENT_CHANGE":
                if before <= 0 or after <= 0:
                    raise ValueError("price/index observations must be positive")
                change = (after / before - Decimal(1)) * Decimal(100)
            elif method == "YIELD_CHANGE_BP":
                change = (after - before) * Decimal(100)
            else:
                raise ValueError(f"unsupported intermarket change method: {method}")
            result[current["effective_at_utc"]] = change
        return result

    @staticmethod
    def _correlation(left: list[Decimal], right: list[Decimal]) -> str | None:
        if len(left) != len(right) or len(left) < 2:
            return None
        count = Decimal(len(left))
        mean_left = sum(left, Decimal(0)) / count
        mean_right = sum(right, Decimal(0)) / count
        centered_left = [value - mean_left for value in left]
        centered_right = [value - mean_right for value in right]
        sum_left = sum((value * value for value in centered_left), Decimal(0))
        sum_right = sum((value * value for value in centered_right), Decimal(0))
        if sum_left == 0 or sum_right == 0:
            return None
        covariance = sum((a * b for a, b in zip(centered_left, centered_right)), Decimal(0))
        value = covariance / (sum_left * sum_right).sqrt()
        value = max(Decimal(-1), min(Decimal(1), value))
        return format(value.quantize(Decimal("0.000001")), "f")

    @staticmethod
    def _age_days(effective: datetime, cutoff: datetime) -> Decimal:
        return Decimal(str((cutoff - effective).total_seconds())) / Decimal(86400)

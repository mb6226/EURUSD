from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

POLICY_DIFFERENTIAL_VERSION = "policy-rate-differential-v1"
ECB_SOURCE = "ECB_POLICY_RATES"
ECB_PRODUCT = "ECB_DEPOSIT_FACILITY_RATE"
FED_SOURCE = "FED_FOMC_POLICY"
FED_PRODUCT = "FED_TARGET_RANGE"


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
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a valid decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


class PolicyRateDifferentialEngine:
    """Point-in-time USD-minus-EUR policy-rate spread, preserving Fed range."""

    def __init__(self, *, max_observation_age: timedelta) -> None:
        if not isinstance(max_observation_age, timedelta) or max_observation_age <= timedelta(0):
            raise ValueError("max_observation_age must be a positive timedelta")
        self._max_age = max_observation_age

    def assess(
        self,
        *,
        as_of_utc: datetime,
        ecb_observations: Sequence[Mapping[str, Any]],
        fed_observations: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(as_of_utc, datetime) or as_of_utc.tzinfo is None or as_of_utc.utcoffset() is None:
            raise ValueError("as_of_utc must be timezone-aware")
        cutoff = as_of_utc.astimezone(timezone.utc)
        base = {
            "report_type": "FUNDAMENTAL_POLICY_RATE_DIFFERENTIAL",
            "algorithm_version": POLICY_DIFFERENTIAL_VERSION,
            "evaluated_at_utc": cutoff.isoformat(),
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
            "differential_definition": "USD federal-funds target range minus EUR ECB deposit-facility rate",
            "unit": "percentage_points",
        }
        ecb = self._select(
            ecb_observations, source=ECB_SOURCE, product=ECB_PRODUCT,
            as_of=cutoff, range_value=False,
        )
        fed = self._select(
            fed_observations, source=FED_SOURCE, product=FED_PRODUCT,
            as_of=cutoff, range_value=True,
        )
        if ecb is None or fed is None:
            missing = []
            if ecb is None:
                missing.append("ECB_DEPOSIT_FACILITY_RATE")
            if fed is None:
                missing.append("FED_TARGET_RANGE")
            return {
                **base, "status": "UNAVAILABLE",
                "reason_codes": ["REQUIRED_POLICY_RATE_EVIDENCE_MISSING"],
                "missing_products": missing,
            }

        ecb_age = cutoff - ecb["effective_at_utc"]
        fed_age = cutoff - fed["effective_at_utc"]
        stale = []
        if ecb_age > self._max_age:
            stale.append("ECB_DEPOSIT_FACILITY_RATE")
        if fed_age > self._max_age:
            stale.append("FED_TARGET_RANGE")
        if stale:
            return {
                **base, "status": "STALE",
                "reason_codes": ["POLICY_RATE_EVIDENCE_EXCEEDS_MAX_AGE"],
                "stale_products": stale,
                "max_observation_age_seconds": int(self._max_age.total_seconds()),
                "provenance": self._provenance(ecb, fed),
            }

        ecb_rate = ecb["value"]
        fed_low, fed_high = fed["value"]
        low = fed_low - ecb_rate
        high = fed_high - ecb_rate
        return {
            **base,
            "status": "AVAILABLE",
            "reason_codes": [],
            "usd_minus_eur_spread": {
                "low": format(low, "f"),
                "high": format(high, "f"),
            },
            "interpretation_limits": [
                "This is a policy-rate spread, not a market-implied rate path or expected return.",
                "The Fed target is a range and remains a range after subtraction.",
                "The ECB deposit-facility rate is the selected EUR policy proxy; it is not interchangeable with the ECB main refinancing or marginal lending rates.",
                "A positive spread does not by itself imply EURUSD direction or timing.",
                "No forecast, signal, strategy, risk instruction, or execution authority is produced.",
            ],
            "provenance": self._provenance(ecb, fed),
        }

    @staticmethod
    def _select(
        rows: Sequence[Mapping[str, Any]], *, source: str, product: str,
        as_of: datetime, range_value: bool,
    ) -> dict[str, Any] | None:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise TypeError("observations must be a sequence of stored observation mappings")
        eligible = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("stored observation must be a mapping")
            if row.get("source_id") != source or row.get("product_id") != product:
                raise ValueError("observation source/product identity mismatch")
            if row.get("unit") != "percent_per_annum":
                raise ValueError("policy-rate observation has an unexpected unit")
            effective = _timestamp(row.get("effective_at_utc"), "effective_at_utc")
            published = row.get("published_at_utc")
            retrieved = _timestamp(row.get("retrieved_at_utc"), "retrieved_at_utc")
            if published is None:
                continue
            published_at = _timestamp(published, "published_at_utc")
            if effective > as_of or published_at > as_of or retrieved > as_of:
                continue
            raw_value = row.get("value")
            if range_value:
                if not isinstance(raw_value, Mapping) or set(raw_value) != {"low", "high"}:
                    raise ValueError("Fed target range must contain exactly low/high")
                low = _decimal(raw_value["low"], "Fed low")
                high = _decimal(raw_value["high"], "Fed high")
                if low > high:
                    raise ValueError("Fed target range low must not exceed high")
                value: Any = (low, high)
            else:
                value = _decimal(raw_value, "ECB rate")
            eligible.append({
                "value": value, "effective_at_utc": effective,
                "published_at_utc": published_at,
                "retrieved_at_utc": retrieved,
                "observation_key": row.get("observation_key"),
                "version": row.get("version"),
                "payload_sha256": row.get("payload_sha256"),
                "source_record_id": row.get("source_record_id"),
            })
        if not eligible:
            return None
        return max(
            eligible,
            key=lambda item: (
                item["effective_at_utc"], item["retrieved_at_utc"],
                item["version"] if isinstance(item["version"], int) else 0,
            ),
        )

    @staticmethod
    def _provenance(ecb: Mapping[str, Any], fed: Mapping[str, Any]) -> dict[str, Any]:
        def compact(item: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "effective_at_utc": item["effective_at_utc"].isoformat(),
                "published_at_utc": item["published_at_utc"].isoformat(),
                "retrieved_at_utc": item["retrieved_at_utc"].isoformat(),
                "source_record_id": item["source_record_id"],
                "payload_sha256": item["payload_sha256"],
            }
        return {
            "eur_reference": {"source_id": ECB_SOURCE, "product_id": ECB_PRODUCT, **compact(ecb)},
            "usd_reference": {"source_id": FED_SOURCE, "product_id": FED_PRODUCT, **compact(fed)},
            "point_in_time_cutoff_utc": None,
        }

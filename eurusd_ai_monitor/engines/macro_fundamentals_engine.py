from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

MACRO_FUNDAMENTALS_VERSION = "cross-atlantic-macro-fundamentals-v1"

SERIES = {
    "us_cpi": ("US_BLS_MACRO", "US_CPI_ALL_ITEMS_INDEX", "index_1982_84_100"),
    "us_unemployment": ("US_BLS_MACRO", "US_UNEMPLOYMENT_RATE", "percent_of_labor_force"),
    "ea_hicp": ("EUROSTAT_MACRO", "EA_HICP_ALL_ITEMS_INDEX", "index_2015_100"),
    "ea_unemployment": ("EUROSTAT_MACRO", "EA_UNEMPLOYMENT_RATE", "percent_of_labor_force"),
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
        raise ValueError(f"{field} must be a decimal value")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _month(value: datetime) -> tuple[int, int]:
    return value.year, value.month


class MacroFundamentalsEngine:
    """Point-in-time inflation and unemployment comparisons for US and euro area.

    CPI and HICP are intentionally reported separately with a qualified spread:
    their baskets and statistical frameworks are not identical. US and euro-area
    unemployment rates also use different statistical definitions. No consensus,
    forecast, directional vote, or trading authority is inferred.
    """

    def __init__(self, *, max_current_observation_age_days: int = 75) -> None:
        if isinstance(max_current_observation_age_days, bool) or not isinstance(
            max_current_observation_age_days, int
        ) or max_current_observation_age_days <= 0:
            raise ValueError("max_current_observation_age_days must be a positive integer")
        self._max_age_days = max_current_observation_age_days

    def assess(
        self,
        *,
        as_of_utc: datetime,
        us_cpi_observations: Sequence[Mapping[str, Any]],
        us_unemployment_observations: Sequence[Mapping[str, Any]],
        ea_hicp_observations: Sequence[Mapping[str, Any]],
        ea_unemployment_observations: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(as_of_utc, datetime) or as_of_utc.tzinfo is None or as_of_utc.utcoffset() is None:
            raise ValueError("as_of_utc must be timezone-aware")
        cutoff = as_of_utc.astimezone(timezone.utc)
        inputs = {
            "us_cpi": us_cpi_observations,
            "us_unemployment": us_unemployment_observations,
            "ea_hicp": ea_hicp_observations,
            "ea_unemployment": ea_unemployment_observations,
        }
        selected = {
            name: self._select(rows, *SERIES[name], cutoff)
            for name, rows in inputs.items()
        }
        inflation = self._inflation(selected["us_cpi"], selected["ea_hicp"], cutoff)
        unemployment = self._unemployment(
            selected["us_unemployment"], selected["ea_unemployment"], cutoff
        )
        dimensions = (inflation, unemployment)
        available = sum(item["status"] == "AVAILABLE" for item in dimensions)
        status = "AVAILABLE" if available == 2 else "PARTIAL" if available == 1 else "UNAVAILABLE"
        return {
            "report_type": "CROSS_ATLANTIC_MACRO_FUNDAMENTALS",
            "algorithm_version": MACRO_FUNDAMENTALS_VERSION,
            "evaluated_at_utc": cutoff.isoformat(),
            "status": status,
            "reason_codes": [
                reason for item in dimensions for reason in item.get("reason_codes", [])
            ],
            "inflation": inflation,
            "unemployment": unemployment,
            "interpretation_limits": [
                "US CPI and euro-area HICP are distinct statistical measures; their spread is a qualified comparison, not a perfectly harmonized index.",
                "US unemployment and euro-area harmonized unemployment have different statistical definitions; the gap is contextual, not a like-for-like labor-market score.",
                "Year-over-year inflation is calculated from the same series and reference month 12 months apart; no missing month is interpolated.",
                "Only observations published and retrieved no later than the as-of cutoff are eligible.",
                "No consensus estimate, surprise, forecast, EURUSD direction, probability, signal, strategy, risk instruction, or execution authority is produced.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    def _select(
        self,
        rows: Sequence[Mapping[str, Any]],
        source_id: str,
        product_id: str,
        unit: str,
        cutoff: datetime,
    ) -> dict[tuple[int, int], dict[str, Any]]:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise TypeError("macro observations must be a sequence of stored observation mappings")
        latest: dict[tuple[int, int], dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("macro observation must be a mapping")
            if row.get("source_id") != source_id or row.get("product_id") != product_id:
                raise ValueError("macro observation source/product identity mismatch")
            if row.get("unit") != unit:
                raise ValueError("macro observation unit mismatch")
            effective = _timestamp(row.get("effective_at_utc"), "effective_at_utc")
            published_raw = row.get("published_at_utc")
            if published_raw is None:
                continue
            published = _timestamp(published_raw, "published_at_utc")
            retrieved = _timestamp(row.get("retrieved_at_utc"), "retrieved_at_utc")
            if effective > cutoff or published > cutoff or retrieved > cutoff:
                continue
            if effective.day != 1 or effective.hour or effective.minute or effective.second or effective.microsecond:
                raise ValueError("macro effective timestamp must be the first day of its reference month at 00:00 UTC")
            value = _decimal(row.get("value"), "macro value")
            source_record_id = row.get("source_record_id")
            version = row.get("version")
            payload_sha256 = row.get("payload_sha256")
            if not isinstance(source_record_id, str) or not source_record_id.strip():
                raise ValueError("macro observation source_record_id is required")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError("macro observation version must be a positive integer")
            if not isinstance(payload_sha256, str) or len(payload_sha256) != 64 or any(
                char not in "0123456789abcdef" for char in payload_sha256
            ):
                raise ValueError("macro observation payload_sha256 must be a lowercase SHA-256 digest")
            key = _month(effective)
            candidate = {
                "source_id": source_id,
                "product_id": product_id,
                "unit": unit,
                "value": value,
                "effective_at_utc": effective,
                "published_at_utc": published,
                "retrieved_at_utc": retrieved,
                "source_record_id": source_record_id,
                "version": version,
                "payload_sha256": payload_sha256,
            }
            prior = latest.get(key)
            if prior is None or (
                candidate["retrieved_at_utc"], candidate["version"]
            ) > (prior["retrieved_at_utc"], prior["version"]):
                latest[key] = candidate
        return latest

    def _fresh(self, item: dict[str, Any] | None, cutoff: datetime) -> bool:
        return bool(
            item is not None
            and (cutoff - item["effective_at_utc"]).total_seconds()
            <= self._max_age_days * 86400
        )

    @staticmethod
    def _evidence(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": item["source_id"],
            "product_id": item["product_id"],
            "unit": item["unit"],
            "effective_at_utc": item["effective_at_utc"].isoformat(),
            "published_at_utc": item["published_at_utc"].isoformat(),
            "retrieved_at_utc": item["retrieved_at_utc"].isoformat(),
            "source_record_id": item["source_record_id"],
            "version": item["version"],
            "payload_sha256": item["payload_sha256"],
        }

    def _inflation(self, us: dict, ea: dict, cutoff: datetime) -> dict[str, Any]:
        if not us or not ea:
            return {"status": "UNAVAILABLE", "reason_codes": ["INFLATION_SERIES_MISSING"]}
        common_periods = set(us).intersection(ea)
        if not common_periods:
            return {
                "status": "UNAVAILABLE",
                "reason_codes": ["INFLATION_REFERENCE_MONTHS_NOT_ALIGNED"],
                "us_latest_reference_month": f"{max(us)[0]:04d}-{max(us)[1]:02d}",
                "ea_latest_reference_month": f"{max(ea)[0]:04d}-{max(ea)[1]:02d}",
            }
        period = max(common_periods)
        prior_year = (period[0] - 1, period[1])
        us_now, us_prior = us[period], us.get(prior_year)
        ea_now, ea_prior = ea[period], ea.get(prior_year)
        # Freshness is a property of the selected current observations and must
        # be reported before checking the historical YoY baseline. Otherwise a
        # stale current month with a missing 12-month baseline is misclassified
        # as merely unavailable, hiding the more important data-quality state.
        if not self._fresh(us_now, cutoff) or not self._fresh(ea_now, cutoff):
            return {
                "status": "STALE",
                "reason_codes": ["INFLATION_CURRENT_OBSERVATION_STALE"],
                "reference_month": f"{period[0]:04d}-{period[1]:02d}",
                "provenance": {
                    "us_current": self._evidence(us_now),
                    "euro_area_current": self._evidence(ea_now),
                },
            }
        if not all((us_prior, ea_prior)):
            return {
                "status": "UNAVAILABLE",
                "reason_codes": ["INFLATION_YEAR_AGO_BASELINE_MISSING"],
                "reference_month": f"{period[0]:04d}-{period[1]:02d}",
            }
        if min(us_now["value"], us_prior["value"], ea_now["value"], ea_prior["value"]) <= 0:
            raise ValueError("CPI/HICP index values must be positive")
        us_yoy = (us_now["value"] / us_prior["value"] - Decimal(1)) * Decimal(100)
        ea_yoy = (ea_now["value"] / ea_prior["value"] - Decimal(1)) * Decimal(100)
        return {
            "status": "AVAILABLE",
            "reason_codes": [],
            "reference_month": f"{period[0]:04d}-{period[1]:02d}",
            "us_cpi_yoy_percent": format(us_yoy, "f"),
            "euro_area_hicp_yoy_percent": format(ea_yoy, "f"),
            "us_minus_euro_area_inflation_pp": format(us_yoy - ea_yoy, "f"),
            "provenance": {
                "us_current": self._evidence(us_now),
                "us_year_ago": self._evidence(us_prior),
                "euro_area_current": self._evidence(ea_now),
                "euro_area_year_ago": self._evidence(ea_prior),
            },
        }

    def _unemployment(self, us: dict, ea: dict, cutoff: datetime) -> dict[str, Any]:
        common = sorted(set(us).intersection(ea))
        if not common:
            return {"status": "UNAVAILABLE", "reason_codes": ["UNEMPLOYMENT_COMMON_MONTH_MISSING"]}
        period = common[-1]
        us_item, ea_item = us[period], ea[period]
        if not self._fresh(us_item, cutoff) or not self._fresh(ea_item, cutoff):
            return {
                "status": "STALE",
                "reason_codes": ["UNEMPLOYMENT_CURRENT_OBSERVATION_STALE"],
                "reference_month": f"{period[0]:04d}-{period[1]:02d}",
                "provenance": {
                    "us": self._evidence(us_item),
                    "euro_area": self._evidence(ea_item),
                },
            }
        gap = us_item["value"] - ea_item["value"]
        return {
            "status": "AVAILABLE",
            "reason_codes": [],
            "reference_month": f"{period[0]:04d}-{period[1]:02d}",
            "us_unemployment_percent": format(us_item["value"], "f"),
            "euro_area_unemployment_percent": format(ea_item["value"], "f"),
            "us_minus_euro_area_unemployment_pp": format(gap, "f"),
            "provenance": {
                "us": self._evidence(us_item),
                "euro_area": self._evidence(ea_item),
            },
        }

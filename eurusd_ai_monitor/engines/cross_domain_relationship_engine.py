from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, sqrt
from typing import Any, Mapping

ALGORITHM_VERSION = "cross-domain-relationships-v1"
_PRICE_UNITS = {"usd_per_eur", "usd_per_barrel", "usd_per_troy_ounce", "usd_per_ounce", "index_points", "index_1982_84_100", "index_2015_100"}
_YIELD_UNITS = {"percent_per_annum"}
_PERCENT_POINT_UNITS = {"percent_of_labor_force", "percent_of_open_interest"}


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _scalar(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list, tuple)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mx, my = sum(left) / len(left), sum(right) / len(right)
    dx, dy = [x - mx for x in left], [y - my for y in right]
    vx, vy = sum(x*x for x in dx), sum(y*y for y in dy)
    if vx <= 0 or vy <= 0:
        return None
    value = sum(x*y for x, y in zip(dx, dy)) / sqrt(vx * vy)
    return max(-1.0, min(1.0, value))


class CrossDomainRelationshipEngine:
    """Strict point-in-time descriptive relationships across distinct evidence domains.

    Only exact common timestamps are aligned. No forward-fill, interpolation,
    causal attribution, forecasting, directional voting, or trade authority.
    """

    def __init__(self, *, minimum_aligned_changes: int = 20, lookback_changes: int = 250) -> None:
        for name, value in (("minimum_aligned_changes", minimum_aligned_changes), ("lookback_changes", lookback_changes)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                raise ValueError(f"{name} must be an integer >= 2")
        if minimum_aligned_changes > lookback_changes:
            raise ValueError("minimum_aligned_changes cannot exceed lookback_changes")
        self.minimum = minimum_aligned_changes
        self.lookback = lookback_changes

    def assess(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise TypeError("snapshot must be a mapping")
        if snapshot.get("read_mode") != "STRICT_SYSTEM_KNOWLEDGE":
            raise ValueError("cross-domain relationships require STRICT_SYSTEM_KNOWLEDGE")
        cutoff = _time(snapshot.get("as_of_utc"), "as_of_utc")
        if not isinstance(snapshot.get("snapshot_sha256"), str) or len(snapshot["snapshot_sha256"]) != 64:
            raise ValueError("a unified snapshot SHA-256 is required")
        domains = snapshot.get("analytics_domains")
        if not isinstance(domains, Mapping):
            raise ValueError("analytics_domains must be a mapping")

        series: list[dict[str, Any]] = []
        excluded: dict[str, str] = {}
        for domain, domain_view in sorted(domains.items()):
            if not isinstance(domain_view, Mapping):
                continue
            for product in domain_view.get("products", ()):
                if not isinstance(product, Mapping):
                    continue
                product_id = product.get("product_id")
                identity = f"{domain}:{product_id}"
                if product.get("status") != "ELIGIBLE":
                    excluded[identity] = "PRODUCT_NOT_QUALITY_ELIGIBLE"
                    continue
                rows = product.get("observations")
                if not isinstance(rows, list):
                    excluded[identity] = "OBSERVATIONS_NOT_A_LIST"
                    continue
                unit = None
                selected: dict[datetime, tuple[float, str]] = {}
                invalid = False
                for row in rows:
                    if not isinstance(row, Mapping):
                        invalid = True; break
                    try:
                        effective = _time(row.get("effective_at_utc"), "effective_at_utc")
                        published = _time(row.get("published_at_utc"), "published_at_utc")
                        retrieved = _time(row.get("retrieved_at_utc"), "retrieved_at_utc")
                    except ValueError:
                        invalid = True; break
                    if effective > cutoff or published > cutoff or retrieved > cutoff or published > retrieved:
                        invalid = True; break
                    if row.get("source_id") != product.get("source_id") or row.get("product_id") != product_id:
                        invalid = True; break
                    row_unit = row.get("unit")
                    value = _scalar(row.get("value"))
                    digest = row.get("payload_sha256")
                    if not isinstance(row_unit, str) or value is None or not isinstance(digest, str) or len(digest) != 64:
                        invalid = True; break
                    if unit is None: unit = row_unit
                    if unit != row_unit:
                        invalid = True; break
                    selected[effective] = (value, digest)
                if invalid:
                    excluded[identity] = "INVALID_OR_NON_PIT_OBSERVATION"
                    continue
                if unit not in _PRICE_UNITS | _YIELD_UNITS | _PERCENT_POINT_UNITS:
                    excluded[identity] = "UNSUPPORTED_MEASURE_UNIT"
                    continue
                ordered = sorted(selected.items())
                changes: dict[datetime, tuple[float, str, str]] = {}
                method = "PERCENT_CHANGE" if unit in _PRICE_UNITS else "CHANGE_BASIS_POINTS" if unit in _YIELD_UNITS else "CHANGE_PERCENTAGE_POINTS"
                for (previous_time, (previous, previous_hash)), (current_time, (current, current_hash)) in zip(ordered, ordered[1:]):
                    if unit in _PRICE_UNITS:
                        if previous <= 0 or current <= 0:
                            continue
                        change = (current / previous - 1.0) * 100.0
                    elif unit in _YIELD_UNITS:
                        change = (current - previous) * 100.0
                    else:
                        change = current - previous
                    if isfinite(change):
                        changes[current_time] = (change, previous_hash, current_hash)
                series.append({"domain": str(domain), "source_id": product["source_id"], "product_id": product_id,
                               "unit": unit, "method": method if ordered else "", "changes": changes})

        relationships = []
        candidates = 0
        for index, left in enumerate(series):
            for right in series[index + 1:]:
                if left["domain"] == right["domain"]:
                    continue
                candidates += 1
                common = sorted(set(left["changes"]) & set(right["changes"]))[-self.lookback:]
                identity = f"{left['domain']}:{left['product_id']}|{right['domain']}:{right['product_id']}"
                if len(common) < self.minimum:
                    relationships.append({"relationship_id": identity, "status": "INSUFFICIENT_DATA",
                        "reason_codes": ["EXACT_COMMON_CHANGE_HISTORY_BELOW_MINIMUM"],
                        "aligned_change_count": len(common), "required_aligned_changes": self.minimum})
                    continue
                x = [left["changes"][at][0] for at in common]
                y = [right["changes"][at][0] for at in common]
                corr = _correlation(x, y)
                if corr is None:
                    relationships.append({"relationship_id": identity, "status": "INSUFFICIENT_DATA",
                        "reason_codes": ["ZERO_VARIANCE_OR_INVALID_ALIGNED_CHANGES"], "aligned_change_count": len(common)})
                    continue
                strength = "STRONG" if abs(corr) >= .7 else "MODERATE" if abs(corr) >= .4 else "WEAK"
                relationships.append({"relationship_id": identity, "status": "AVAILABLE", "reason_codes": [],
                    "left": {"domain": left["domain"], "source_id": left["source_id"], "product_id": left["product_id"], "unit": left["unit"], "change_method": left["method"]},
                    "right": {"domain": right["domain"], "source_id": right["source_id"], "product_id": right["product_id"], "unit": right["unit"], "change_method": right["method"]},
                    "aligned_change_count": len(common), "sample_start_utc": common[0].isoformat(), "sample_end_utc": common[-1].isoformat(),
                    "pearson_correlation": round(corr, 8), "descriptive_strength": strength,
                    "sample_direction": "POSITIVE_ASSOCIATION" if corr > 0 else "NEGATIVE_ASSOCIATION" if corr < 0 else "NO_LINEAR_ASSOCIATION",
                    "evidence_hashes": sorted({h for at in common for h in (left["changes"][at][1], left["changes"][at][2], right["changes"][at][1], right["changes"][at][2])})})

        available = sum(item["status"] == "AVAILABLE" for item in relationships)
        status = "AVAILABLE" if available and available == len(relationships) else "PARTIAL" if available else "INSUFFICIENT_EVIDENCE"
        return {"report_type": "POINT_IN_TIME_CROSS_DOMAIN_RELATIONSHIPS", "algorithm_version": ALGORITHM_VERSION,
            "status": status, "as_of_utc": cutoff.isoformat(), "snapshot_sha256": snapshot["snapshot_sha256"],
            "relationship_count": len(relationships), "available_relationship_count": available,
            "candidate_cross_domain_pair_count": candidates, "relationships": relationships,
            "eligible_series_count": len(series), "excluded_series": excluded,
            "policy": {"strict_system_knowledge_only": True, "exact_timestamp_alignment_only": True,
                "no_forward_fill": True, "no_interpolation": True, "no_lookahead": True,
                "distinct_domains_required": True, "same_domain_pairs_excluded": True,
                "correlation_is_not_causation": True, "no_forecast_or_directional_vote": True},
            "interpretation_limits": ["Pearson correlation is descriptive association, not causality or predictive skill.",
                "Only exact common change timestamps are compared; differing frequencies and calendars reduce coverage.",
                "No forward-fill, interpolation, synthetic observations, or hidden missing-value repair is performed.",
                "Relationships are not independent evidence when products share providers, source construction, or underlying markets.",
                "A relationship is not a EURUSD directional vote, forecast, scenario probability, trade signal, or execution instruction."],
            "decision_authority": "CONTEXT_ONLY", "trade_authority": "NONE", "order_execution": "DISABLED"}

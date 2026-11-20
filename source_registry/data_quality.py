from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


_FRESHNESS_DAYS = {
    "REALTIME": 1,
    "INTRADAY": 1,
    "DAILY": 5,
    "WEEKLY": 21,
    "MONTHLY": 75,
    "QUARTERLY": 120,
    "EVENT_DRIVEN": 180,
    "ON_DEMAND": 180,
}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or isinstance(value, (dict, list, tuple)) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _value_numbers(value: Any) -> list[Decimal] | None:
    if isinstance(value, Mapping):
        if set(value) == {"lower", "upper"}:
            low, high = _number(value["lower"]), _number(value["upper"])
        elif set(value) == {"low", "high"}:
            low, high = _number(value["low"]), _number(value["high"])
        else:
            return None
        if low is None or high is None or low > high:
            return None
        return [low, high]
    scalar = _number(value)
    return [scalar] if scalar is not None else None


def _revision_summary(history: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in history:
        grouped[str(row.get("observation_key", ""))].append(row)
    revised_keys = 0
    revision_count = 0
    max_abs_delta: Decimal | None = None
    for versions in grouped.values():
        versions.sort(key=lambda row: (int(row.get("version", 0)), str(row.get("retrieved_at_utc", ""))))
        if len(versions) <= 1:
            continue
        revised_keys += 1
        revision_count += len(versions) - 1
        for previous, current in zip(versions, versions[1:]):
            old_values, new_values = _value_numbers(previous.get("value")), _value_numbers(current.get("value"))
            if old_values is None or new_values is None or len(old_values) != len(new_values):
                continue
            for old, new in zip(old_values, new_values):
                delta = abs(new - old)
                max_abs_delta = delta if max_abs_delta is None else max(max_abs_delta, delta)
    return {
        "observation_keys_with_revisions": revised_keys,
        "revision_count": revision_count,
        "max_absolute_value_delta": format(max_abs_delta, "f") if max_abs_delta is not None else None,
        "revision_policy": "APPEND_ONLY_LATEST_VERSION_SELECTED_BY_AS_OF_READ",
    }


def assess_product_quality(
    product: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
    *,
    as_of_utc: datetime,
    revision_history: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Evaluate one product's evidence quality without changing source data or PIT rules."""
    if not isinstance(product, Mapping):
        raise TypeError("product must be a registry product mapping")
    if as_of_utc.tzinfo is None or as_of_utc.utcoffset() is None:
        raise ValueError("as_of_utc must be timezone-aware")
    cutoff = as_of_utc.astimezone(timezone.utc)
    rows = list(observations)
    issues: list[dict[str, str]] = []
    blocking = 0
    warnings = 0
    expected_unit = product.get("unit")
    frequency = str(product.get("observation_frequency", "EVENT_DRIVEN")).upper()
    freshness_days = _FRESHNESS_DAYS.get(frequency)
    seen_keys: set[str] = set()
    latest_effective: datetime | None = None

    def issue(code: str, severity: str, detail: str) -> None:
        nonlocal blocking, warnings
        issues.append({"code": code, "severity": severity, "detail": detail})
        if severity == "BLOCKER":
            blocking += 1
        else:
            warnings += 1

    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            issue("INVALID_OBSERVATION_SHAPE", "BLOCKER", f"row {index} is not an object")
            continue
        key = str(row.get("observation_key") or row.get("source_record_id") or row.get("effective_at_utc") or index)
        if key in seen_keys:
            issue("DUPLICATE_OBSERVATION_KEY", "BLOCKER", f"duplicate observation identity: {key}")
        seen_keys.add(key)
        effective = _parse_time(row.get("effective_at_utc"))
        published = _parse_time(row.get("published_at_utc"))
        retrieved = _parse_time(row.get("retrieved_at_utc"))
        if effective is None:
            issue("INVALID_EFFECTIVE_TIMESTAMP", "BLOCKER", f"row {index} effective timestamp missing, invalid or timezone-naive")
        elif effective > cutoff:
            issue("FUTURE_EFFECTIVE_TIMESTAMP", "BLOCKER", f"row {index} effective timestamp exceeds as-of cutoff")
        else:
            latest_effective = effective if latest_effective is None else max(latest_effective, effective)
        if published is None:
            issue("PUBLICATION_TIME_UNVERIFIED", "BLOCKER", f"row {index} has no verified publication timestamp")
        elif published > cutoff:
            issue("FUTURE_PUBLICATION_TIMESTAMP", "BLOCKER", f"row {index} publication timestamp exceeds as-of cutoff")
        if retrieved is None:
            issue("INVALID_RETRIEVAL_TIMESTAMP", "BLOCKER", f"row {index} retrieval timestamp missing or invalid")
        elif retrieved > cutoff:
            issue("FUTURE_RETRIEVAL_TIMESTAMP", "BLOCKER", f"row {index} retrieval timestamp exceeds as-of cutoff")
        if published is not None and retrieved is not None and retrieved < published:
            issue("RETRIEVED_BEFORE_PUBLICATION", "BLOCKER", f"row {index} retrieval precedes publication")
        if row.get("unit") != expected_unit:
            issue("UNIT_MISMATCH", "BLOCKER", f"row {index} unit {row.get('unit')!r} does not match registry unit {expected_unit!r}")
        if _value_numbers(row.get("value")) is None:
            issue("NONFINITE_OR_INVALID_VALUE", "BLOCKER", f"row {index} value is not a finite scalar or valid low/high range")

    age_days = None
    freshness = "UNKNOWN"
    if latest_effective is not None:
        age_days = max(0.0, (cutoff - latest_effective).total_seconds() / 86400.0)
        if freshness_days is not None:
            freshness = "FRESH" if age_days <= freshness_days else "STALE"
            if freshness == "STALE":
                issue("STALE_PRODUCT", "WARNING", f"latest effective observation is {age_days:.1f} days old; threshold is {freshness_days} days")
    if not rows:
        issue("NO_OBSERVATIONS", "BLOCKER", "no point-in-time eligible observations were supplied")

    score = max(0, 100 - blocking * 25 - warnings * 10)
    if blocking:
        status = "BLOCKED"
    elif freshness == "STALE":
        status = "STALE"
    elif freshness == "FRESH":
        status = "PASS"
    else:
        status = "UNASSESSED"
    return {
        "source_id": rows[0].get("source_id") if rows and isinstance(rows[0], Mapping) else None,
        "product_id": product.get("product_id"),
        "as_of_utc": cutoff.isoformat().replace("+00:00", "Z"),
        "status": status,
        "quality_score": score,
        "observation_count": len(rows),
        "latest_effective_at_utc": latest_effective.isoformat().replace("+00:00", "Z") if latest_effective else None,
        "freshness_age_days": round(age_days, 3) if age_days is not None else None,
        "freshness_threshold_days": freshness_days,
        "freshness": freshness,
        "blocking_issue_count": blocking,
        "warning_count": warnings,
        "issues": issues,
        "revision_history": _revision_summary(revision_history),
        "eligible_for_downstream_analytics": blocking == 0 and freshness == "FRESH",
        "policy": {
            "no_values_corrected_or_imputed": True,
            "unknown_publication_time_blocks_eligibility": True,
            "future_or_lookahead_evidence_blocks_eligibility": True,
            "revision_history_is_append_only": True,
            "thresholds_are_frequency_defaults_not_economic_truth_bounds": True,
        },
    }


def assess_registry_quality(
    registry: Mapping[str, Any],
    observation_rows: Mapping[tuple[str, str], Iterable[Mapping[str, Any]]],
    *,
    as_of_utc: datetime,
    revision_rows: Mapping[tuple[str, str], Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Produce a deterministic quality report for explicitly supplied PIT rows."""
    revision_rows = revision_rows or {}
    results = []
    for source in registry.get("sources", []):
        if source.get("enabled") is not True:
            continue
        for product in source.get("products", []):
            pair = (source["source_id"], product["product_id"])
            result = assess_product_quality(
                product, observation_rows.get(pair, ()), as_of_utc=as_of_utc,
                revision_history=revision_rows.get(pair, ()),
            )
            result["source_id"] = source["source_id"]
            results.append(result)
    results.sort(key=lambda item: (item["source_id"], item["product_id"]))
    counts = {name: sum(item["status"] == name for item in results) for name in ("PASS", "STALE", "BLOCKED", "UNASSESSED")}
    return {
        "report_type": "MULTI_DOMAIN_DATA_QUALITY_AND_REVISION_REPORT",
        "version": "1.0.0",
        "as_of_utc": as_of_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "product_count": len(results),
        "status_counts": counts,
        "eligible_product_count": sum(item["eligible_for_downstream_analytics"] for item in results),
        "products": results,
        "policy": {
            "read_only_assessment": True,
            "no_network_requests": True,
            "no_database_mutation": True,
            "no_automatic_repair_or_imputation": True,
            "no_point_in_time_filter_bypass": True,
            "quality_gate_not_yet_wired_into_fusion": True,
        },
    }

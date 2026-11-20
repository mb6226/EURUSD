from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping


# These are acquisition constraints, not claims that data is already available.
# A source is never fetched merely because it appears in this table.
_SOURCE_POLICIES: dict[str, dict[str, str]] = {
    "FED_FOMC_POLICY": {
        "mode": "OFFICIAL_HTML_SNAPSHOT",
        "pit_readiness": "RELEASE_TIMESTAMP_REQUIRED",
        "publication_evidence": "Capture the timestamp of the original FOMC statement/release; effective date alone is insufficient.",
        "historical_limit": "The historical target-range table is not, by itself, an intraday publication-time archive.",
    },
    "ECB_POLICY_RATES": {
        "mode": "OFFICIAL_RELEASE_SNAPSHOT",
        "pit_readiness": "RELEASE_TIMESTAMP_REQUIRED",
        "publication_evidence": "Join each effective rate to its original ECB monetary-policy decision release timestamp.",
        "historical_limit": "The current key-rates page's effective dates must not be treated as publication timestamps.",
    },
    "US_BLS_MACRO": {
        "mode": "OFFICIAL_API_PLUS_RELEASE_CALENDAR",
        "pit_readiness": "RELEASE_CALENDAR_JOIN_REQUIRED",
        "publication_evidence": "Join each reference month to the matching original BLS release calendar/press release timestamp; preserve the release document.",
        "historical_limit": "Current API values alone do not prove the value known at an earlier release; preserve original release snapshots to capture revisions.",
    },
    "EUROSTAT_MACRO": {
        "mode": "OFFICIAL_API_SNAPSHOT",
        "pit_readiness": "FORWARD_SNAPSHOTS_ONLY",
        "publication_evidence": "Capture each response with retrieval timestamp and official dataset update metadata; do not backdate current values.",
        "historical_limit": "The API exposes the latest dataset version, not a historical vintage archive; historical point-in-time values cannot be reconstructed from today's response.",
    },
    "FRED_INTERMARKET": {
        "mode": "FRED_ALFRED_VINTAGE_PROVIDER",
        "pit_readiness": "DATE_GRAIN_VINTAGES_ONLY_NO_INTRADAY_PIT",
        "publication_evidence": "Use ALFRED output_type=2 with realtime_start/realtime_end, preserve every raw response, and retain the vintage interval for each value. API key must be explicitly supplied by the operator.",
        "historical_limit": "Daily 2Y/10Y nominal yields, 10Y real yield, broad trade-weighted USD (not ICE DXY), S&P 500, VIX, WTI, Brent, and H.10 USD-per-EUR reference series are date-grain vintage products. They do not establish intraday public release times or executable quotes; strict PIT promotion remains blocked until timestamp evidence is independently verified. Gold/ICE DXY licensing and source access require separate review.",
    },
    "ECB_INTERMARKET": {
        "mode": "ECB_SDMX_INCLUDE_HISTORY_PROVIDER",
        "pit_readiness": "REVISION_HISTORY_CAPTURED_RELEASE_TIME_UNVERIFIED",
        "publication_evidence": "Supply an exact metadata-verified SDMX flow/key; request includeHistory=true and preserve the raw CSV and row attributes.",
        "historical_limit": "ECB observation periods and SDMX revision history do not, by themselves, establish exact intraday public release timestamps; no PIT promotion is performed.",
    },
    "LBMA_INTERMARKET": {
        "mode": "LICENSED_SOURCE_REVIEW",
        "pit_readiness": "LICENSE_REVIEW_REQUIRED",
        "publication_evidence": "Confirm redistribution/API permissions and source timestamp semantics before acquisition.",
        "historical_limit": "No automated request or ingestion until licensing and access conditions are verified.",
    },
    "BROKER_SPOT_REFERENCE": {
        "mode": "LOCAL_BROKER_EXPORT",
        "pit_readiness": "BROKER_TIMEZONE_AND_ARCHIVE_REQUIRED",
        "publication_evidence": "Preserve broker/server timestamp, timezone/DST interpretation, symbol, timeframe, bid/ask basis, and export hash.",
        "historical_limit": "Current rolling M1/M5 exports are not a long-term archive and must not be represented as one.",
    },
    "CFTC_TFF_POSITIONING": {
        "mode": "OFFICIAL_CFTC_API_PLUS_RELEASE_CALENDAR",
        "pit_readiness": "REPORT_AND_PUBLICATION_TIME_JOIN_REQUIRED",
        "publication_evidence": "Use report date plus the actual official release date/time (including holiday delays); archive the release schedule and payload.",
        "historical_limit": "Report Tuesday is not publication time. Monitor the announced 2026 COT cadence transition before assuming a weekly Friday schedule.",
    },
}


def _domain(source: Mapping[str, Any]) -> str:
    category = source.get("category")
    topics = {str(item).casefold() for item in source.get("topics", [])}
    if category == "MONETARY_POLICY":
        return "monetary_policy"
    if category == "ECONOMIC_DATA":
        return "macro_fundamentals"
    if category == "FX_MARKET":
        return "spot_fx"
    if category == "FINANCIAL_MARKETS" and (
        "cot" in topics or "futures_positioning" in topics
    ):
        return "positioning_sentiment"
    if category == "FINANCIAL_MARKETS":
        return "intermarket"
    return str(category or "unclassified").casefold()


def build_acquisition_plan_from_paths(
    registry_path: str | None = None,
    schema_dir: str | None = None,
) -> dict[str, Any]:
    """Load the canonical validated registry and produce its no-network plan."""
    from .registry_loader import DEFAULT_REGISTRY_PATH, DEFAULT_SCHEMA_DIR, load_registry

    registry = load_registry(
        registry_path=registry_path or DEFAULT_REGISTRY_PATH,
        schema_dir=schema_dir or DEFAULT_SCHEMA_DIR,
    )
    return build_acquisition_plan(registry)


def build_acquisition_plan(registry: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic, no-network acquisition/readiness plan.

    This function deliberately does not initialize databases, inspect secrets,
    make HTTP requests, change registry flags, or schedule background work.
    """
    if not isinstance(registry, Mapping) or not isinstance(registry.get("sources"), list):
        raise TypeError("registry must be a validated registry mapping")

    domains: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in registry["sources"]:
        if not isinstance(source, Mapping):
            raise ValueError("registry sources must be objects")
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id must be non-empty")
        policy = _SOURCE_POLICIES.get(source_id)
        if policy is None:
            policy = {
                "mode": "UNMAPPED",
                "pit_readiness": "BLOCKED_UNMAPPED_SOURCE",
                "publication_evidence": "Define and review a source-specific publication-time contract.",
                "historical_limit": "No acquisition until an explicit source policy exists.",
            }
        products = source.get("products")
        if not isinstance(products, list):
            raise ValueError(f"{source_id} products must be a list")
        enabled = source.get("enabled") is True
        products_out = []
        for product in products:
            if not isinstance(product, Mapping):
                raise ValueError(f"{source_id} products must contain objects")
            products_out.append({
                "product_id": product.get("product_id"),
                "measure": product.get("measure"),
                "unit": product.get("unit"),
                "frequency": product.get("observation_frequency"),
                "enabled": enabled,
                "auto_fetch": source.get("auto_fetch") is True,
                "pit_readiness": policy["pit_readiness"],
            })
        domains[_domain(source)].append({
            "source_id": source_id,
            "source_name": source.get("name", source_id),
            "publisher": (source.get("publisher") or {}).get("name"),
            "authority_tier": (source.get("publisher") or {}).get("authority_tier"),
            "enabled": enabled,
            "auto_fetch": source.get("auto_fetch") is True,
            "mode": policy["mode"],
            "pit_readiness": policy["pit_readiness"],
            "publication_evidence": policy["publication_evidence"],
            "historical_limit": policy["historical_limit"],
            "products": sorted(products_out, key=lambda item: str(item["product_id"])),
        })

    source_rows = [
        source
        for domain_sources in domains.values()
        for source in domain_sources
    ]
    readiness_counts: dict[str, int] = defaultdict(int)
    for source in source_rows:
        readiness_counts[source["pit_readiness"]] += len(source["products"])

    return {
        "report_type": "CONTROLLED_MULTI_DOMAIN_ACQUISITION_PLAN",
        "version": "1.0.0",
        "network_requests_made": 0,
        "databases_created_or_mutated": False,
        "registry_mutated": False,
        "automatic_fetch_enabled": False,
        "registered_source_count": len(source_rows),
        "registered_product_count": sum(len(source["products"]) for source in source_rows),
        "enabled_product_count": sum(
            len(source["products"]) for source in source_rows if source["enabled"]
        ),
        "readiness_counts_by_product": dict(sorted(readiness_counts.items())),
        "domains": {
            domain: sorted(sources, key=lambda item: item["source_id"])
            for domain, sources in sorted(domains.items())
        },
        "policy": {
            "raw_payload_archive_before_normalization": True,
            "publication_time_must_be_source_evidenced": True,
            "retrieval_time_stamped_locally_after_response": True,
            "revisions_are_append_only": True,
            "unknown_publication_time_is_not_backfilled": True,
            "licensed_or_credentialed_sources_require_access_review": True,
            "no_auto_fetch": True,
        },
    }

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping


_REQUIRED_DOMAINS = {
    "spot_fx": "Broker spot FX bars/quotes and verified bid/ask basis",
    "monetary_policy": "Fed and ECB policy decisions with original release timestamps",
    "macro_fundamentals": "US and euro-area inflation/employment with release vintages",
    "rates_and_yields": "US nominal/real yields and euro sovereign yields",
    "usd_and_fx_benchmarks": "Broad USD benchmark and EURUSD reference rates (not ICE DXY or executable spot)",
    "equities_and_volatility": "Equity index and volatility reference series",
    "energy": "WTI and Brent crude oil reference series",
    "precious_metals": "Gold reference price with verified licensing and release semantics",
    "positioning_sentiment": "CFTC futures positioning with actual publication timestamps",
    "news_and_geopolitics": "Timestamped news/event evidence with source lineage",
    "options_and_cross_currency": "FX options risk reversals, implied volatility and cross-currency basis",
}

_PRODUCT_DOMAIN = {
    "US_2Y_TREASURY_YIELD": "rates_and_yields",
    "US_10Y_TREASURY_YIELD": "rates_and_yields",
    "US_10Y_REAL_TREASURY_YIELD": "rates_and_yields",
    "DE_10Y_GOVERNMENT_YIELD": "rates_and_yields",
    "USD_BROAD_TRADE_WEIGHTED_INDEX": "usd_and_fx_benchmarks",
    "EURUSD_DAILY_REFERENCE_RATE": "usd_and_fx_benchmarks",
    "SP500_INDEX": "equities_and_volatility",
    "US_VIX_CLOSE": "equities_and_volatility",
    "WTI_CRUDE_OIL_PRICE": "energy",
    "BRENT_CRUDE_OIL_PRICE": "energy",
    "GOLD_USD_TROY_OUNCE": "precious_metals",
    "EURUSD_SPOT_REFERENCE": "spot_fx",
    "EURO_FX_DEALER_NET_OI_PCT": "positioning_sentiment",
    "EURO_FX_ASSET_MANAGER_NET_OI_PCT": "positioning_sentiment",
    "EURO_FX_LEVERAGED_MONEY_NET_OI_PCT": "positioning_sentiment",
}


def build_multi_domain_coverage_report(registry: Mapping[str, Any]) -> dict[str, Any]:
    """Describe registered product coverage without implying live availability."""
    if not isinstance(registry, Mapping) or not isinstance(registry.get("sources"), list):
        raise TypeError("registry must be a validated registry mapping")
    domains: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unmapped: list[dict[str, str]] = []
    for source in registry["sources"]:
        if not isinstance(source, Mapping):
            raise ValueError("registry sources must be objects")
        source_id = source.get("source_id")
        for product in source.get("products", []):
            product_id = product.get("product_id")
            domain = _PRODUCT_DOMAIN.get(product_id)
            if domain is None:
                # Broad source families still count for their documented top-level domain.
                category = source.get("category")
                topics = {str(t).casefold() for t in source.get("topics", [])}
                if category == "MONETARY_POLICY":
                    domain = "monetary_policy"
                elif category == "ECONOMIC_DATA":
                    domain = "macro_fundamentals"
                elif "futures_positioning" in topics:
                    domain = "positioning_sentiment"
                elif category == "FX_MARKET":
                    domain = "spot_fx"
                else:
                    unmapped.append({"source_id": str(source_id), "product_id": str(product_id)})
                    continue
            domains[domain].append({
                "source_id": source_id,
                "product_id": product_id,
                "enabled": source.get("enabled") is True,
                "auto_fetch": source.get("auto_fetch") is True,
                "authority_tier": (source.get("publisher") or {}).get("authority_tier"),
                "frequency": product.get("observation_frequency"),
                "unit": product.get("unit"),
            })
    output = {}
    for domain, description in _REQUIRED_DOMAINS.items():
        products = sorted(domains.get(domain, []), key=lambda x: (x["source_id"], x["product_id"]))
        output[domain] = {
            "description": description,
            "registry_status": "REGISTERED" if products else "NOT_COVERED",
            "registered_product_count": len(products),
            "enabled_product_count": sum(p["enabled"] for p in products),
            "automatic_fetch_enabled": any(p["auto_fetch"] for p in products),
            "products": products,
        }
    registered_domains = sum(x["registered_product_count"] > 0 for x in output.values())
    return {
        "report_type": "EURUSD_MULTI_DOMAIN_COVERAGE_ASSESSMENT",
        "version": "1.0.0",
        "registered_source_count": len(registry["sources"]),
        "registered_product_count": sum(len(s.get("products", [])) for s in registry["sources"]),
        "required_domain_count": len(_REQUIRED_DOMAINS),
        "registered_domain_count": registered_domains,
        "domain_coverage_ratio": registered_domains / len(_REQUIRED_DOMAINS),
        "live_data_availability": "NOT_ASSESSED_BY_REGISTRY_ONLY_REPORT",
        "strict_pit_readiness": "MIXED; SEE SOURCE-SPECIFIC ACQUISITION PLAN",
        "unmapped_products": sorted(unmapped, key=lambda x: (x["source_id"], x["product_id"])),
        "domains": output,
        "known_gaps": [
            "ICE US Dollar Index (DXY): not substituted with the broader FRED trade-weighted USD index; licensing/source access review required.",
            "Gold spot/reference price: LBMA licensing and publication-time semantics not verified; no acquisition.",
            "FX options risk reversals/implied volatility and cross-currency basis: no licensed source/provider configured.",
            "Intraday intermarket quotes and historical bid/ask ticks: daily reference series are not a substitute.",
            "News/geopolitical evidence: no production source/provider is registered in this registry snapshot.",
            "A registered product is not evidence that observations are present, current, complete, or PIT-eligible.",
        ],
        "policy": {
            "registry_mutated_by_report": False,
            "network_requests_made": 0,
            "databases_created_or_mutated": False,
            "auto_fetch_enabled": False,
            "unverified_sources_not_promoted": True,
        },
    }

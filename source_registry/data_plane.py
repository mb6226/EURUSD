from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .observation_store import (
    DEFAULT_OBSERVATION_DB,
    PointInTimeObservationStore,
)
from .registry_loader import DEFAULT_REGISTRY_PATH, DEFAULT_SCHEMA_DIR, load_registry


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("as_of_utc must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of_utc must be timezone-aware")
    return value.astimezone(timezone.utc)


def _domain_for(source: Mapping[str, Any]) -> str:
    category = source.get("category")
    topics = {str(item).lower() for item in source.get("topics", [])}
    if category == "MONETARY_POLICY":
        return "monetary_policy"
    if category == "ECONOMIC_DATA":
        return "macro_fundamentals"
    if category == "FINANCIAL_MARKETS" and (
        "cot" in topics or "futures_positioning" in topics
    ):
        return "positioning_sentiment"
    if category == "FINANCIAL_MARKETS":
        return "intermarket"
    if category == "FX_MARKET":
        return "spot_fx"
    return str(category or "UNCLASSIFIED").lower()


class PointInTimeDataPlane:
    """Registry-driven, read-only multi-domain view over canonical PIT observations.

    This class never fetches data, creates an observation database, or changes
    registry/source state. Ingestion remains an explicit caller action.
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        *,
        registry: Mapping[str, Any],
        observation_store: PointInTimeObservationStore | None,
        market_data_store: Any | None = None,
    ) -> None:
        if not isinstance(registry, Mapping) or not isinstance(registry.get("sources"), list):
            raise TypeError("registry must be a validated registry document")
        if observation_store is not None:
            if not isinstance(observation_store, PointInTimeObservationStore):
                raise TypeError("observation_store must be a PointInTimeObservationStore")
            if not getattr(observation_store, "_read_only", False):
                raise ValueError("observation_store must be opened read-only")

        self._store = observation_store
        if market_data_store is not None and not getattr(market_data_store, "_read_only", False):
            raise ValueError("market_data_store must be opened read-only")
        self._market_store = market_data_store
        self._registry = deepcopy(dict(registry))
        self._products: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        seen_products: set[tuple[str, str]] = set()
        for source in registry["sources"]:
            if not isinstance(source, Mapping):
                raise ValueError("registry sources must be objects")
            source_id = source.get("source_id")
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("registry source_id must be non-empty")
            if source_id in seen_sources:
                raise ValueError(f"duplicate source_id: {source_id}")
            seen_sources.add(source_id)
            products = source.get("products")
            if not isinstance(products, list):
                raise ValueError(f"source {source_id} products must be a list")
            for product in products:
                if not isinstance(product, Mapping):
                    raise ValueError("registry products must be objects")
                product_id = product.get("product_id")
                if not isinstance(product_id, str) or not product_id.strip():
                    raise ValueError("registry product_id must be non-empty")
                identity = (source_id, product_id)
                if identity in seen_products:
                    raise ValueError(f"duplicate source/product: {identity!r}")
                seen_products.add(identity)
                self._products.append({
                    "domain": _domain_for(source),
                    "source_id": source_id,
                    "source_name": source.get("name", source_id),
                    "category": source.get("category"),
                    "enabled": source.get("enabled") is True,
                    "auto_fetch": source.get("auto_fetch") is True,
                    "product_id": product_id,
                    "measure": product.get("measure"),
                    "unit": product.get("unit"),
                    "frequency": product.get("observation_frequency"),
                    "authority_tier": (source.get("publisher") or {}).get("authority_tier"),
                })

    @classmethod
    def from_paths(
        cls,
        *,
        registry_path: str | Path = DEFAULT_REGISTRY_PATH,
        schema_dir: str | Path = DEFAULT_SCHEMA_DIR,
        observation_db_path: str | Path = DEFAULT_OBSERVATION_DB,
        market_db_path: str | Path | None = None,
    ) -> "PointInTimeDataPlane":
        """Load the validated registry and open an existing PIT DB without creating it."""
        registry = load_registry(registry_path=registry_path, schema_dir=schema_dir)
        db_path = Path(observation_db_path)
        store = (
            PointInTimeObservationStore.open_read_only(db_path)
            if db_path.is_file()
            else None
        )
        from eurusd_ai_monitor.storage.market_data_store import (
            DEFAULT_MARKET_DATA_DB_PATH, MarketDataStore,
        )
        market_path = Path(market_db_path or DEFAULT_MARKET_DATA_DB_PATH)
        market_store = (
            MarketDataStore.open_read_only(market_path)
            if market_path.is_file()
            else None
        )
        return cls(
            registry=registry, observation_store=store,
            market_data_store=market_store,
        )

    def build_observation_requests(self) -> dict[str, tuple[tuple[str, str], ...]]:
        """Return enabled registry products grouped for one batched as-of read."""
        grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for product in self._products:
            if product["enabled"]:
                grouped[product["domain"]].append(
                    (product["source_id"], product["product_id"])
                )
        return {
            domain: tuple(sorted(pairs))
            for domain, pairs in sorted(grouped.items())
        }

    def read_as_of(self, as_of_utc: datetime) -> dict[str, Any]:
        """Read all enabled products at one cutoff and report explicit coverage gaps."""
        cutoff = _as_utc(as_of_utc)
        enabled = [item for item in self._products if item["enabled"]]
        disabled_count = len(self._products) - len(enabled)
        if self._store is None:
            rows_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
            store_status = "NOT_CONFIGURED"
        else:
            requests = [
                (item["source_id"], item["product_id"])
                for item in enabled
            ]
            rows_by_pair = self._store.get_many_as_of(requests, cutoff)
            store_status = "AVAILABLE"

        domains: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in enabled:
            pair = (item["source_id"], item["product_id"])
            observations = rows_by_pair.get(pair, [])
            product_status = (
                "UNAVAILABLE" if self._store is None
                else "AVAILABLE" if observations
                else "MISSING"
            )
            domains[item["domain"]].append({
                **item,
                "status": product_status,
                "observation_count": len(observations),
                "first_effective_at_utc": (
                    observations[0]["effective_at_utc"] if observations else None
                ),
                "last_effective_at_utc": (
                    observations[-1]["effective_at_utc"] if observations else None
                ),
                "observations": observations,
            })

        domain_results = {}
        total_observations = 0
        available_products = 0
        for domain, products in sorted(domains.items()):
            count = sum(item["observation_count"] for item in products)
            available = sum(item["status"] == "AVAILABLE" for item in products)
            total_observations += count
            available_products += available
            if self._store is None:
                status = "UNAVAILABLE"
            elif available == len(products):
                status = "AVAILABLE"
            elif available:
                status = "PARTIAL"
            else:
                status = "MISSING"
            domain_results[domain] = {
                "status": status,
                "registered_enabled_products": len(products),
                "available_products": available,
                "observation_count": count,
                "products": sorted(
                    products, key=lambda item: (item["source_id"], item["product_id"])
                ),
            }

        registered_count = len(enabled)
        if self._store is None:
            overall = "UNAVAILABLE"
        elif available_products == registered_count and registered_count:
            overall = "AVAILABLE"
        elif available_products:
            overall = "PARTIAL"
        else:
            overall = "MISSING"

        return {
            "report_type": "MULTI_DOMAIN_POINT_IN_TIME_DATA_PLANE",
            "version": self.VERSION,
            "status": overall,
            "as_of_utc": cutoff.isoformat(),
            "store_status": store_status,
            "registered_source_count": len({item["source_id"] for item in self._products}),
            "enabled_product_count": registered_count,
            "disabled_product_count": disabled_count,
            "available_product_count": available_products,
            "coverage_ratio": (
                available_products / registered_count if registered_count else 0.0
            ),
            "observation_count": total_observations,
            "domains": domain_results,
            "observation_requests": {
                domain: [list(pair) for pair in pairs]
                for domain, pairs in self.build_observation_requests().items()
            },
            "policy": {
                "read_mode": "READ_ONLY_POINT_IN_TIME",
                "required_timestamps": [
                    "effective_at_utc", "published_at_utc", "retrieved_at_utc"
                ],
                "unknown_publication_excluded": True,
                "disabled_sources_excluded": True,
                "automatic_fetch": False,
                "source_registry_mutated": False,
                "observation_store_mutated": False,
            },
        }

    def read_unified_as_of(self, as_of_utc: datetime) -> dict[str, Any]:
        """Build one strict system-knowledge snapshot and a separate quality-gated analytics view.

        Raw eligible evidence is retained unchanged in ``evidence_domains``. Only
        observations whose product passes the Phase 37G quality checks are exposed
        through ``analytics_domains``. This is read-only and never fetches data.
        """
        from .data_quality import assess_registry_quality

        cutoff = _as_utc(as_of_utc)
        base = self.read_as_of(cutoff)
        observations_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
        revisions_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
        if self._store is not None:
            for domain_data in base["domains"].values():
                for product_view in domain_data["products"]:
                    pair = (product_view["source_id"], product_view["product_id"])
                    observations_by_pair[pair] = product_view["observations"]
            pairs = sorted(observations_by_pair)
            revisions_by_pair = self._store.get_many_revision_history(
                pairs, as_of_utc=cutoff
            )

        quality = assess_registry_quality(
            self._registry, observations_by_pair, as_of_utc=cutoff,
            revision_rows=revisions_by_pair,
        )
        quality_by_pair = {
            (item["source_id"], item["product_id"]): item
            for item in quality["products"]
        }
        evidence_domains = base["domains"]
        analytics_domains: dict[str, dict[str, Any]] = {}
        for domain, domain_data in evidence_domains.items():
            products = []
            eligible_count = 0
            for product in domain_data["products"]:
                pair = (product["source_id"], product["product_id"])
                assessment = quality_by_pair.get(pair, {
                    "status": "BLOCKED", "quality_score": 0,
                    "eligible_for_downstream_analytics": False,
                    "issues": [{"code": "QUALITY_ASSESSMENT_MISSING", "severity": "BLOCKER"}],
                })
                eligible = assessment["eligible_for_downstream_analytics"]
                eligible_observations = product["observations"] if eligible else []
                eligible_count += int(eligible)
                products.append({
                    "source_id": product["source_id"],
                    "product_id": product["product_id"],
                    "status": "ELIGIBLE" if eligible else "QUARANTINED",
                    "quality_status": assessment["status"],
                    "quality_score": assessment["quality_score"],
                    "eligible_observation_count": len(eligible_observations),
                    "observations": eligible_observations,
                })
            analytics_domains[domain] = {
                "status": "ELIGIBLE" if eligible_count == len(products) and products else "PARTIAL" if eligible_count else "BLOCKED",
                "registered_enabled_products": len(products),
                "eligible_products": eligible_count,
                "observation_count": sum(p["eligible_observation_count"] for p in products),
                "products": products,
            }

        spot_market_archive: dict[str, Any]
        spot_streams: list[dict[str, Any]] = []
        if self._market_store is None:
            spot_market_archive = {
                "status": "UNAVAILABLE", "reason": "MARKET_ARCHIVE_NOT_CONFIGURED",
                "legacy_candle_count": 0, "versioned_candle_count": 0,
                "streams": [], "eligible_for_analytics": False,
            }
        else:
            market_metadata = self._market_store.get_history_metadata()
            if not market_metadata["version_ledger_available"]:
                spot_market_archive = {
                    "status": "PROVENANCE_UNAVAILABLE",
                    "reason": "CANDLE_VERSION_LEDGER_UNAVAILABLE",
                    "schema_version": market_metadata["schema_version"],
                    "legacy_candle_count": market_metadata["legacy_candle_count"],
                    "versioned_candle_count": 0,
                    "streams": market_metadata["streams"],
                    "eligible_for_analytics": False,
                    "policy": "LEGACY_CANDLES_NOT_PROMOTED_WITHOUT_POINT_IN_TIME_PROVENANCE",
                }
            else:
                stream_results = []
                for stream in market_metadata["streams"]:
                    rows = self._market_store.get_candle_versions_as_of(
                        stream["broker_server"], stream["symbol"],
                        stream["timeframe"], cutoff,
                    )
                    issues: list[str] = []
                    for row in rows:
                        provenance = row.get("provenance", {})
                        price_basis = (provenance.get("price_basis") or {}).get("price_basis")
                        if row.get("source_id") not in {"MT5_COPY_RATES", "MT5_COPY_RATES_RANGE"}:
                            issues.append("SOURCE_ID_UNVERIFIED")
                        if price_basis not in {"BID", "LAST"}:
                            issues.append("PRICE_BASIS_UNVERIFIED")
                        if provenance.get("bar_time_basis") != "UTC":
                            issues.append("BAR_TIME_BASIS_UNVERIFIED")
                        values = row.get("values", {})
                        try:
                            open_value, high_value = Decimal(str(values["open"])), Decimal(str(values["high"]))
                            low_value, close_value = Decimal(str(values["low"])), Decimal(str(values["close"]))
                            if not all(v.is_finite() for v in (open_value, high_value, low_value, close_value)):
                                raise ValueError
                            if high_value < max(open_value, low_value, close_value) or low_value > min(open_value, high_value, close_value):
                                raise ValueError
                        except (KeyError, ValueError, InvalidOperation):
                            issues.append("INVALID_OHLC_VALUES")
                    latest_close = rows[-1]["candle_close_time_utc"] if rows else None
                    age_days = None
                    if latest_close:
                        latest_dt = datetime.fromisoformat(latest_close.replace("Z", "+00:00"))
                        age_days = max(0.0, (cutoff - latest_dt).total_seconds() / 86400.0)
                    if not rows:
                        status = "MISSING"
                    elif issues:
                        status = "BLOCKED"
                    elif age_days is not None and age_days > 1:
                        status = "STALE"
                    else:
                        status = "PASS"
                    result = {
                        **stream, "status": status,
                        "observation_count": len(rows),
                        "latest_candle_close_time_utc": latest_close,
                        "freshness_age_days": round(age_days, 3) if age_days is not None else None,
                        "price_basis": ((rows[-1].get("provenance", {}).get("price_basis") or {}).get("price_basis") if rows else None),
                        "issues": sorted(set(issues)),
                        "evidence_candles": rows,
                        "candles": rows if status == "PASS" else [],
                        "eligible_for_analytics": status == "PASS",
                    }
                    stream_results.append(result)
                eligible_streams = [item for item in stream_results if item["eligible_for_analytics"]]
                spot_streams = eligible_streams
                if eligible_streams and len(eligible_streams) == len(stream_results):
                    spot_status = "AVAILABLE"
                elif eligible_streams:
                    spot_status = "PARTIAL"
                elif any(item["status"] in {"BLOCKED", "STALE"} for item in stream_results):
                    spot_status = "BLOCKED"
                else:
                    spot_status = "MISSING"
                spot_market_archive = {
                    "status": spot_status,
                    "schema_version": market_metadata["schema_version"],
                    "legacy_candle_count": market_metadata["legacy_candle_count"],
                    "versioned_candle_count": market_metadata["versioned_candle_count"],
                    "streams": stream_results,
                    "eligible_for_analytics": bool(eligible_streams),
                    "policy": "CLOSED_BARS_ONLY_WITH_STRICT_OBSERVED_AND_AS_OF_CUTOFFS",
                }
        if "spot_fx" in analytics_domains:
            analytics_domains["spot_fx"]["market_archive_status"] = spot_market_archive["status"]
            analytics_domains["spot_fx"]["market_streams"] = spot_streams
            if spot_streams:
                analytics_domains["spot_fx"]["status"] = "ELIGIBLE" if spot_market_archive["status"] == "AVAILABLE" else "PARTIAL"

        registry_sha256 = hashlib.sha256(
            json.dumps(self._registry, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        identity = {
            "as_of_utc": base["as_of_utc"],
            "registry_sha256": registry_sha256,
            "read_mode": "STRICT_SYSTEM_KNOWLEDGE",
            "evidence": [
                [source, product, row.get("observation_key"), row.get("version"),
                 row.get("effective_at_utc"), row.get("published_at_utc"),
                 row.get("retrieved_at_utc"), row.get("payload_sha256")]
                for pair, rows in sorted(observations_by_pair.items())
                for source, product in [pair]
                for row in rows
            ],
            "spot_archive_metadata": {
                key: spot_market_archive.get(key)
                for key in ("status", "schema_version", "legacy_candle_count", "versioned_candle_count", "streams")
            },
            "spot_candle_versions": [
                [row.get("source_id"), row.get("broker_server"), row.get("symbol"),
                 row.get("timeframe"), row.get("candle_open_time_utc"),
                 row.get("observed_at_utc"), row.get("as_of_utc"),
                 row.get("version_id"), row.get("values_sha256")]
                for stream in spot_market_archive.get("streams", [])
                for row in stream.get("evidence_candles", [])
            ],
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        eligible_products = quality["eligible_product_count"]
        return {
            "report_type": "UNIFIED_HISTORICAL_DATA_PLANE",
            "version": "1.0.0",
            "status": (
                "UNAVAILABLE" if self._store is None and self._market_store is None
                else "READY" if eligible_products == base["enabled_product_count"] and spot_market_archive["status"] in {"AVAILABLE", "UNAVAILABLE"}
                else "PARTIAL" if eligible_products or spot_streams
                else "NO_QUALITY_ELIGIBLE_PRODUCTS"
            ),
            "read_mode": "STRICT_SYSTEM_KNOWLEDGE",
            "as_of_utc": base["as_of_utc"],
            "snapshot_sha256": snapshot_hash,
            "registry_sha256": registry_sha256,
            "registered_source_count": base["registered_source_count"],
            "enabled_product_count": base["enabled_product_count"],
            "available_product_count": base["available_product_count"],
            "evidence_observation_count": base["observation_count"],
            "quality_eligible_product_count": eligible_products,
            "quality_blocked_product_count": quality["status_counts"]["BLOCKED"],
            "quality_stale_product_count": quality["status_counts"]["STALE"],
            "spot_market_archive": spot_market_archive,
            "evidence_domains": evidence_domains,
            "analytics_domains": analytics_domains,
            "quality_report": quality,
            "policy": {
                "single_as_of_cutoff_across_domains": True,
                "spot_candles_use_separate_append_only_version_ledger": True,
                "strict_system_knowledge_only": True,
                "publication_retrieval_and_effective_cutoffs_enforced": True,
                "quality_gate_applied_before_analytics_view": True,
                "raw_eligible_evidence_preserved": True,
                "blocked_evidence_not_deleted_or_repaired": True,
                "public_availability_reconstruction_not_implicit": True,
                "automatic_fetch": False,
                "database_mutated": False,
                "registry_mutated": False,
                "fusion_or_live_execution_wired": False,
            },
        }

    def read_public_availability_as_of(self, as_of_utc: datetime, *, ledger: Any) -> dict[str, Any]:
        """Explicit reconstructed-public-availability view; never changes system-knowledge reads."""
        cutoff = _as_utc(as_of_utc)
        if self._store is None:
            raise RuntimeError("PUBLIC_AVAILABILITY_REQUIRES_CONFIGURED_OBSERVATION_STORE")
        if not callable(getattr(ledger, "read_public_availability_as_of", None)):
            raise TypeError("ledger must provide read_public_availability_as_of")
        domains: dict[str, list[dict[str, Any]]] = defaultdict(list)
        total = 0
        available = 0
        for item in self._products:
            if not item["enabled"]:
                continue
            rows = ledger.read_public_availability_as_of(
                self._store, source_id=item["source_id"],
                product_id=item["product_id"], as_of_utc=cutoff,
            )
            count = len(rows)
            total += count
            available += int(count > 0)
            domains[item["domain"]].append({**item,
                "status": "AVAILABLE" if count else "MISSING",
                "observation_count": count, "observations": rows})
        output = {}
        for domain, products in sorted(domains.items()):
            have = sum(p["status"] == "AVAILABLE" for p in products)
            output[domain] = {"status": "AVAILABLE" if have == len(products) else "PARTIAL" if have else "MISSING",
                              "registered_enabled_products": len(products),
                              "available_products": have,
                              "observation_count": sum(p["observation_count"] for p in products),
                              "products": products}
        enabled_count = sum(len(v) for v in domains.values())
        return {"report_type": "MULTI_DOMAIN_POINT_IN_TIME_DATA_PLANE",
                "version": self.VERSION, "status": "AVAILABLE" if available == enabled_count and enabled_count else "PARTIAL" if available else "MISSING",
                "as_of_utc": cutoff.isoformat(), "read_mode": "RECONSTRUCTED_PUBLIC_AVAILABILITY",
                "enabled_product_count": enabled_count, "available_product_count": available,
                "observation_count": total, "domains": output,
                "policy": {"retrieval_time_filter_bypassed": False,
                           "requires_per_observation_attestation": True,
                           "unattested_observations_excluded": True,
                           "source_registry_mutated": False,
                           "observation_store_mutated": False}}

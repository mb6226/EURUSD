from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from source_registry.adapters.cftc_positioning import CFTCPositioningAdapter
from source_registry.adapters.macro_series import OfficialMacroSeriesAdapter, US_BLS_SOURCE_ID
from source_registry.adapters.models import FetchRequest
from source_registry.ingestion import SourceObservationIngestion
from source_registry.observation_store import PointInTimeObservationStore
from source_registry.providers.bls import BLSCPIRecordsProvider, UrllibTransport
from source_registry.providers.cftc import CFTCOfficialSnapshotProvider, CFTC_PRODUCTS
from source_registry.raw_archive import RawSnapshotArchive
from source_registry.registry_loader import load_registry

ROOT = Path(__file__).resolve().parents[1]
RAW_DB = ROOT / "source_registry" / "operational" / "raw_snapshots.sqlite"
OBSERVATION_DB = ROOT / "source_registry" / "operational" / "observations.sqlite"


def main() -> int:
    # Reopening this dedicated append-only store is safe and makes retries idempotent.
    registry = load_registry()
    archive = RawSnapshotArchive.from_registry(RAW_DB, registry=registry)
    transport = UrllibTransport(
        allowed_hosts={"api.bls.gov", "www.bls.gov", "blsmon1.bls.gov", "publicreporting.cftc.gov", "www.cftc.gov"},
        timeout_seconds=30,
        max_response_bytes=20 * 1024 * 1024,
    )
    clock = lambda: datetime.now(timezone.utc)

    # BLS CPI: original release value and embargo timestamp must match the API.
    bls_summary = None
    bls_error = None
    store = None
    try:
        bls_provider = BLSCPIRecordsProvider(
            transport=transport, archive=archive, clock=clock, lookback_years=1
        )
        request = FetchRequest(US_BLS_SOURCE_ID, "US_CPI_ALL_ITEMS_INDEX")
        records = bls_provider(request)
        adapter = OfficialMacroSeriesAdapter(
            source_id=US_BLS_SOURCE_ID,
            product_id="US_CPI_ALL_ITEMS_INDEX",
            records_provider=lambda _request: records,
        )
        store = PointInTimeObservationStore(OBSERVATION_DB)
        ingestion = SourceObservationIngestion(
            registry=registry,
            adapters={(US_BLS_SOURCE_ID, "US_CPI_ALL_ITEMS_INDEX"): adapter},
            store=store,
            clock=clock,
        )
        bls_summary = ingestion.ingest(US_BLS_SOURCE_ID, "US_CPI_ALL_ITEMS_INDEX")
    except Exception as exc:
        bls_error = f"{type(exc).__name__}: {exc}"

    # CFTC: archive raw rows + official release evidence, then persist the PIT join.
    cftc_provider = CFTCOfficialSnapshotProvider(
        transport=transport, archive=archive, clock=clock, lookback_days=365
    )
    cftc_summary = cftc_provider.acquire()
    if store is None:
        store = PointInTimeObservationStore(OBSERVATION_DB)
    cftc_adapters = {
        (cftc_summary["source_id"], product_id): CFTCPositioningAdapter(
            product_id=product_id,
            records_provider=lambda _request, product=product_id:
                cftc_provider.records_for_product(product),
        )
        for product_id in CFTC_PRODUCTS
    }
    cftc_ingestion = SourceObservationIngestion(
        registry=registry, adapters=cftc_adapters, store=store, clock=clock
    )
    cftc_persistence = {}
    for product_id in CFTC_PRODUCTS:
        item = cftc_ingestion.ingest(cftc_summary["source_id"], product_id)
        cftc_persistence[product_id] = {
            "observations_received": item.observations_received,
            "observations_inserted": item.persistence.observations_inserted,
            "observations_unchanged": item.persistence.observations_unchanged,
            "observations_revised": item.persistence.observations_revised,
        }
    cftc_summary["pit_ingestion"] = cftc_persistence
    cftc_summary["pit_observations_persisted"] = sum(
        item["observations_inserted"] for item in cftc_persistence.values()
    )

    snapshots = archive.list_snapshots()
    report = {
        "phase": "37B",
        "completed_at_utc": clock().isoformat(),
        "bls_cpi": ({
            "status": "PIT_INGESTED",
            "source_id": bls_summary.source_id,
            "product_id": bls_summary.product_id,
            "observations_received": bls_summary.observations_received,
            "persistence": {
                "batches_inserted": bls_summary.persistence.batches_inserted,
                "observations_inserted": bls_summary.persistence.observations_inserted,
                "observations_unchanged": bls_summary.persistence.observations_unchanged,
                "observations_revised": bls_summary.persistence.observations_revised,
            },
            "point_in_time_basis": "Original BLS CPI archive value + embargo timestamp, cross-checked against current API.",
        } if bls_summary else {
            "status": "RAW_API_SNAPSHOT_ONLY",
            "error": bls_error,
            "pit_observations_persisted": 0,
        }),
        "cftc_tff": cftc_summary,
        "raw_archive": {
            "path": str(RAW_DB),
            "snapshots": len(snapshots),
            "payload_bytes": sum(item["payload_bytes"] for item in snapshots),
        },
        "observation_store": {
            "path": str(OBSERVATION_DB) if store else None,
            "observation_count": store.count_observations() if store else 0,
        },
        "safety": {
            "registry_auto_fetch_changed": False,
            "monitor_restarted": False,
            "vision_enabled": False,
            "live_trading_or_order_execution": False,
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PHASE37B_INGESTION_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

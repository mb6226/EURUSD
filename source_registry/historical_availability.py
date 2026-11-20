from __future__ import annotations

"""Explicit, evidence-backed public-availability replay; never alters strict system PIT."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from typing import Any, Iterable

from .observation_store import PointInTimeObservationStore, _stamp, _utc
from .raw_archive import RawSnapshotArchive

SCHEMA = """
CREATE TABLE IF NOT EXISTS attestations (
 attestation_id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL, product_id TEXT NOT NULL,
 observation_key TEXT NOT NULL, observation_version INTEGER NOT NULL,
 observation_payload_sha256 TEXT NOT NULL, published_at_utc TEXT NOT NULL,
 evidence_json TEXT NOT NULL, evidence_manifest_sha256 TEXT NOT NULL,
 value_vintage_status TEXT NOT NULL CHECK(value_vintage_status='AS_RELEASED_VALUE_VERIFIED'),
 attested_at_utc TEXT NOT NULL, attestor TEXT NOT NULL, method_version TEXT NOT NULL,
 limitations TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_attestation_identity ON attestations(
 source_id, product_id, observation_key, observation_version, observation_payload_sha256
);
CREATE TRIGGER IF NOT EXISTS attestations_no_update BEFORE UPDATE ON attestations
 BEGIN SELECT RAISE(ABORT, 'attestations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS attestations_no_delete BEFORE DELETE ON attestations
 BEGIN SELECT RAISE(ABORT, 'attestations are append-only'); END;
"""


def _aware(value: datetime, field: str) -> datetime:
    return _utc(value, field)


class HistoricalAvailabilityLedger:
    """Append-only ledger; caller must prove both original release and as-released value."""
    VERSION = "1.0.0"

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(SCHEMA)
            db.commit()

    def attest(self, *, observation: dict[str, Any], published_at_utc: datetime,
               evidence_snapshot_ids: Iterable[str], archive: RawSnapshotArchive, observation_store: PointInTimeObservationStore,
               attested_at_utc: datetime, attestor: str, method_version: str,
               value_vintage_status: str, limitations: str = "") -> str:
        required = ("source_id", "product_id", "observation_key", "version", "payload_sha256", "published_at_utc")
        if any(k not in observation for k in required):
            raise ValueError("observation identity is incomplete")
        if int(observation["version"]) != 1:
            raise ValueError("revised observation versions need their own verified public-availability timestamp; not supported by v1")
        published = _stamp(_aware(published_at_utc, "published_at_utc"))
        observed_publication = observation["published_at_utc"]
        if not observed_publication or _stamp(datetime.fromisoformat(observed_publication.replace("Z", "+00:00"))) != published:
            raise ValueError("attested publication timestamp does not match stored observation")
        attested = _stamp(_aware(attested_at_utc, "attested_at_utc"))
        if not getattr(observation_store, "_read_only", False):
            raise ValueError("observation store must be opened read-only")
        db = observation_store._connect()
        try:
            stored = db.execute(
                "SELECT * FROM observations WHERE source_id=? AND product_id=? AND observation_key=? AND version=? AND payload_sha256=?",
                (observation["source_id"], observation["product_id"], observation["observation_key"], observation["version"], observation["payload_sha256"]),
            ).fetchone()
        finally:
            db.close()
        if stored is None:
            raise ValueError("observation does not exist in the canonical store")
        if datetime.fromisoformat(attested.replace("Z", "+00:00")) < datetime.fromisoformat(stored["retrieved_at_utc"].replace("Z", "+00:00")):
            raise ValueError("attestation cannot predate local retrieval")
        if not attestor.strip() or not method_version.strip():
            raise ValueError("attestor and method_version are required")
        if value_vintage_status != "AS_RELEASED_VALUE_VERIFIED":
            raise ValueError("public replay requires verified as-released value; current/latest values cannot be backdated")
        ids = sorted(set(evidence_snapshot_ids))
        if len(ids) < 2:
            raise ValueError("at least two independent archived evidence snapshots are required")
        snapshots = {s["snapshot_id"]: s for s in archive.list_snapshots()}
        evidence = []
        for sid in ids:
            item = snapshots.get(sid)
            if item is None:
                raise ValueError(f"unknown evidence snapshot: {sid}")
            payload = archive.get_payload(sid)
            digest = sha256(payload).hexdigest()
            if digest != item["payload_sha256"]:
                raise ValueError("evidence snapshot hash mismatch")
            if datetime.fromisoformat(attested.replace("Z", "+00:00")) < datetime.fromisoformat(item["retrieved_at_utc"].replace("Z", "+00:00")):
                raise ValueError("attestation cannot predate archived evidence retrieval")
            evidence.append({"snapshot_id": sid, "source_id": item["source_id"],
                             "product_id": item["product_id"], "source_url": item["source_url"],
                             "retrieved_at_utc": item["retrieved_at_utc"], "payload_sha256": digest})
        if len({item["source_url"] for item in evidence}) < 2:
            raise ValueError("evidence must include at least two distinct official source URLs")
        manifest = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        manifest_hash = sha256(manifest.encode()).hexdigest()
        identity = {"source_id": observation["source_id"], "product_id": observation["product_id"],
                    "observation_key": observation["observation_key"], "version": observation["version"],
                    "payload_sha256": observation["payload_sha256"], "published_at_utc": published,
                    "evidence_manifest_sha256": manifest_hash, "attestor": attestor, "method_version": method_version}
        attestation_id = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT OR IGNORE INTO attestations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                attestation_id, observation["source_id"], observation["product_id"],
                observation["observation_key"], observation["version"], observation["payload_sha256"],
                published, manifest, manifest_hash, value_vintage_status, attested, attestor,
                method_version, limitations))
            db.commit()
        return attestation_id

    def read_public_availability_as_of(self, store: PointInTimeObservationStore, *,
                                       source_id: str, product_id: str, as_of_utc: datetime) -> list[dict[str, Any]]:
        if not getattr(store, "_read_only", False):
            raise ValueError("observation store must be opened read-only")
        cutoff = _stamp(_aware(as_of_utc, "as_of_utc"))
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            attestations = db.execute("""SELECT * FROM attestations WHERE source_id=? AND product_id=?
                AND published_at_utc<=? AND value_vintage_status='AS_RELEASED_VALUE_VERIFIED'
                ORDER BY observation_key, observation_version""", (source_id, product_id, cutoff)).fetchall()
        output = {}
        connection = store._connect()
        try:
            for att in attestations:
                row = connection.execute("""SELECT * FROM observations WHERE source_id=? AND product_id=?
                    AND observation_key=? AND version=? AND payload_sha256=? AND published_at_utc=?
                    AND effective_at_utc<=?""", (source_id, product_id, att["observation_key"],
                    att["observation_version"], att["observation_payload_sha256"],
                    att["published_at_utc"], cutoff)).fetchone()
                if row is None:
                    continue
                output[row["observation_key"]] = {
                    "source_id": row["source_id"], "product_id": row["product_id"],
                    "observation_key": row["observation_key"], "version": row["version"],
                    "effective_at_utc": row["effective_at_utc"], "published_at_utc": row["published_at_utc"],
                    "retrieved_at_utc": row["retrieved_at_utc"], "value": json.loads(row["value_json"]),
                    "unit": row["unit"], "source_record_id": row["source_record_id"],
                    "source_url": row["source_url"], "payload_sha256": row["payload_sha256"],
                    "availability_mode": "RECONSTRUCTED_PUBLIC_AVAILABILITY",
                    "attestation_id": att["attestation_id"],
                    "attested_at_utc": att["attested_at_utc"],
                    "evidence_manifest_sha256": att["evidence_manifest_sha256"],
                    "limitations": att["limitations"],
                }
        finally:
            connection.close()
        return sorted(output.values(), key=lambda x: (x["effective_at_utc"], x["observation_key"]))

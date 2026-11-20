from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_SENSITIVE_KEYS = {
    "api_key", "apikey", "key", "token", "access_token",
    "authorization", "password", "secret", "cookie", "set_cookie",
}


def _is_sensitive_key(value: object) -> bool:
    normalized = str(value).casefold().replace("-", "_")
    return (
        normalized in _SENSITIVE_KEYS
        or normalized.endswith("_api_key")
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
    )


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("<redacted>" if _is_sensitive_key(key) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    query = [
        (key, "<redacted>" if _is_sensitive_key(key) else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _utc_stamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("retrieved_at_utc must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retrieved_at_utc must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class RawSnapshotSummary:
    snapshot_id: str
    source_id: str
    product_id: str
    retrieved_at_utc: str
    payload_sha256: str
    payload_bytes: int
    inserted: bool


class RawSnapshotArchive:
    """Append-only archive of original provider payloads, before normalization.

    No network access is performed here. Callers supply bytes received from an
    explicitly selected provider; this archive preserves those exact bytes and
    the transport metadata needed to reproduce parsing and revision decisions.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: str | Path,
        *,
        allowed_products: Mapping[str, set[str]],
        max_payload_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self.path = Path(path)
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        if not isinstance(allowed_products, Mapping):
            raise TypeError("allowed_products must map source IDs to product ID sets")
        self.allowed_products = {
            source: set(products) for source, products in allowed_products.items()
        }
        self.max_payload_bytes = max_payload_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_registry(
        cls,
        path: str | Path,
        *,
        registry: Mapping[str, Any],
        max_payload_bytes: int = 50 * 1024 * 1024,
    ) -> "RawSnapshotArchive":
        """Create an archive allowlist from enabled products in a validated registry."""
        if not isinstance(registry, Mapping) or not isinstance(registry.get("sources"), list):
            raise TypeError("registry must be a validated registry mapping")
        allowed: dict[str, set[str]] = {}
        for source in registry["sources"]:
            if not isinstance(source, Mapping):
                raise ValueError("registry sources must be objects")
            if source.get("enabled") is not True:
                continue
            source_id = source.get("source_id")
            products = source.get("products")
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("source_id must be non-empty")
            if not isinstance(products, list):
                raise ValueError(f"{source_id} products must be a list")
            allowed[source_id] = {
                product["product_id"]
                for product in products
                if isinstance(product, Mapping)
                and isinstance(product.get("product_id"), str)
                and product["product_id"].strip()
            }
        return cls(
            path,
            allowed_products=allowed,
            max_payload_bytes=max_payload_bytes,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS archive_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS raw_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    retrieved_at_utc TEXT NOT NULL,
                    http_status INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    etag TEXT,
                    last_modified TEXT,
                    response_headers_json TEXT NOT NULL,
                    request_metadata_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_bytes INTEGER NOT NULL,
                    payload BLOB NOT NULL,
                    UNIQUE(source_id, product_id, retrieved_at_utc, payload_sha256)
                );
                CREATE INDEX IF NOT EXISTS idx_raw_snapshots_product_time
                    ON raw_snapshots(source_id, product_id, retrieved_at_utc);
                CREATE TRIGGER IF NOT EXISTS raw_snapshots_no_update
                BEFORE UPDATE ON raw_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'raw snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS raw_snapshots_no_delete
                BEFORE DELETE ON raw_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'raw snapshots are immutable');
                END;
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO archive_meta(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
            connection.commit()
        finally:
            connection.close()

    def append(
        self,
        *,
        source_id: str,
        product_id: str,
        source_url: str,
        retrieved_at_utc: datetime,
        http_status: int,
        content_type: str,
        payload: bytes,
        response_headers: Mapping[str, Any] | None = None,
        request_metadata: Mapping[str, Any] | None = None,
    ) -> RawSnapshotSummary:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id must be non-empty")
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id must be non-empty")
        if product_id not in self.allowed_products.get(source_id, set()):
            raise ValueError(f"source/product is not allowlisted: {source_id}/{product_id}")
        parsed = urlsplit(source_url) if isinstance(source_url, str) else None
        if parsed is None or parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("source_url must be an absolute HTTPS URL")
        if isinstance(http_status, bool) or not isinstance(http_status, int) or http_status != 200:
            raise ValueError("only successful HTTP 200 responses may be archived")
        if not isinstance(content_type, str) or not content_type.strip():
            raise ValueError("content_type must be non-empty")
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("payload must be non-empty bytes")
        if len(payload) > self.max_payload_bytes:
            raise ValueError("payload exceeds max_payload_bytes")
        retrieved = _utc_stamp(retrieved_at_utc)
        headers = _redact(dict(response_headers or {}))
        request = _redact(dict(request_metadata or {}))
        safe_url = _safe_url(source_url)
        headers_json = _canonical(headers)
        request_json = _canonical(request)
        digest = sha256(payload).hexdigest()
        identity = _canonical({
            "source_id": source_id,
            "product_id": product_id,
            "source_url": safe_url,
            "retrieved_at_utc": retrieved,
            "payload_sha256": digest,
        })
        snapshot_id = sha256(identity.encode("utf-8")).hexdigest()

        connection = self._connect()
        inserted = False
        try:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO raw_snapshots (
                    snapshot_id, source_id, product_id, source_url,
                    retrieved_at_utc, http_status, content_type, etag,
                    last_modified, response_headers_json, request_metadata_json,
                    payload_sha256, payload_bytes, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id, source_id, product_id, safe_url, retrieved,
                    http_status, content_type,
                    headers.get("ETag") or headers.get("etag"),
                    headers.get("Last-Modified") or headers.get("last-modified"),
                    headers_json, request_json, digest, len(payload), payload,
                ),
            )
            inserted = cursor.rowcount == 1
            connection.commit()
        finally:
            connection.close()
        return RawSnapshotSummary(
            snapshot_id=snapshot_id,
            source_id=source_id,
            product_id=product_id,
            retrieved_at_utc=retrieved,
            payload_sha256=digest,
            payload_bytes=len(payload),
            inserted=inserted,
        )

    def get_payload(self, snapshot_id: str) -> bytes:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ValueError("snapshot_id must be non-empty")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT payload FROM raw_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(snapshot_id)
        return bytes(row["payload"])

    def list_snapshots(
        self, source_id: str | None = None, product_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            parameters.append(source_id)
        if product_id is not None:
            clauses.append("product_id = ?")
            parameters.append(product_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT snapshot_id, source_id, product_id, source_url,
                       retrieved_at_utc, http_status, content_type, etag,
                       last_modified, response_headers_json, request_metadata_json,
                       payload_sha256, payload_bytes
                FROM raw_snapshots
                """ + where + " ORDER BY retrieved_at_utc, snapshot_id",
                parameters,
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                **dict(row),
                "response_headers": json.loads(row["response_headers_json"]),
                "request_metadata": json.loads(row["request_metadata_json"]),
            }
            for row in rows
        ]

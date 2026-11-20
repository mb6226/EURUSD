from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eurusd_ai_monitor.storage.market_data_store import (
    _BACKFILL_SCHEMA, _CANDLE_VERSION_SCHEMA, _PA_LIFECYCLE_SCHEMA,
    _SCHEMA, _SCHEMA_VERSION,
)

DEFAULT_DB = ROOT / "eurusd_ai_monitor" / "data" / "market" / "market_data.sqlite"


def inspect_database(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path, timeout=5) as con:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        candle_count = int(con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]) if "candles" in tables else 0
        version_count = int(con.execute("SELECT COUNT(*) FROM candle_versions").fetchone()[0]) if "candle_versions" in tables else 0
    return {"path": str(path), "integrity": integrity, "schema_version": version,
            "legacy_candle_count": candle_count, "versioned_candle_count": version_count,
            "version_ledger_available": version >= 4 and "candle_versions" in tables}


def migrate(path: Path) -> dict:
    before = inspect_database(path)
    if before["integrity"] != "ok":
        raise RuntimeError("DATABASE_INTEGRITY_CHECK_FAILED")
    if before["schema_version"] == _SCHEMA_VERSION:
        return {"status": "ALREADY_CURRENT", **before}
    if before["schema_version"] != 3:
        raise RuntimeError(f"UNSUPPORTED_SCHEMA_VERSION_{before['schema_version']}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(path.name + f".pre-v4-{stamp}.bak")
    source = sqlite3.connect(path, timeout=5)
    target = sqlite3.connect(backup, timeout=5)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    backup_check = inspect_database(backup)
    if backup_check["integrity"] != "ok" or backup_check["legacy_candle_count"] != before["legacy_candle_count"]:
        raise RuntimeError("BACKUP_VERIFICATION_FAILED")

    schema = "\n".join((_SCHEMA, _BACKFILL_SCHEMA, _PA_LIFECYCLE_SCHEMA, _CANDLE_VERSION_SCHEMA))
    with sqlite3.connect(path, timeout=5) as con:
        con.execute("PRAGMA busy_timeout=5000")
        try:
            con.executescript("BEGIN EXCLUSIVE;\n" + schema +
                              f"\nPRAGMA user_version = {_SCHEMA_VERSION};\nCOMMIT;")
        except Exception:
            try:
                con.rollback()
            except Exception:
                pass
            raise
    after = inspect_database(path)
    if after["integrity"] != "ok" or not after["version_ledger_available"]:
        raise RuntimeError("POST_MIGRATION_VERIFICATION_FAILED")
    if after["legacy_candle_count"] != before["legacy_candle_count"]:
        raise RuntimeError("LEGACY_CANDLE_COUNT_CHANGED")
    if after["versioned_candle_count"] != 0:
        raise RuntimeError("LEGACY_CANDLES_MUST_NOT_BE_BACKDATED_AS_VERSIONS")
    return {"status": "MIGRATED_SCHEMA_ONLY", "backup_path": str(backup),
            "before": before, "after": after,
            "legacy_rows_promoted": 0,
            "note": "Old candles remain legacy/unversioned. New code must be running for future ingestions to populate candle_versions."}


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely migrate the EURUSD market archive schema 3 to 4.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="Create verified backup and apply schema-only migration.")
    args = parser.parse_args()
    current = inspect_database(args.db)
    if not args.apply:
        print({"mode": "PREFLIGHT_ONLY", **current,
               "next_action": "Run with --apply only during a controlled writer-free window."})
        return 0
    result = migrate(args.db)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

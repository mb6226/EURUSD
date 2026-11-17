import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from source_registry.manager import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_SCHEMA_DIR,
    RegistryManager,
)
from source_registry.state_db import initialize_state_db

TABLES = (
    "source_state",
    "product_state",
    "source_status_history",
    "product_status_history",
    "source_runs",
    "source_run_attempts",
)


def snapshot_database(db_path):
    with closing(sqlite3.connect(db_path)) as db:
        result = {}
        for table in TABLES:
            rows = db.execute(f"SELECT * FROM {table}").fetchall()
            result[table] = sorted(repr(row) for row in rows)
        return result


class RegistryIdempotencyTests(unittest.TestCase):
    def test_two_consecutive_syncs_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.db"
            initialize_state_db(db_path)

            manager = RegistryManager(
                registry_path=DEFAULT_REGISTRY_PATH,
                state_db_path=db_path,
                schema_dir=DEFAULT_SCHEMA_DIR,
            )

            first = manager.sync()
            first_snapshot = snapshot_database(db_path)

            second = manager.sync()
            second_snapshot = snapshot_database(db_path)

            self.assertEqual(first.sources_added, 2)
            self.assertEqual(first.products_added, 4)
            self.assertEqual(second.sources_added, 0)
            self.assertEqual(second.products_added, 0)
            self.assertEqual(first_snapshot, second_snapshot)

            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(
                    db.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    db.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )

                expected_counts = {
                    "source_state": 2,
                    "product_state": 4,
                    "source_status_history": 2,
                    "product_status_history": 4,
                    "source_runs": 0,
                    "source_run_attempts": 0,
                }
                for table, expected_count in expected_counts.items():
                    with self.subTest(table=table):
                        count = db.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0]
                        self.assertEqual(count, expected_count)


if __name__ == "__main__":
    unittest.main()

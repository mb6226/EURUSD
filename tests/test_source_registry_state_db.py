import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from source_registry.state_db import initialize_state_db


@contextmanager
def db_connection(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class StateDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        initialize_state_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_creates_source_and_product_state_tables(self):
        with db_connection(self.db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        self.assertTrue(
            {
                "source_state",
                "product_state",
                "source_runs",
                "source_run_attempts",
                "source_status_history",
                "product_status_history",
            }.issubset(tables)
        )

    def test_queued_run_can_have_no_start_time(self):
        with db_connection(self.db_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO source_state (source_id, status, updated_at_utc)
                VALUES ('TEST_SOURCE', 'NOT_CONNECTED', '2026-01-01T00:00:00Z')
                """
            )
            cursor = connection.execute(
                """
                INSERT INTO source_runs (
                    source_id, trigger_type, status, created_at_utc
                )
                VALUES (
                    'TEST_SOURCE', 'SCHEDULED', 'QUEUED',
                    '2026-01-01T00:00:00Z'
                )
                """
            )
            run = connection.execute(
                "SELECT created_at_utc, started_at_utc, finished_at_utc "
                "FROM source_runs WHERE run_id = ?",
                (cursor.lastrowid,),
            ).fetchone()

        self.assertEqual(
            run,
            ("2026-01-01T00:00:00Z", None, None),
        )

    def test_product_state_and_history_are_scoped_to_product(self):
        with db_connection(self.db_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO source_state (source_id, status, updated_at_utc)
                VALUES ('TEST_SOURCE', 'NOT_CONNECTED', '2026-01-01T00:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO product_state (
                    source_id, product_id, status, updated_at_utc
                )
                VALUES (
                    'TEST_SOURCE', 'TEST_PRODUCT', 'ACTIVE',
                    '2026-01-01T00:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO product_status_history (
                    source_id, product_id, to_status, reason_code,
                    changed_at_utc
                )
                VALUES (
                    'TEST_SOURCE', 'TEST_PRODUCT', 'ACTIVE', 'TEST',
                    '2026-01-01T00:00:00Z'
                )
                """
            )
            count = connection.execute(
                """
                SELECT COUNT(*) FROM product_status_history
                WHERE source_id = 'TEST_SOURCE' AND product_id = 'TEST_PRODUCT'
                """
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_attempt_can_be_scoped_to_a_product(self):
        with db_connection(self.db_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO source_state (source_id, status, updated_at_utc)
                VALUES ('TEST_SOURCE', 'NOT_CONNECTED', '2026-01-01T00:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO product_state (
                    source_id, product_id, status, updated_at_utc
                )
                VALUES (
                    'TEST_SOURCE', 'TEST_PRODUCT', 'NOT_CONNECTED',
                    '2026-01-01T00:00:00Z'
                )
                """
            )
            run_id = connection.execute(
                """
                INSERT INTO source_runs (
                    source_id, trigger_type, status, created_at_utc,
                    started_at_utc
                )
                VALUES (
                    'TEST_SOURCE', 'MANUAL', 'RUNNING',
                    '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z'
                )
                """
            ).lastrowid
            connection.execute(
                """
                INSERT INTO source_run_attempts (
                    run_id, source_id, product_id, attempt_number,
                    started_at_utc, finished_at_utc, outcome
                )
                VALUES (
                    ?, 'TEST_SOURCE', 'TEST_PRODUCT', 1,
                    '2026-01-01T00:00:01Z', '2026-01-01T00:00:02Z',
                    'SUCCEEDED'
                )
                """,
                (run_id,),
            )

        self.assertIsNotNone(run_id)

    def test_reinitializing_does_not_remove_existing_state(self):
        with db_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO source_state (source_id, status, updated_at_utc)
                VALUES ('TEST_SOURCE', 'ACTIVE', '2026-01-01T00:00:00Z')
                """
            )

        initialize_state_db(self.db_path)

        with db_connection(self.db_path) as connection:
            status = connection.execute(
                "SELECT status FROM source_state WHERE source_id = 'TEST_SOURCE'"
            ).fetchone()[0]

        self.assertEqual(status, "ACTIVE")


if __name__ == "__main__":
    unittest.main()

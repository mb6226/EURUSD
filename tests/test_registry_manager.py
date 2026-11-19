import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from source_registry.manager import RegistryManager
from source_registry.registry_loader import (
    RegistryLoaderError,
    RegistryValidationError,
    load_registry,
)
from source_registry.state_db import connect_state_db, initialize_state_db

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = PROJECT_ROOT / "source_registry" / "registry.json"
SCHEMA_DIR = PROJECT_ROOT / "source_registry" / "schemas"


@contextmanager
def state_connection(path):
    connection = connect_state_db(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class RegistryLoaderTests(unittest.TestCase):
    def test_loads_valid_registry_with_schema_validation(self):
        registry = load_registry(DEFAULT_REGISTRY, SCHEMA_DIR)

        self.assertEqual(registry["schema_version"], 1)
        self.assertTrue(registry["sources"])
        self.assertTrue(
            all(source["auto_fetch"] is False for source in registry["sources"])
        )

    def test_rejects_schema_invalid_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "registry.json"
            path.write_text(
                json.dumps({"schema_version": 1, "sources": [{}]}),
                encoding="utf-8",
            )

            with self.assertRaises(RegistryValidationError):
                load_registry(path, SCHEMA_DIR)

    def test_rejects_invalid_retry_configuration(self):
        registry = load_registry(DEFAULT_REGISTRY, SCHEMA_DIR)
        registry["sources"][0]["fetch"]["max_attempts"] = 4

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaises(RegistryValidationError):
                load_registry(path, SCHEMA_DIR)

    def test_reports_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "registry.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaises(RegistryLoaderError):
                load_registry(path, SCHEMA_DIR)


class RegistryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.registry_path = self.root / "registry.json"
        self.db_path = self.root / "state.db"
        self.registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
        self.write_registry(self.registry)
        initialize_state_db(self.db_path)
        self.manager = RegistryManager(
            registry_path=self.registry_path,
            state_db_path=self.db_path,
            schema_dir=SCHEMA_DIR,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_registry(self, registry):
        self.registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_creates_initial_source_and_product_states(self):
        result = self.manager.sync()

        self.assertEqual(result.sources_added, 9)
        self.assertEqual(result.products_added, 17)
        with state_connection(self.db_path) as connection:
            source_statuses = {
                row["status"]
                for row in connection.execute("SELECT status FROM source_state")
            }
            product_statuses = {
                row["status"]
                for row in connection.execute("SELECT status FROM product_state")
            }

        self.assertEqual(source_statuses, {"NOT_CONNECTED"})
        self.assertEqual(product_statuses, {"NOT_CONNECTED"})

    def test_repeated_sync_preserves_existing_state_and_history(self):
        self.manager.sync()
        with state_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE source_state
                SET status = 'ACTIVE',
                    last_success_at_utc = '2026-01-01T00:00:00Z'
                WHERE source_id = 'FED_FOMC_POLICY'
                """
            )
            before_state = tuple(
                connection.execute(
                    """
                    SELECT status, last_success_at_utc, updated_at_utc
                    FROM source_state
                    WHERE source_id = 'FED_FOMC_POLICY'
                    """
                ).fetchone()
            )
            before_history = connection.execute(
                "SELECT COUNT(*) FROM source_status_history"
            ).fetchone()[0]

        result = self.manager.sync()

        with state_connection(self.db_path) as connection:
            after_state = tuple(
                connection.execute(
                    """
                    SELECT status, last_success_at_utc, updated_at_utc
                    FROM source_state
                    WHERE source_id = 'FED_FOMC_POLICY'
                    """
                ).fetchone()
            )
            after_history = connection.execute(
                "SELECT COUNT(*) FROM source_status_history"
            ).fetchone()[0]

        self.assertEqual(result.sources_added, 0)
        self.assertEqual(result.products_added, 0)
        self.assertEqual(after_state, before_state)
        self.assertEqual(after_history, before_history)

    def test_removed_source_and_products_are_retired(self):
        self.manager.sync()
        with state_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO source_runs (
                    source_id, trigger_type, status, created_at_utc
                )
                VALUES (
                    'FED_FOMC_POLICY', 'MANUAL', 'QUEUED',
                    '2026-01-01T00:00:00Z'
                )
                """
            )

        self.registry["sources"] = [
            source
            for source in self.registry["sources"]
            if source["source_id"] != "FED_FOMC_POLICY"
        ]
        self.write_registry(self.registry)
        result = self.manager.sync()

        with state_connection(self.db_path) as connection:
            source_status = connection.execute(
                """
                SELECT status FROM source_state
                WHERE source_id = 'FED_FOMC_POLICY'
                """
            ).fetchone()["status"]
            product_status = connection.execute(
                """
                SELECT DISTINCT status FROM product_state
                WHERE source_id = 'FED_FOMC_POLICY'
                """
            ).fetchall()
            run_count = connection.execute(
                """
                SELECT COUNT(*) FROM source_runs
                WHERE source_id = 'FED_FOMC_POLICY'
                """
            ).fetchone()[0]

        self.assertEqual(result.sources_retired, 1)
        self.assertEqual(source_status, "RETIRED")
        self.assertEqual({row["status"] for row in product_status}, {"RETIRED"})
        self.assertEqual(run_count, 1)

    def test_removed_product_is_retired_without_retiring_source(self):
        self.manager.sync()
        source = next(
            source
            for source in self.registry["sources"]
            if source["source_id"] == "ECB_POLICY_RATES"
        )
        source["products"] = [
            product
            for product in source["products"]
            if product["product_id"] != "ECB_MAIN_REFINANCING_RATE"
        ]
        self.write_registry(self.registry)

        result = self.manager.sync()

        with state_connection(self.db_path) as connection:
            source_status = connection.execute(
                """
                SELECT status FROM source_state
                WHERE source_id = 'ECB_POLICY_RATES'
                """
            ).fetchone()["status"]
            product_status = connection.execute(
                """
                SELECT status FROM product_state
                WHERE source_id = 'ECB_POLICY_RATES'
                  AND product_id = 'ECB_MAIN_REFINANCING_RATE'
                """
            ).fetchone()["status"]
            history_count = connection.execute(
                """
                SELECT COUNT(*) FROM product_status_history
                WHERE source_id = 'ECB_POLICY_RATES'
                  AND product_id = 'ECB_MAIN_REFINANCING_RATE'
                  AND reason_code = 'REMOVED_FROM_REGISTRY'
                """
            ).fetchone()[0]

        self.assertEqual(result.products_retired, 1)
        self.assertEqual(source_status, "NOT_CONNECTED")
        self.assertEqual(product_status, "RETIRED")
        self.assertEqual(history_count, 1)

    def test_disabled_source_is_not_retired(self):
        self.manager.sync()
        with state_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE source_state
                SET status = 'ACTIVE'
                WHERE source_id = 'FED_FOMC_POLICY'
                """
            )

        source = next(
            source
            for source in self.registry["sources"]
            if source["source_id"] == "FED_FOMC_POLICY"
        )
        source["enabled"] = False
        self.write_registry(self.registry)

        result = self.manager.sync()

        with state_connection(self.db_path) as connection:
            status = connection.execute(
                """
                SELECT status FROM source_state
                WHERE source_id = 'FED_FOMC_POLICY'
                """
            ).fetchone()["status"]

        self.assertEqual(result.sources_retired, 0)
        self.assertEqual(status, "ACTIVE")

    def test_readded_source_is_reactivated_without_losing_run_history(self):
        self.manager.sync()
        with state_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO source_runs (
                    source_id, trigger_type, status, created_at_utc
                )
                VALUES (
                    'FED_FOMC_POLICY', 'MANUAL', 'QUEUED',
                    '2026-01-01T00:00:00Z'
                )
                """
            )

        all_sources = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
        self.registry["sources"] = [
            source
            for source in self.registry["sources"]
            if source["source_id"] != "FED_FOMC_POLICY"
        ]
        self.write_registry(self.registry)
        self.manager.sync()

        self.write_registry(all_sources)
        result = self.manager.sync()

        with state_connection(self.db_path) as connection:
            source_status = connection.execute(
                """
                SELECT status FROM source_state
                WHERE source_id = 'FED_FOMC_POLICY'
                """
            ).fetchone()["status"]
            run_count = connection.execute(
                """
                SELECT COUNT(*) FROM source_runs
                WHERE source_id = 'FED_FOMC_POLICY'
                """
            ).fetchone()[0]
            transitions = connection.execute(
                """
                SELECT COUNT(*) FROM source_status_history
                WHERE source_id = 'FED_FOMC_POLICY'
                  AND reason_code IN (
                      'REMOVED_FROM_REGISTRY',
                      'REACTIVATED_IN_REGISTRY'
                  )
                """
            ).fetchone()[0]

        self.assertEqual(result.sources_reactivated, 1)
        self.assertEqual(source_status, "NOT_CONNECTED")
        self.assertEqual(run_count, 1)
        self.assertEqual(transitions, 2)

    def test_registry_validation_failure_does_not_change_database(self):
        self.manager.sync()
        with state_connection(self.db_path) as connection:
            before_sources = connection.execute(
                "SELECT COUNT(*) FROM source_state"
            ).fetchone()[0]
            before_history = connection.execute(
                "SELECT COUNT(*) FROM source_status_history"
            ).fetchone()[0]

        self.write_registry({"schema_version": 1, "sources": [{}]})
        with self.assertRaises(RegistryValidationError):
            self.manager.sync()

        with state_connection(self.db_path) as connection:
            after_sources = connection.execute(
                "SELECT COUNT(*) FROM source_state"
            ).fetchone()[0]
            after_history = connection.execute(
                "SELECT COUNT(*) FROM source_status_history"
            ).fetchone()[0]

        self.assertEqual(after_sources, before_sources)
        self.assertEqual(after_history, before_history)

    def test_database_error_rolls_back_entire_sync(self):
        with state_connection(self.db_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_product_state
                BEFORE INSERT ON product_state
                BEGIN
                    SELECT RAISE(ABORT, 'forced test failure');
                END
                """
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.manager.sync()

        with state_connection(self.db_path) as connection:
            source_count = connection.execute(
                "SELECT COUNT(*) FROM source_state"
            ).fetchone()[0]
            product_count = connection.execute(
                "SELECT COUNT(*) FROM product_state"
            ).fetchone()[0]
            history_count = connection.execute(
                "SELECT COUNT(*) FROM source_status_history"
            ).fetchone()[0]

        self.assertEqual(source_count, 0)
        self.assertEqual(product_count, 0)
        self.assertEqual(history_count, 0)


if __name__ == "__main__":
    unittest.main()

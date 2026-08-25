"""Unit tests for SQLite migration runner."""

import tempfile
import unittest
from pathlib import Path

from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner


class TestMigrations(unittest.TestCase):
    """Test suite for database migrations."""

    def test_run_initial_migration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ailen_mig.db"
            db_mgr = SQLiteManager(db_path)
            runner = MigrationRunner(db_mgr)

            available = runner.get_available_migrations()
            self.assertTrue(len(available) >= 1)
            self.assertEqual(available[0][0], 1)

            # First run applies migration
            applied = runner.run_migrations()
            self.assertEqual(applied, 4)
            self.assertEqual(runner.get_current_version(), 4)

            # Second run is idempotent (0 applied)
            applied_again = runner.run_migrations()
            self.assertEqual(applied_again, 0)
            self.assertEqual(runner.get_current_version(), 4)

            # Check that tables exist
            with db_mgr.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = {row[0] for row in cursor.fetchall()}
                self.assertIn("schema_meta", tables)
                self.assertIn("sessions", tables)
                self.assertIn("messages", tables)
                self.assertIn("memories", tables)
                self.assertIn("business_facts", tables)
                self.assertIn("system_events", tables)
                self.assertIn("admin_credentials", tables)
                self.assertIn("notes", tables)
                self.assertIn("reminders", tables)
                self.assertIn("tool_events", tables)

    def test_migration_0002_admin_credentials_single_row(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ailen_auth.db"
            db_mgr = SQLiteManager(db_path)
            runner = MigrationRunner(db_mgr)
            runner.run_migrations()

            import sqlite3

            with db_mgr.connection() as conn:
                cursor = conn.cursor()
                # Fila única: id distinto de 1 debe ser rechazado por el CHECK.
                with self.assertRaises(sqlite3.IntegrityError):
                    cursor.execute(
                        "INSERT INTO admin_credentials (id, username, password_hash, "
                        "salt, kdf, iterations, created_at, updated_at) "
                        "VALUES (2, 'x', x'00', x'00', 'kdf', 1, 't', 't');"
                    )


if __name__ == "__main__":
    unittest.main()

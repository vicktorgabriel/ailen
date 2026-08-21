"""Unit tests for SQLiteManager."""

import os
import tempfile
import unittest
from pathlib import Path

from ailen.infrastructure.sqlite.connection import SQLiteManager


class TestSQLiteManager(unittest.TestCase):
    """Test suite for SQLite connection manager."""

    def test_in_memory_connection(self):
        mgr = SQLiteManager(":memory:")
        self.assertTrue(mgr.check_health())

        with mgr.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT);")
            cursor.execute("INSERT INTO test (val) VALUES ('hello');")

        # In-memory creates separate DBs per connection in standard SQLite unless shared,
        # but check_health and execute work without error.
        self.assertTrue(mgr.check_health())

    def test_file_database_persistence_and_pragmas(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            mgr = SQLiteManager(db_path)

            with mgr.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT);")
                cursor.execute("INSERT INTO kv VALUES ('greeting', 'hola');")

            # Check pragma settings
            with mgr.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA foreign_keys;")
                row = cursor.fetchone()
                self.assertEqual(row[0], 1)

                cursor.execute("SELECT v FROM kv WHERE k = 'greeting';")
                row = cursor.fetchone()
                self.assertEqual(row["v"], "hola")

    @unittest.skipUnless(os.name == "posix", "POSIX permissions only")
    def test_file_database_is_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "private.db"
            mgr = SQLiteManager(db_path)
            with mgr.connection() as conn:
                conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY);")
            self.assertEqual(db_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()

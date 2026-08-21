"""SQLite connection management for AILEN."""

import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("ailen.infrastructure.sqlite")


class SQLiteManager:
    """Manages SQLite database connections and configuration."""

    def __init__(self, db_path: str | Path = "data/ailen.db"):
        self.db_path = Path(db_path)
        self._ensure_parent_directory()

    def _ensure_parent_directory(self) -> None:
        """Create parent directory if it does not exist (unless in-memory)."""
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def create_connection(self) -> sqlite3.Connection:
        """Create and configure a new SQLite connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        # This database contains private memory and the admin credential hash.
        # On POSIX filesystems, keep the DB owner-only; SQLite WAL/SHM files
        # inherit the database mode when they are created.
        if str(self.db_path) != ":memory:":
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                logger.warning("Could not restrict SQLite file permissions: %s", self.db_path)

        # Optimize SQLite for reliable embedded multi-process operation
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        if str(self.db_path) != ":memory:":
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.close()

        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for SQLite connections with automatic commit/rollback."""
        conn = self.create_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Database transaction failed")
            raise
        finally:
            conn.close()

    def check_health(self) -> bool:
        """Verify database connectivity and query execution."""
        try:
            with self.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1;")
                row = cursor.fetchone()
                return bool(row and row[0] == 1)
        except (sqlite3.Error, OSError) as exc:
            logger.error("Database health check failed: %s", exc)
            return False

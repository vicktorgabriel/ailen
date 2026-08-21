"""SQLite migration runner for AILEN."""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ailen.infrastructure.sqlite.connection import SQLiteManager

logger = logging.getLogger("ailen.infrastructure.sqlite.migrations")


class MigrationRunner:
    """Manages schema versioning and execution of SQL migration scripts."""

    def __init__(self, db_manager: SQLiteManager, migrations_dir: Path | None = None):
        self.db_manager = db_manager
        self.migrations_dir = migrations_dir or (Path(__file__).parent / "migrations")

    def _ensure_meta_table(self, conn: sqlite3.Connection) -> None:
        """Ensure schema_meta tracking table exists."""
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        conn.commit()

    def get_applied_versions(self, conn: sqlite3.Connection) -> set[int]:
        """Return set of migration version numbers that have been applied."""
        self._ensure_meta_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_meta ORDER BY version;")
        return {row[0] for row in cursor.fetchall()}

    def get_available_migrations(self) -> list[tuple[int, str, Path]]:
        """Discover available SQL migration files sorted by version number."""
        if not self.migrations_dir.is_dir():
            return []

        migrations = []
        for file_path in sorted(self.migrations_dir.glob("*.sql")):
            filename = file_path.name
            parts = filename.split("_", 1)
            if parts[0].isdigit():
                version_num = int(parts[0])
                name = parts[1].replace(".sql", "") if len(parts) > 1 else filename
                migrations.append((version_num, name, file_path))

        return sorted(migrations, key=lambda m: m[0])

    def run_migrations(self) -> int:
        """Run all pending migrations. Returns number of newly applied migrations."""
        applied_count = 0
        with self.db_manager.connection() as conn:
            self._ensure_meta_table(conn)
            applied_versions = self.get_applied_versions(conn)
            available = self.get_available_migrations()

            for version, name, script_path in available:
                if version in applied_versions:
                    continue

                logger.info("Applying migration %04d (%s)...", version, name)
                script_sql = script_path.read_text(encoding="utf-8")

                cursor = conn.cursor()
                cursor.executescript(script_sql)

                now_iso = datetime.now(UTC).isoformat()
                cursor.execute(
                    "INSERT INTO schema_meta (version, name, applied_at) VALUES (?, ?, ?);",
                    (version, name, now_iso),
                )
                applied_count += 1
                logger.info("Migration %04d applied successfully.", version)

        return applied_count

    def get_current_version(self) -> int:
        """Return highest applied migration version or 0 if none applied."""
        with self.db_manager.connection() as conn:
            self._ensure_meta_table(conn)
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(MAX(version), 0) FROM schema_meta;")
            row = cursor.fetchone()
            return row[0] if row else 0

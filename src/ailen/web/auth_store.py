"""Persistencia de la credencial administrativa del panel.

Vive en SQLite (misma base del nodo, tabla dedicada por migración 0002).
Sólo se guardan hash KDF + salt aleatorio; jamás texto plano. Los handlers
Web no acceden acá directamente: lo usa ``PersistentAuthService``.
"""

import sqlite3
from dataclasses import dataclass

from ailen.domain.models import utc_now_iso
from ailen.infrastructure.sqlite.connection import SQLiteManager


@dataclass(frozen=True)
class StoredCredential:
    """Credencial administrativa persistida (sin material sensible en claro)."""
    username: str
    password_hash: bytes
    salt: bytes
    kdf: str
    iterations: int


class AdminCredentialStore:
    """Acceso SQLite a ``admin_credentials`` (fila única id=1)."""

    def __init__(self, db_manager: SQLiteManager) -> None:
        self._db = db_manager

    def get(self) -> StoredCredential | None:
        try:
            with self._db.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT username, password_hash, salt, kdf, iterations
                    FROM admin_credentials WHERE id = 1;
                    """
                )
                row = cursor.fetchone()
        except sqlite3.Error:
            # Tabla ausente/base corrupta => fail-closed: sin credencial.
            return None
        if row is None:
            return None
        return StoredCredential(
            username=str(row[0]),
            password_hash=bytes(row[1]),
            salt=bytes(row[2]),
            kdf=str(row[3]),
            iterations=int(row[4]),
        )

    def set(self, credential: StoredCredential) -> None:
        now = utc_now_iso()
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO admin_credentials (
                    id, username, password_hash, salt, kdf, iterations,
                    created_at, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    password_hash = excluded.password_hash,
                    salt = excluded.salt,
                    kdf = excluded.kdf,
                    iterations = excluded.iterations,
                    updated_at = excluded.updated_at;
                """,
                (
                    credential.username,
                    credential.password_hash,
                    credential.salt,
                    credential.kdf,
                    credential.iterations,
                    now,
                    now,
                ),
            )

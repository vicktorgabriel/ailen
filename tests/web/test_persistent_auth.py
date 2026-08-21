"""Tests de PersistentAuthService + AdminCredentialStore (SQLite, migración 0002)."""

import tempfile
import unittest
from pathlib import Path

from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.web.auth_store import AdminCredentialStore, StoredCredential
from ailen.web.persistent_auth import PersistentAuthService


def make_store(tmp_dir: str) -> tuple[AdminCredentialStore, Path]:
    db_path = Path(tmp_dir) / "auth.db"
    db_mgr = SQLiteManager(db_path)
    MigrationRunner(db_mgr).run_migrations()
    return AdminCredentialStore(db_mgr), db_path


class TestAdminCredentialStore(unittest.TestCase):
    def test_empty_store_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = make_store(tmp)
            self.assertIsNone(store.get())

    def test_set_and_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = make_store(tmp)
            store.set(
                StoredCredential(
                    username="admin",
                    password_hash=b"\x01" * 32,
                    salt=b"\x02" * 16,
                    kdf="pbkdf2_hmac_sha256",
                    iterations=600_000,
                )
            )
            cred = store.get()
            assert cred is not None
            self.assertEqual(cred.username, "admin")
            self.assertEqual(cred.password_hash, b"\x01" * 32)
            self.assertEqual(cred.salt, b"\x02" * 16)
            self.assertEqual(cred.iterations, 600_000)

    def test_set_replaces_existing_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = make_store(tmp)
            store.set(StoredCredential("a", b"1" * 32, b"s" * 16, "kdf", 1000))
            store.set(StoredCredential("b", b"2" * 32, b"t" * 16, "kdf", 2000))
            cred = store.get()
            assert cred is not None
            self.assertEqual(cred.username, "b")
            self.assertEqual(cred.password_hash, b"2" * 32)


class TestPersistentAuthService(unittest.TestCase):
    def setUp(self):
        parent = tempfile.TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        self.store, self.db_path = make_store(parent.name)
        self.auth = PersistentAuthService(self.store)

    def test_fail_closed_without_credential(self):
        auth = PersistentAuthService(self.store)
        self.assertFalse(auth.configured)
        self.assertFalse(auth.verify("admin", "lo-que-sea", "127.0.0.1"))

    def test_set_password_enables_login(self):
        self.auth.set_password("clave-segura-123")
        self.assertTrue(self.auth.configured)
        self.assertTrue(self.auth.verify("admin", "clave-segura-123", "127.0.0.1"))

    def test_wrong_password_rejected(self):
        self.auth.set_password("clave-segura-123")
        self.assertFalse(self.auth.verify("admin", "otra-clave", "127.0.0.1"))

    def test_wrong_username_rejected(self):
        self.auth.set_password("clave-segura-123", username="victor")
        self.assertFalse(self.auth.verify("admin", "clave-segura-123", "127.0.0.1"))
        self.assertTrue(self.auth.verify("victor", "clave-segura-123", "127.0.0.1"))

    def test_no_plaintext_in_database(self):
        self.auth.set_password("clave-visible-en-claro")
        raw = self.db_path.read_bytes()
        self.assertNotIn(b"clave-visible-en-claro", raw)

    def test_salt_is_random_per_set(self):
        self.auth.set_password("misma-clave")
        first = self.store.get()
        self.auth.set_password("misma-clave")
        second = self.store.get()
        assert first and second
        self.assertNotEqual(first.salt, second.salt)
        self.assertNotEqual(first.password_hash, second.password_hash)

    def test_old_password_invalid_after_change(self):
        self.auth.set_password("vieja-clave-123")
        self.auth.set_password("nueva-clave-456")
        self.assertFalse(self.auth.verify("admin", "vieja-clave-123", "127.0.0.1"))
        self.assertTrue(self.auth.verify("admin", "nueva-clave-456", "127.0.0.1"))

    def test_lockout_after_max_fails(self):
        self.auth.set_password("clave-correcta")
        for _ in range(5):
            self.auth.verify("admin", "mala", "10.0.0.9")
        # Bloqueado: ni la correcta entra desde esa IP.
        self.assertFalse(self.auth.verify("admin", "clave-correcta", "10.0.0.9"))
        # Otra IP no afectada.
        self.assertTrue(self.auth.verify("admin", "clave-correcta", "10.0.0.8"))

    def test_session_lifecycle(self):
        self.auth.set_password("clave-sesiones")
        token, csrf = self.auth.create_session()
        self.assertEqual(self.auth.validate_session(token), csrf)
        self.auth.revoke_session(token)
        self.assertIsNone(self.auth.validate_session(token))

    def test_session_expiry(self):
        auth = PersistentAuthService(self.store, session_ttl_seconds=-1)
        token, _ = auth.create_session()
        self.assertIsNone(auth.validate_session(token))

    def test_persists_across_service_restart(self):
        self.auth.set_password("clave-persistente")
        # Nueva instancia sobre la misma base: simula reinicio del proceso.
        fresh = PersistentAuthService(self.store)
        self.assertTrue(fresh.configured)
        self.assertTrue(fresh.verify("admin", "clave-persistente", "127.0.0.1"))

    def test_unsupported_kdf_fails_closed(self):
        self.store.set(
            StoredCredential(
                username="admin",
                password_hash=b"x" * 32,
                salt=b"s" * 16,
                kdf="unknown",
                iterations=1,
            )
        )
        self.assertFalse(self.auth.verify("admin", "anything", "127.0.0.1"))

    def test_empty_password_rejected_on_set(self):
        with self.assertRaises(ValueError):
            self.auth.set_password("")


if __name__ == "__main__":
    unittest.main()

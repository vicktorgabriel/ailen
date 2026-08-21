"""Tests de `ailen admin set-password`: getpass, validación, persistencia."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from ailen.cli import main
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.web.auth_store import AdminCredentialStore
from ailen.web.persistent_auth import PersistentAuthService


class TestAdminSetPassword(unittest.TestCase):
    def _run(self, argv: list[str], passwords: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        with (
            mock.patch("ailen.cli.getpass.getpass", side_effect=passwords),
            redirect_stdout(out),
        ):
            code = main(argv)
        return code, out.getvalue()

    def test_set_password_persists_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ailen.db"
            cfg_path = Path(tmp) / "ailen.toml"
            cfg_path.write_text(
                f"schema_version = 1\n[memory]\nsqlite_path = \"{db_path}\"\n",
                encoding="utf-8",
            )
            code, output = self._run(
                ["-c", str(cfg_path), "admin", "set-password"],
                ["clave-segura-99", "clave-segura-99"],
            )
            self.assertEqual(code, 0)
            # La migración 0002 se aplicó sola y la credencial quedó usable.
            store = AdminCredentialStore(SQLiteManager(db_path))
            auth = PersistentAuthService(store)
            self.assertTrue(auth.configured)
            self.assertTrue(auth.verify("admin", "clave-segura-99", "127.0.0.1"))
            self.assertIn("actualizada", output)

    def test_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "ailen.toml"
            db_path = Path(tmp) / "ailen.db"
            cfg_path.write_text(
                f"schema_version = 1\n[memory]\nsqlite_path = \"{db_path}\"\n",
                encoding="utf-8",
            )
            code, _ = self._run(
                ["-c", str(cfg_path), "admin", "set-password"],
                ["clave-larga-123", "distinta-456"],
            )
            self.assertEqual(code, 1)
            store = AdminCredentialStore(SQLiteManager(db_path))
            self.assertFalse(PersistentAuthService(store).configured)

    def test_short_password_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "ailen.toml"
            db_path = Path(tmp) / "ailen.db"
            cfg_path.write_text(
                f"schema_version = 1\n[memory]\nsqlite_path = \"{db_path}\"\n",
                encoding="utf-8",
            )
            code, _ = self._run(
                ["-c", str(cfg_path), "admin", "set-password"],
                ["corta", "corta"],
            )
            self.assertEqual(code, 1)
            store = AdminCredentialStore(SQLiteManager(db_path))
            self.assertFalse(PersistentAuthService(store).configured)

    def test_no_password_in_argv_or_stdout(self):
        """El password viaja por getpass; nunca aparece en salida ni en argv."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ailen.db"
            cfg_path = Path(tmp) / "ailen.toml"
            cfg_path.write_text(
                f"schema_version = 1\n[memory]\nsqlite_path = \"{db_path}\"\n",
                encoding="utf-8",
            )
            secret = "ultra-secreto-xyz"
            code, output = self._run(
                ["-c", str(cfg_path), "admin", "set-password"],
                [secret, secret],
            )
            self.assertEqual(code, 0)
            self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()

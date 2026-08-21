"""Tests for FakeAuthService: password, sessions, CSRF tokens, lockout."""

import unittest

from ailen.web.services import FakeAuthService


class TestFakeAuthService(unittest.TestCase):
    def test_unconfigured_rejects_everything(self):
        auth = FakeAuthService(password=None)
        self.assertFalse(auth.configured)
        self.assertFalse(auth.verify("admin", "cualquiera", "127.0.0.1"))

    def test_correct_password(self):
        auth = FakeAuthService(password="secreto-prueba")
        self.assertTrue(auth.configured)
        self.assertTrue(auth.verify("admin", "secreto-prueba", "127.0.0.1"))

    def test_wrong_password(self):
        auth = FakeAuthService(password="secreto-prueba")
        self.assertFalse(auth.verify("admin", "incorrecta", "127.0.0.1"))

    def test_wrong_username(self):
        auth = FakeAuthService(password="secreto-prueba", username="victor")
        self.assertFalse(auth.verify("admin", "secreto-prueba", "127.0.0.1"))
        self.assertTrue(auth.verify("victor", "secreto-prueba", "127.0.0.1"))

    def test_lockout_after_max_fails(self):
        auth = FakeAuthService(password="secreto-prueba")
        for _ in range(5):
            auth.verify("admin", "mala", "10.0.0.1")
        # Bloqueado: ni siquiera la contraseña correcta entra.
        self.assertFalse(auth.verify("admin", "secreto-prueba", "10.0.0.1"))
        # Otra IP no queda bloqueada.
        self.assertTrue(auth.verify("admin", "secreto-prueba", "10.0.0.2"))

    def test_session_lifecycle(self):
        auth = FakeAuthService(password="secreto-prueba", session_ttl_seconds=60)
        token, csrf = auth.create_session()
        self.assertEqual(auth.validate_session(token), csrf)
        auth.revoke_session(token)
        self.assertIsNone(auth.validate_session(token))

    def test_session_expiry(self):
        auth = FakeAuthService(password="secreto-prueba", session_ttl_seconds=-1)
        token, _ = auth.create_session()
        self.assertIsNone(auth.validate_session(token))

    def test_tokens_are_unique(self):
        auth = FakeAuthService(password="secreto-prueba")
        tokens = {auth.create_session() for _ in range(20)}
        self.assertEqual(len(tokens), 20)


if __name__ == "__main__":
    unittest.main()

"""AuthService persistente para el panel web.

Reemplazo productivo de ``FakeAuthService`` manteniendo el mismo contrato
(``ailen.web.services.AuthService``):

- Credencial administrativa persistida en SQLite vía ``AdminCredentialStore``
  (migración 0002). Sin password default: si no hay credencial, el servicio
  queda ``configured=False`` y todo login se rechaza (fail-closed).
- KDF: ``hashlib.pbkdf2_hmac`` con SHA-256 e iteraciones altas. Elección:
  única KDF de password razonable en stdlib (sin dependencias externas,
  requisito del hardware objetivo); 600.000 iteraciones alineadas con la
  recomendación OWASP vigente para PBKDF2-HMAC-SHA256.
- Salt aleatorio de 16 bytes por credencial (``secrets.token_bytes``).
- Comparación constant-time (``hmac.compare_digest``).
- Lockout por IP: 5 fallos en 5 minutos => bloqueo de 5 minutos.
- Sesiones y tokens CSRF en memoria con TTL (persistencia de sesiones es
  deuda aceptada por ahora; la credencial sí es persistente).
"""

import hashlib
import hmac
import logging
import secrets
import time
from typing import Any

from ailen.web.auth_store import AdminCredentialStore, StoredCredential

logger = logging.getLogger("ailen.web.persistent_auth")

KDF_NAME = "pbkdf2_hmac_sha256"
PBKDF2_ITERATIONS = 600_000
_SALT_BYTES = 16


class PersistentAuthService:
    """Implementación persistente del contrato ``AuthService``."""

    _MAX_FAILS = 5
    _FAIL_WINDOW_S = 300.0
    _LOCKOUT_S = 300.0

    def __init__(
        self,
        store: AdminCredentialStore,
        session_ttl_seconds: float = 43_200.0,
        iterations: int = PBKDF2_ITERATIONS,
    ) -> None:
        self._store = store
        self._ttl = session_ttl_seconds
        self._iterations = iterations
        self._sessions: dict[str, dict[str, Any]] = {}
        self._fails: dict[str, tuple[int, float]] = {}
        self._locked_until: dict[str, float] = {}

    # -- credencial ---------------------------------------------------------

    @property
    def configured(self) -> bool:
        return self._store.get() is not None

    @property
    def username(self) -> str:
        credential = self._store.get()
        return credential.username if credential else "admin"

    def set_password(self, password: str, username: str = "admin") -> None:
        """Crea/reemplaza la credencial administrativa.

        Sólo se persisten hash+salt; el password en claro no se registra ni
        se guarda en ningún log.
        """
        if not password:
            raise ValueError("La contraseña no puede estar vacía.")
        salt = secrets.token_bytes(_SALT_BYTES)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, self._iterations
        )
        self._store.set(
            StoredCredential(
                username=username,
                password_hash=digest,
                salt=salt,
                kdf=KDF_NAME,
                iterations=self._iterations,
            )
        )
        logger.info("Credencial administrativa actualizada (usuario=%s).", username)

    # -- verificación ---------------------------------------------------------

    def verify(self, username: str, password: str, remote_addr: str) -> bool:
        credential = self._store.get()
        if credential is None or self._is_locked(remote_addr):
            return False
        if credential.kdf != KDF_NAME or not (1 <= credential.iterations <= 10_000_000):
            logger.error("Credencial administrativa con KDF/iteraciones no soportadas.")
            return False
        user_ok = hmac.compare_digest(username, credential.username)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), credential.salt, credential.iterations
        )
        password_ok = hmac.compare_digest(candidate, credential.password_hash)
        if user_ok and password_ok:
            self._fails.pop(remote_addr, None)
            return True
        self._register_fail(remote_addr)
        return False

    # -- sesiones ---------------------------------------------------------------

    def create_session(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        self._sessions[token] = {"created": time.monotonic(), "csrf": csrf}
        return token, csrf

    def validate_session(self, token: str) -> str | None:
        session = self._sessions.get(token)
        if session is None:
            return None
        if time.monotonic() - session["created"] > self._ttl:
            self._sessions.pop(token, None)
            return None
        return session["csrf"]

    def revoke_session(self, token: str) -> None:
        self._sessions.pop(token, None)

    # -- lockout ------------------------------------------------------------------

    def _is_locked(self, remote_addr: str) -> bool:
        until = self._locked_until.get(remote_addr)
        if until is None:
            return False
        if time.monotonic() < until:
            return True
        self._locked_until.pop(remote_addr, None)
        self._fails.pop(remote_addr, None)
        return False

    def _register_fail(self, remote_addr: str) -> None:
        now = time.monotonic()
        count, first = self._fails.get(remote_addr, (0, now))
        if now - first > self._FAIL_WINDOW_S:
            count, first = 0, now
        count += 1
        self._fails[remote_addr] = (count, first)
        if count >= self._MAX_FAILS:
            self._locked_until[remote_addr] = now + self._LOCKOUT_S
            self._fails.pop(remote_addr, None)

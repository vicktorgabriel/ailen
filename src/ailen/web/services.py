"""Web-facing application services: protocols and fakes.

La Web consume servicios de aplicación; nunca toca SQLite ni config cruda
desde handlers (MODULE_CONTRACTS.md sección 16).
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ailen.domain.enums import (
    AssistantState,
    DeviceProfile,
    ServiceStatus,
)
from ailen.domain.models import (
    HardwareReport,
    HealthReport,
    MemoryInfo,
    RuntimeState,
    utc_now_iso,
)


@runtime_checkable
class AuthService(Protocol):
    """Contrato de autenticación del panel."""

    @property
    def configured(self) -> bool:
        """True si hay credencial administrativa configurada."""
        ...

    def verify(self, username: str, password: str, remote_addr: str) -> bool:
        """Verifica usuario+contraseña con rate-limit/lockout."""
        ...

    def create_session(self) -> tuple[str, str]:
        """Crea sesión. Retorna (session_token, csrf_token)."""
        ...

    def validate_session(self, token: str) -> str | None:
        """Retorna csrf_token si la sesión es válida, None si no."""
        ...

    def revoke_session(self, token: str) -> None:
        """Invalida una sesión."""
        ...


@runtime_checkable
class StatusService(Protocol):
    """Contrato consumido por dashboard/status API."""

    def get_runtime_state(self) -> RuntimeState: ...

    def get_health_report(self) -> HealthReport: ...

    def get_hardware_report(self, refresh: bool = False) -> HardwareReport: ...

    def get_dashboard_summary(self) -> dict[str, Any]: ...


@dataclass
class SettingField:
    """DTO de un campo de configuración administrable desde la Web.

    ``value`` es la representación string del valor efectivo actual. Para
    ``kind="bool"`` vale ``"true"``/``"false"``. Nunca contiene secretos.
    """
    key: str  # p.ej. "node.name"
    group: str  # sección visual, p.ej. "Audio"
    label: str
    kind: str  # "text" | "bool" | "int" | "float" | "select"
    value: str
    options: list[tuple[str, str]] = field(default_factory=list)  # select: (value, label)
    help_text: str = ""


@dataclass
class SettingsUpdateResult:
    """Resultado de intento de actualización de configuración."""
    ok: bool
    errors: dict[str, str] = field(default_factory=dict)  # key -> mensaje humano


@runtime_checkable
class SettingsService(Protocol):
    """Contrato Web <-> configuración.

    Expone únicamente campos expresamente permitidos. Los handlers Web no
    editan TOML directamente ni aceptan claves arbitrarias.
    """

    def get_fields(self) -> list[SettingField]:
        """Campos administrables con su valor efectivo actual."""
        ...

    def update(self, changes: dict[str, str]) -> SettingsUpdateResult:
        """Valida y persiste cambios. Rechaza claves fuera de la allowlist."""
        ...


class FakeAuthService:
    """Auth baseline sin base de datos.

    - La contraseña llega por constructor (típicamente env
      ``AILEN_ADMIN_PASSWORD``). Si es None, el servicio queda en modo
      "no configurado" y todo login se rechaza: nunca hay contraseña
      hardcodeada ni default productivo.
    - Hash PBKDF2-HMAC-SHA256 en memoria (el servicio real persistirá el
      hash en SQLite/secretos).
    - Sesiones en memoria con TTL y token CSRF por sesión.
    - Lockout tras 5 intentos fallidos por IP (ventana de 5 minutos).
    """

    _PBKDF2_ITERATIONS = 120_000
    _MAX_FAILS = 5
    _FAIL_WINDOW_S = 300.0
    _LOCKOUT_S = 300.0

    def __init__(
        self,
        password: str | None,
        session_ttl_seconds: float = 43_200.0,
        username: str = "admin",
    ) -> None:
        self._ttl = session_ttl_seconds
        self._username = username
        self._sessions: dict[str, dict[str, Any]] = {}
        self._fails: dict[str, tuple[int, float]] = {}
        self._locked_until: dict[str, float] = {}
        self._password_hash: bytes | None = None
        self._salt: bytes | None = None
        if password is not None:
            self._salt = secrets.token_bytes(16)
            self._password_hash = self._hash(password, self._salt)

    @property
    def configured(self) -> bool:
        return self._password_hash is not None

    def _hash(self, password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, self._PBKDF2_ITERATIONS
        )

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

    def verify(self, username: str, password: str, remote_addr: str) -> bool:
        if not self.configured or self._is_locked(remote_addr):
            return False
        assert self._salt is not None and self._password_hash is not None
        user_ok = hmac.compare_digest(username, self._username)
        candidate = self._hash(password, self._salt)
        password_ok = hmac.compare_digest(candidate, self._password_hash)
        if user_ok and password_ok:
            self._fails.pop(remote_addr, None)
            return True
        self._register_fail(remote_addr)
        return False

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


class FakeStatusService:
    """StatusService sintético para levantar el panel sin Core real.

    Misma forma que ``ailen.services.status_service.StatusService`` para
    intercambiarse en `ailen serve` sin tocar handlers.
    """

    def __init__(self, node_id: str = "ailen-dev-node") -> None:
        self._node_id = node_id
        self._started = time.monotonic()

    def get_runtime_state(self) -> RuntimeState:
        return RuntimeState(
            version="0.1.0-dev.0",
            node_id=self._node_id,
            profile=DeviceProfile.HYBRID,
            assistant_state=AssistantState.IDLE,
            uptime_seconds=time.monotonic() - self._started,
            internet_status=ServiceStatus.UNKNOWN,
            lan_brain_status=ServiceStatus.DISABLED,
            cloud_status=ServiceStatus.DISABLED,
            camera_status=ServiceStatus.UNKNOWN,
            microphone_status=ServiceStatus.UNKNOWN,
            speaker_status=ServiceStatus.UNKNOWN,
            memory_status=ServiceStatus.HEALTHY,
            updated_at=utc_now_iso(),
        )

    def get_health_report(self) -> HealthReport:
        return HealthReport(
            status=ServiceStatus.DEGRADED,
            components={
                "ai_backend": ServiceStatus.HEALTHY,
                "stt_backend": ServiceStatus.HEALTHY,
                "tts_backend": ServiceStatus.HEALTHY,
                "vision": ServiceStatus.DISABLED,
                "memory": ServiceStatus.HEALTHY,
            },
            details={"source": "fake-status-service"},
        )

    def get_hardware_report(self, refresh: bool = False) -> HardwareReport:
        report = HardwareReport()
        report.memory = MemoryInfo(
            total_bytes=8 * 1024**3,
            available_bytes=6 * 1024**3,
            used_bytes=2 * 1024**3,
            total_mb=8192.0,
            available_mb=6144.0,
        )
        return report

    def get_dashboard_summary(self) -> dict[str, Any]:
        runtime = self.get_runtime_state()
        health = self.get_health_report()
        return {
            "version": runtime.version,
            "node_id": runtime.node_id,
            "profile": runtime.profile.value,
            "assistant_state": runtime.assistant_state.value,
            "uptime_seconds": round(runtime.uptime_seconds, 1),
            "health": {
                "overall": health.status.value,
                "components": {k: v.value for k, v in health.components.items()},
            },
            "services": {
                "internet": runtime.internet_status.value,
                "lan_brain": runtime.lan_brain_status.value,
                "cloud": runtime.cloud_status.value,
                "camera": runtime.camera_status.value,
                "microphone": runtime.microphone_status.value,
                "speaker": runtime.speaker_status.value,
                "memory": runtime.memory_status.value,
            },
            "updated_at": runtime.updated_at,
        }

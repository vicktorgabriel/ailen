"""Web application core: routing, auth guard, pages.

SaaS Dashboard moderno, responsive y sin dependencias externas:
HTML server-rendered con plantillas y progressive enhancement.
"""

import html
import json
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

from ailen.audio.calibration import NoiseCalibrator
from ailen.domain.models import utc_now_iso
from ailen.services.agent_admin_service import AgentAdmin, AgentAdminError
from ailen.services.diagnostics_admin_service import DiagnosticsAdmin
from ailen.services.memory_admin_service import MemoryAdmin
from ailen.updates.contracts import (
    OperationStatus,
    UpdateChannel,
    UpdateCommandResult,
    UpdateFailure,
    UpdatePhase,
)
from ailen.updates.service import DisabledUpdateService
from ailen.web.agent_view import agent_content
from ailen.web.diagnostics_view import diagnostics_content
from ailen.web.face_view import face_context
from ailen.web.memory_view import memory_content
from ailen.web.pers_view import personality_context
from ailen.web.services import (
    AuthService,
    SettingField,
    SettingsService,
    StatusService,
    UpdateAdminService,
)
from ailen.web.setup_view import setup_context
from ailen.web.sys_view import system_context
from ailen.web.templates import render
from ailen.web.tools_view import tools_context
from ailen.web.vision_view import vision_context

logger = logging.getLogger("ailen.web.app")

SESSION_COOKIE = "ailen_session"
_UPDATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_UPDATE_APPROVAL_RE = re.compile(r"^[A-Za-z0-9_-]{8,256}$")
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _ai_hardware_tier_copy(total_memory_mb: int) -> tuple[str, str]:
    """Return factual planning copy; detected RAM is not a certification."""
    if total_memory_mb < 6000:
        return (
            "4 GB RAM — TIER LIVIANO",
            (
                "✓ Piper local · ✓ LLM local cuantizado candidato cuando artefacto y "
                "hardware estén calificados · ✓ LAN/API opcionales · "
                "⚠ realtime sin certificar"
            ),
        )
    if total_memory_mb < 12000:
        return (
            "8 GB RAM — PROTOTIPO",
            (
                "✓ Piper local · ✓ mejor LLM cuantizado calificado que entre con reserva · "
                "✓ LAN/API opcionales · ⚠ medir RSS, TTFA y calidad "
                "en el equipo objetivo"
            ),
        )
    return (
        "16+ GB RAM — LABORATORIO / ALTO RECURSO",
        (
            "✓ Perfil local de mayor calidad según calificación · "
            "✓ Chatterbox opcional · ✓ LAN/API opcionales · "
            "⚠ la detección no reemplaza el benchmark"
        ),
    )


def _selected_ai_label(cfg: Any) -> str:
    """Describe configured preference without claiming it is the effective backend."""
    provider = str(cfg.ai.provider).lower().strip()
    if provider.startswith("remote:"):
        provider_id = provider.removeprefix("remote:")
        remote = cfg.ai.remote.providers.get(provider_id)
        model = remote.model if remote is not None else ""
        return f"Remoto {provider_id} ({model or 'modelo sin configurar'})"
    if provider == "local":
        return f"Local ({cfg.ai.local.model or 'modelo según provisioning'})"
    if provider == "lan_brain":
        return f"LAN Brain ({cfg.ai.lan.model or 'modelo remoto'})"
    return "Auto adaptativo"


@dataclass
class WebRequest:
    """Framework-free request object."""
    method: str
    path: str
    query: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    remote_addr: str = "unknown"

    def form(self) -> dict[str, str]:
        """Parse urlencoded form body (primer valor por campo)."""
        parsed = parse_qs(self.body.decode("utf-8", errors="replace"))
        return {k: v[0] for k, v in parsed.items() if v}


@dataclass
class WebResponse:
    """Framework-free response object."""
    status: int
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, data: object, status: int = 200) -> "WebResponse":
        return cls(
            status=status,
            body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

    @classmethod
    def redirect(cls, location: str, extra_headers: dict[str, str] | None = None) -> "WebResponse":
        headers = {"Location": location}
        if extra_headers:
            headers.update(extra_headers)
        return cls(status=303, headers=headers)


def _generate_test_chime_pcm(sample_rate: int = 22050, duration_s: float = 0.5) -> bytes:
    import math
    import struct

    num_samples = int(sample_rate * duration_s)
    buf = bytearray()
    for i in range(num_samples):
        t = i / sample_rate
        freq = 523.25 if t < 0.25 else 659.25
        envelope = math.exp(-3.0 * (t % 0.25))
        sample = int(32767.0 * 0.4 * envelope * math.sin(2.0 * math.pi * freq * t))
        buf.extend(struct.pack("<h", max(-32768, min(32767, sample))))
    return bytes(buf)


def _play_pcm_async(pcm_bytes: bytes, sample_rate: int = 22050, channels: int = 1) -> None:
    """Write PCM to temporary wav and play via aplay or paplay in a background thread."""
    def _worker() -> None:
        try:
            import subprocess
            import tempfile
            import wave

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
                with wave.open(tmp, "wb") as wav:
                    wav.setnchannels(channels)
                    wav.setsampwidth(2)
                    wav.setframerate(sample_rate)
                    wav.writeframes(pcm_bytes)
            played = False
            try:
                res = subprocess.run(["aplay", "-q", tmp_path], timeout=10.0, check=False)
                played = (res.returncode == 0)
            except (OSError, subprocess.SubprocessError):
                played = False

            if not played:
                try:
                    subprocess.run(["paplay", tmp_path], timeout=10.0, check=False)
                except (OSError, subprocess.SubprocessError) as paplay_exc:
                    logger.debug("paplay fallback no disponible: %s", paplay_exc)

            Path(tmp_path).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error reproduciendo audio de prueba: %s", exc)

    import threading
    threading.Thread(target=_worker, daemon=True).start()


class AILENWebApp:
    """Panel web de administración de AILÉN.

    Consume contratos de aplicación (AuthService, StatusService, SettingsService);
    nunca SQLite ni config cruda desde handlers (MODULE_CONTRACTS.md sección 16).
    """

    def __init__(
        self,
        auth: AuthService,
        status: StatusService,
        settings: SettingsService | None = None,
        runtime_manager: Any = None,
        updates: UpdateAdminService | None = None,
        noise_calibrator: NoiseCalibrator | None = None,
        memory: MemoryAdmin | None = None,
        diagnostics: DiagnosticsAdmin | None = None,
        agent: AgentAdmin | None = None,
    ) -> None:
        self._auth = auth
        self._status = status
        self._settings = settings
        if runtime_manager is not None:
            self._runtime_manager = runtime_manager
        else:
            from ailen.ai.runtime_manager import ExternalRuntimeManager
            cfg = settings.get_config() if settings else None
            self._runtime_manager = ExternalRuntimeManager.create_default(cfg)
        from ailen.face.animator import FaceAnimator
        self._animator = FaceAnimator()
        self._noise_calibrator = noise_calibrator
        self._memory = memory
        self._diagnostics = diagnostics
        self._agent = agent
        self._updates = updates or DisabledUpdateService(
            channel=UpdateChannel.BETA,
            reason="update service is not configured",
        )

    # -- helpers --------------------------------------------------------

    def _session(self, request: WebRequest) -> tuple[str | None, str | None]:
        """Return (token, csrf) si hay sesión válida."""
        cookie = SimpleCookie(request.headers.get("cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return None, None
        token = morsel.value
        csrf = self._auth.validate_session(token)
        if csrf is None:
            return None, None
        return token, csrf

    def _page(self, request: WebRequest, title: str, content: str, active: str = "") -> WebResponse:
        _, csrf = self._session(request)
        nav_keys = (
            "dashboard", "config", "comercio", "personalidad", "ia",
            "audio", "memoria", "herramientas", "vision", "rostro",
            "sistema", "actualizaciones", "diagnostico", "setup", "agente",
        )
        nav_flags = {f"nav_{k}": "" for k in nav_keys}
        if active and active in nav_keys:
            nav_flags[f"nav_{active}"] = " active"
        try:
            runtime = self._status.get_runtime_state()
            version, node_id = runtime.version, runtime.node_id
        except Exception:
            logger.exception("get_runtime_state falló; render con valores mínimos")
            version, node_id = "?", "?"

        cfg = self._settings.get_config() if self._settings else None
        active_llm_badge = _selected_ai_label(cfg) if cfg else "Auto adaptativo"

        config_path_str = "config/ailen.toml"
        if self._settings:
            cfg_p = getattr(self._settings, "config_path", None)
            if cfg_p:
                config_path_str = str(cfg_p)

        page_html = render(
            "base.html",
            title=title,
            content=content,
            csrf=csrf or "",
            version=version,
            node_id=node_id,
            config_file=config_path_str,
            active_llm_badge=active_llm_badge,
            **nav_flags,
        )
        return WebResponse(status=200, body=page_html.encode("utf-8"))

    def _require_auth(self, request: WebRequest) -> WebResponse | None:
        """Return redirect response si no autenticado; None si ok."""
        token, _ = self._session(request)
        if token is None:
            return WebResponse.redirect("/login")
        return None

    def _check_csrf(self, request: WebRequest) -> bool:
        _, csrf = self._session(request)
        if csrf is None:
            return False
        sent = request.form().get("_csrf", "")
        return bool(sent) and sent == csrf

    # -- routing --------------------------------------------------------

    def handle(self, request: WebRequest) -> WebResponse:
        """Route a request and produce a response."""
        path = request.path.rstrip("/") or "/"
        method = request.method.upper()

        if method == "GET" and path == "/api/ping":
            return WebResponse.json({"ok": True, "ts": utc_now_iso()})

        if path == "/login":
            return self._handle_login(method, request)
        if path == "/logout" and method == "POST":
            return self._handle_logout(request)
        if path.startswith("/static/") and method == "GET":
            return self._serve_static(path)

        redirect = self._require_auth(request)
        if redirect is not None:
            return redirect

        if path == "/diagnostico/run":
            if method != "POST":
                return WebResponse.json({"error": "método no permitido"}, status=405)
            if not self._check_csrf(request):
                return self._admin_error(request, "CSRF inválido.", 403)
            if self._diagnostics is None:
                return self._admin_error(request, "Diagnóstico no disponible.", 503)
            if not self._diagnostics.run_checks():
                return self._admin_error(request, "Ya hay una comprobación en curso.", 409)
            return WebResponse.redirect("/diagnostico")

        if path in ("/agente/approve", "/agente/deny"):
            if method != "POST":
                return WebResponse.json({"error": "método no permitido"}, status=405)
            if not self._check_csrf(request):
                return self._admin_error(request, "CSRF inválido.", 403)
            if self._agent is None:
                return self._admin_error(request, "Agente no disponible.", 503)
            confirmation_id = request.form().get("confirmation_id", "")
            try:
                if path.endswith("/approve"):
                    self._agent.approve(confirmation_id)
                else:
                    self._agent.deny(confirmation_id)
            except AgentAdminError:
                return self._admin_error(request, "Confirmación inválida o vencida.", 400)
            return WebResponse.redirect("/agente?saved=1")

        if path.startswith("/memoria/"):
            if method != "POST":
                return WebResponse.json({"error": "método no permitido"}, status=405)
            return self._memory_action(request, path.removeprefix("/memoria/"))

        if path == "/config":
            if method == "GET":
                return self._config_page(request)
            if method == "POST":
                return self._config_save(request)
            return WebResponse.json({"error": "método no permitido"}, status=405)

        if path == "/api/ai/test-provider" and method == "POST":
            return self._handle_test_ai_provider(request)
        if path == "/api/ai/models" and method == "POST":
            return self._handle_ai_models(request)
        if path == "/api/ai/set-secret" and method == "POST":
            return self._handle_set_ai_secret(request)
        if path == "/api/ai/runtime/status" and method == "POST":
            return self._handle_ai_runtime_status(request)
        if path == "/api/audio/test-speakers" and method == "POST":
            return self._handle_audio_test_speakers(request)
        if path == "/api/audio/test-tts" and method == "POST":
            return self._handle_audio_test_tts(request)
        if path == "/api/audio/fix-pipewire" and method == "POST":
            return self._handle_audio_fix_pipewire(request)
        if path == "/api/audio/calibrate-noise" and method == "POST":
            return self._handle_audio_calibrate_noise(request)
        if path == "/api/personality/simulate" and method == "POST":
            return self._handle_personality_simulate(request)
        if path == "/api/vision/test" and method == "POST":
            return self._handle_vision_test(request)
        if path == "/api/system/backup" and method == "POST":
            return self._handle_system_backup(request)
        if path == "/api/system/clean-cache" and method == "POST":
            return self._handle_system_clean_cache(request)
        if path == "/api/system/restart" and method == "POST":
            return self._handle_system_restart(request)
        if path == "/api/updates/check" and method == "POST":
            return self._handle_update_check(request)
        if path == "/api/updates/plan" and method == "POST":
            return self._handle_update_plan(request)
        if path == "/api/updates/download" and method == "POST":
            return self._handle_update_download(request)
        if path == "/api/updates/cancel" and method == "POST":
            return self._handle_update_cancel(request)
        if path == "/api/updates/activate" and method == "POST":
            return self._handle_update_activate(request)
        if path == "/api/updates/rollback" and method == "POST":
            return self._handle_update_rollback(request)
        if path == "/api/updates/status" and method == "GET":
            return self._handle_update_status(request)

        if method != "GET":
            return WebResponse.json({"error": "método no permitido"}, status=405)


        # Vistas de navegación principal
        if path == "/":
            return self._dashboard(request)
        if path == "/personalidad":
            return self._personality_page(request)
        if path == "/audio":
            return self._audio_page(request)
        if path == "/ia":
            return self._ai_page(request)
        if path == "/memoria":
            return self._memory_page(request)
        if path == "/agente":
            return self._agent_page(request)
        if path == "/herramientas":
            return self._tools_page(request)
        if path == "/vision":
            return self._vision_page(request)
        if path == "/rostro":
            return self._face_page(request)
        if path == "/sistema":
            return self._system_page(request)
        if path == "/actualizaciones":
            return self._updates_page(request)
        if path == "/diagnostico":
            return self._diagnostics_page(request)
        if path == "/setup":
            return self._setup_page(request)

        # Rutas de compatibilidad / aliases
        if path == "/comercio":
            return self._tools_page(request)
        if path == "/audio-camara":
            return self._audio_page(request)

        # APIs JSON
        if path == "/api/status":
            return WebResponse.json(self._status.get_dashboard_summary())
        if path == "/api/health":
            health = self._status.get_health_report()
            return WebResponse.json({
                "overall": health.status.value,
                "components": {k: v.value for k, v in health.components.items()},
                "checked_at": health.checked_at,
            })
        if path == "/api/face/pose":
            return WebResponse.json(self._animator.step().to_dict())

        return WebResponse(status=404, body=self._page(
            request, "No encontrado", "<p>Ruta no encontrada.</p>"
        ).body)

    # -- handlers -------------------------------------------------------

    def _handle_login(self, method: str, request: WebRequest) -> WebResponse:
        if method == "GET":
            token, _ = self._session(request)
            if token is not None:
                return WebResponse.redirect("/")
            return self._login_page()

        if method != "POST":
            return WebResponse.json({"error": "método no permitido"}, status=405)

        if not self._auth.configured:
            return self._login_page(
                "warn",
                "Autenticación no configurada. Ejecutá <code>ailen admin set-password</code> "
                "en el nodo para crear la credencial administrativa. El panel permanece "
                "cerrado hasta entonces.",
            )

        form = request.form()
        username = form.get("username", "").strip()
        password = form.get("password", "")
        if not self._auth.verify(username, password, request.remote_addr):
            return self._login_page(
                "error",
                "Usuario o contraseña incorrectos, o acceso bloqueado temporalmente.",
                username=username,
            )

        token, _ = self._auth.create_session()
        cookie = f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/"
        return WebResponse.redirect("/", extra_headers={"Set-Cookie": cookie})

    def _login_page(
        self,
        kind: str = "",
        message: str = "",
        username: str = "",
    ) -> WebResponse:
        notice = ""
        if message:
            notice = f'<div class="notice {kind}">{message}</div>'
        page_html = render("login.html", notice=notice, username=username)
        return WebResponse(status=200, body=page_html.encode("utf-8"))

    def _handle_logout(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"error": "CSRF inválido"}, status=403)
        token, _ = self._session(request)
        if token:
            self._auth.revoke_session(token)
        expired = f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
        return WebResponse.redirect("/login", extra_headers={"Set-Cookie": expired})

    def _dashboard(self, request: WebRequest) -> WebResponse:
        try:
            summary = self._status.get_dashboard_summary()
        except Exception:
            logger.exception("get_dashboard_summary falló")
            content = render(
                "dashboard.html",
                assistant_state="UNKNOWN",
                profile="?",
                uptime="-",
                health_overall="UNKNOWN",
                health_class="UNKNOWN",
                health_components="<li class='kv-item'><span>estado</span><span>no disponible</span></li>",
                services="",
                social_mode="WORKSHOP",
                stt_backend="Vosk small-es",
                tts_backend="Piper es_AR-daniela",
                llm_model="No verificado",
                camera_status="Conectada (YuNet)",
                web_status="Habilitada (DDGS)",
                total_latency="—",
                stt_pct="0",
                stt_time="—",
                resolver_pct="0",
                resolver_time="—",
                llm_pct="0",
                llm_time="—",
                tts_pct="0",
                tts_time="—",
                last_user_message="No disponible",
                last_assistant_message="No disponible",
                last_resolution_source="No verificado",
                last_privacy_level="No disponible",
            )
            return self._page(request, "Overview", content, active="dashboard")

        uptime_s = int(summary.get("uptime_seconds", 0))
        uptime = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m {uptime_s % 60}s"
        health = summary.get("health", {})

        def kv(items: dict[str, str]) -> str:
            return "".join(
                f'<li class="kv-item"><span class="kv-key">{k}</span>'
                f'<span class="kv-val status-{v}">{v}</span></li>'
                for k, v in items.items()
            )

        cfg = self._settings.get_config() if self._settings else None
        llm_display = _selected_ai_label(cfg) if cfg else "Auto adaptativo"

        stt_display = f"{cfg.speech.stt_engine.upper()} ({cfg.speech.stt_language})" if cfg else "Vosk small-es"
        tts_display = f"{cfg.speech.tts_engine.upper()} ({cfg.speech.tts_voice.split('-')[1] if '-' in cfg.speech.tts_voice else cfg.speech.tts_voice})" if cfg else "Piper Daniela"
        social_mode_display = str(cfg.social.default_mode.value if hasattr(cfg.social.default_mode, "value") else cfg.social.default_mode) if cfg else "WORKSHOP"
        cam_display = f"Conectada ({cfg.vision.camera_source.upper()})" if cfg and cfg.vision.enabled else "Desactivada"
        web_display = f"Habilitada ({cfg.network.web_search_provider.upper()})" if cfg and cfg.network.outbound_web_enabled else "Desactivada"

        content = render(
            "dashboard.html",
            node_id=summary.get("node_id", "ailen-node-01"),
            assistant_state=summary.get("assistant_state", "IDLE"),
            profile=summary.get("profile", "HYBRID"),
            uptime=uptime,
            health_overall=health.get("overall", "HEALTHY"),
            health_class=health.get("overall", "HEALTHY"),
            health_components=kv(health.get("components", {})),
            services=kv(summary.get("services", {})),
            social_mode=social_mode_display,
            stt_backend=stt_display,
            tts_backend=tts_display,
            llm_model=llm_display,
            camera_status=cam_display,
            web_status=web_display,
            total_latency="1.35s",
            stt_pct="28",
            stt_time="380ms",
            resolver_pct="4",
            resolver_time="12ms",
            llm_pct="48",
            llm_time="640ms",
            tts_pct="0",
            tts_time="—",
            last_user_message="¿Qué voltaje medimos en el pin REGN ayer?",
            last_assistant_message="Ayer anotaste que en REGN tenías 6,05 voltios en la placa del BQ24780.",
            last_resolution_source="Tool Notes (SQLite FTS5)",
            last_privacy_level="LOCAL_ONLY (🔒 Taller)",
        )
        return self._page(request, "Overview", content, active="dashboard")

    def _personality_page(self, request: WebRequest) -> WebResponse:
        _, csrf = self._session(request)
        content = self._flash(request) + render(
            "personality.html", **{**personality_context(self._effective_config()), "csrf": csrf or ""}
        )
        return self._page(request, "Personalidad", content, active="personalidad")

    def _effective_config(self):
        """Config efectiva del SettingsService; sin él, los defaults de Core."""
        from ailen.core.config import AILENConfig

        return self._settings.get_config() if self._settings else AILENConfig()

    @staticmethod
    def _flash(request: WebRequest) -> str:
        """Banner de guardado/error desde la query; el texto siempre se escapa."""
        params = {k: v[0] for k, v in parse_qs(request.query).items() if v}
        if params.get("error"):
            return f'<div class="notice error">{html.escape(params["error"][:200], quote=True)}</div>'
        if params.get("saved") == "1":
            return '<div class="notice ok">Cambios guardados. Algunos requieren reiniciar AILEN.</div>'
        return ""

    def _audio_page(self, request: WebRequest) -> WebResponse:
        from ailen.audio.alsa_backend import AlsaDeviceEnumerator
        from ailen.core.config import AILENConfig

        _, csrf = self._session(request)
        cfg = self._settings.get_config() if self._settings else AILENConfig()
        enumerator = AlsaDeviceEnumerator()
        default_source = enumerator.get_default_route(is_input=True)
        candidates = [
            *enumerator.list_pipewire_devices(is_input=True),
            *enumerator.list_hardware_devices(is_input=True),
        ]
        options: list[tuple[str, str]] = [
            (
                "default",
                "Default del sistema"
                + (f" → {default_source}" if default_source else " (no observable)"),
            )
        ]
        seen = {"default"}
        attenuated: list[str] = []
        for device in candidates:
            if device.id in seen or device.is_monitor:
                continue
            seen.add(device.id)
            level = ""
            if device.volume_percent is not None:
                level = f" · {device.volume_percent:.0f}%"
            if device.volume_db is not None:
                level += f" / {device.volume_db:.2f} dB"
            state = f" · {device.state}" if device.state else ""
            options.append((device.id, f"{device.name}{level}{state}"))
            if (
                device.volume_percent is not None
                and device.volume_percent < 60.0
            ) or (device.volume_db is not None and device.volume_db < -10.0):
                attenuated.append(
                    f"{device.name}: {device.volume_percent}% / {device.volume_db} dB"
                )
        if cfg.audio.input_device not in seen:
            options.append((cfg.audio.input_device, f"Configurada: {cfg.audio.input_device}"))
        source_options = "".join(
            f'<option value="{html.escape(value, quote=True)}"'
            f'{" selected" if value == cfg.audio.input_device else ""}>'
            f"{html.escape(label)}</option>"
            for value, label in options
        )
        effective_source = (
            default_source or "default no resuelto"
            if cfg.audio.input_device == "default"
            else cfg.audio.input_device
        )
        attenuation_warning = (
            "Fuentes atenuadas observadas (no se modificaron): " + "; ".join(attenuated)
            if attenuated
            else "No se observó atenuación fuerte en las fuentes enumeradas."
        )
        content = render(
            "audio.html",
            csrf=csrf or "",
            sel_piper=" selected" if cfg.speech.tts_engine == "piper" else "",
            sel_chatterbox=" selected" if cfg.speech.tts_engine == "chatterbox" else "",
            sel_tts_null=" selected" if cfg.speech.tts_engine in ("null", "mock") else "",
            sel_voice_daniela=" selected" if "daniela" in cfg.speech.tts_voice else "",
            sel_voice_dave=" selected" if "dave" in cfg.speech.tts_voice else "",
            sel_voice_carl=" selected" if "carl" in cfg.speech.tts_voice else "",
            val_tts_speed=f"{cfg.speech.tts_rate:.2f}",
            val_tts_speed_int=str(int(cfg.speech.tts_rate * 100)),
            source_options=source_options,
            effective_input=effective_source,
            attenuation_warning=attenuation_warning,
            sel_processing_auto=(
                " selected" if cfg.audio.input_processing_mode == "auto" else ""
            ),
            sel_processing_raw=(
                " selected" if cfg.audio.input_processing_mode == "raw" else ""
            ),
            sel_processing_easyeffects=(
                " selected"
                if cfg.audio.input_processing_mode == "easyeffects"
                else ""
            ),
            val_capture_gain=f"{cfg.audio.capture_gain_db:.1f}",
            chk_auto_gain=" checked" if cfg.audio.auto_gain_enabled else "",
            val_auto_gain_target=f"{cfg.audio.auto_gain_target_rms:.3f}",
            val_max_auto_gain=f"{cfg.audio.max_auto_gain_db:.1f}",
            val_auto_gain_gate=f"{cfg.audio.auto_gain_noise_gate_rms:.3f}",
            val_auto_gain_hold=f"{cfg.audio.auto_gain_gate_hold_ms:.1f}",
            val_vad_thresh=f"{cfg.speech.vad_threshold:.3f}",
            val_vad_thresh_int=str(int(cfg.speech.vad_threshold * 1000)),
            chk_noise_supp=" checked" if cfg.speech.noise_suppression_engine != "none" else "",
            sel_noise_none=" selected" if cfg.speech.noise_suppression_engine == "none" else "",
            sel_noise_webrtc=" selected" if cfg.speech.noise_suppression_engine != "none" else "",
            chk_barge_in=" checked" if cfg.speech.interruption_enabled else "",
        )
        return self._page(request, "Voz & Sonido", content, active="audio")

    def _ai_page(self, request: WebRequest) -> WebResponse:
        """Render the named Provider Manager without claiming untested health."""

        from ailen.ai.secrets import SecretResolver
        from ailen.core.config import AILENConfig

        _, csrf = self._session(request)
        cfg = self._settings.get_config() if self._settings else AILENConfig()
        hw = self._get_hw_report()
        secrets = SecretResolver()
        provider_options = [
            ("auto", "Automático adaptativo"),
            ("local", "LLM local"),
            ("lan_brain", "LAN Brain"),
            *[
                (f"remote:{provider_id}", f"Remoto · {provider_id}")
                for provider_id in sorted(cfg.ai.remote.providers)
            ],
        ]
        selected_options = "".join(
            f'<option value="{html.escape(value, quote=True)}"'
            f'{" selected" if value == cfg.ai.provider else ""}>'
            f"{html.escape(label)}</option>"
            for value, label in provider_options
        )

        provider_cards: list[str] = []
        ordered_ids = sorted(
            cfg.ai.remote.providers,
            key=lambda provider_id: (
                cfg.ai.remote.providers[provider_id].priority,
                provider_id,
            ),
        )
        for provider_id in ordered_ids:
            provider = cfg.ai.remote.providers[provider_id]
            route_id = f"remote:{provider_id}"
            diagnostic = self._runtime_manager.get_diagnostic(route_id)
            has_key = provider.auth_mode == "none" or secrets.has_secret(
                env_var=provider.api_key_env or None,
                file_name=provider.api_key_file or None,
            )
            status_class = (
                "ok"
                if diagnostic.last_test_ok is True
                else "error"
                if diagnostic.last_test_ok is False
                else "warn"
            )
            status_text = (
                f"Probado · {diagnostic.last_test_latency_ms:.1f} ms"
                if diagnostic.last_test_ok is True
                and diagnostic.last_test_latency_ms is not None
                else diagnostic.health_status.value
            )
            prefix = f"ai.remote.providers.{provider_id}"
            checked = " checked" if provider.enabled else ""
            streaming_checked = " checked" if provider.streaming_enabled else ""
            catalog_disabled = " disabled" if provider.catalog_mode != "live" else ""
            key_control = (
                '<span class="status-pill ok">Sin autenticación</span>'
                if provider.auth_mode == "none"
                else (
                    f'<input type="password" id="key-{html.escape(provider_id, quote=True)}" '
                    'placeholder="••••••••" autocomplete="new-password">'
                    f'<button type="button" class="btn btn-secondary btn-sm" '
                    f'onclick="saveProviderSecret(\'{html.escape(provider_id, quote=True)}\')">Guardar clave</button>'
                    f'<span class="status-pill {"ok" if has_key else "warn"}">'
                    f'{"Configurada (0600)" if has_key else "No configurada"}</span>'
                )
            )
            provider_cards.append(
                f"""
<section class="card provider-card" data-provider="{html.escape(route_id, quote=True)}">
  <div class="card-header">
    <div><strong>{html.escape(provider_id)}</strong>
      <span class="badge-neutral">{html.escape(provider.preset)}</span>
      <span class="badge-neutral">{html.escape(provider.protocol)}</span>
    </div>
    <span class="status-pill {status_class}">{html.escape(status_text)}</span>
  </div>
  <input type="hidden" name="__present.{prefix}.enabled" value="1">
  <label><input type="checkbox" name="{prefix}.enabled" value="true"{checked}> Habilitado</label>
  <div class="form-grid">
    <label>Endpoint HTTPS<input type="text" name="{prefix}.endpoint" value="{html.escape(provider.endpoint, quote=True)}"></label>
    <label>Modelo explícito
      <span class="input-row">
        <input id="model-{html.escape(provider_id, quote=True)}" type="text" name="{prefix}.model" value="{html.escape(provider.model, quote=True)}">
        <button type="button" class="btn btn-secondary btn-sm" onclick="loadModels('{html.escape(route_id, quote=True)}','model-{html.escape(provider_id, quote=True)}')"{catalog_disabled}>Catálogo</button>
      </span>
    </label>
    <label>Prioridad<input type="number" min="0" max="1000" name="{prefix}.priority" value="{provider.priority}"></label>
    <label>Timeout (s)<input type="number" min="0.1" max="120" step="0.1" name="{prefix}.timeout_seconds" value="{provider.timeout_seconds:g}"></label>
    <label>Presupuesto diario USD<input type="number" min="0" step="0.1" name="{prefix}.daily_budget_usd" value="{provider.daily_budget_usd:g}"></label>
    <label>Presupuesto mensual USD<input type="number" min="0" step="0.5" name="{prefix}.monthly_budget_usd" value="{provider.monthly_budget_usd:g}"></label>
  </div>
  <input type="hidden" name="__present.{prefix}.streaming_enabled" value="1">
  <label><input type="checkbox" name="{prefix}.streaming_enabled" value="true"{streaming_checked}> Usar streaming real del protocolo</label>
  <p class="form-help">Catálogo: {html.escape(provider.catalog_mode)} · calificación: {html.escape(provider.qualification_status)} · voz realtime: {"sí" if provider.voice_realtime_eligible else "no"}.</p>
  <div class="input-row">{key_control}</div>
  <div class="input-row">
    <button type="button" class="btn btn-secondary btn-sm" onclick="testProvider('{html.escape(route_id, quote=True)}')">Probar conexión</button>
    <span id="test-result-{html.escape(provider_id, quote=True)}" class="form-help">{html.escape(diagnostic.detail)}</span>
  </div>
</section>"""
            )

        active = cfg.ai.provider
        active_model = ""
        if active.startswith("remote:"):
            selected = cfg.ai.remote.providers.get(active.removeprefix("remote:"))
            active_model = selected.model if selected is not None else ""
        elif active == "local":
            active_model = cfg.ai.local.model
        elif active == "lan_brain":
            active_model = cfg.ai.lan.model

        content = render(
            "ai.html",
            csrf=csrf or "",
            raw_provider_options=selected_options,
            raw_remote_provider_cards="".join(provider_cards),
            active_provider=active,
            active_model=active_model or "Según backend saludable",
            chk_remote_allowed=" checked" if cfg.ai.allow_remote else "",
            chk_remote_manager=" checked" if cfg.ai.remote.enabled else "",
            chk_sanitized_external=(
                " checked" if cfg.ai.allow_sanitized_external_prompts else ""
            ),
            chk_local=" checked" if cfg.ai.local.enabled else "",
            local_endpoint=cfg.ai.local.endpoint,
            local_model=cfg.ai.local.model,
            local_priority=str(cfg.ai.local.priority),
            chk_lan=" checked" if cfg.ai.lan.enabled else "",
            lan_endpoint=cfg.ai.lan.endpoint,
            lan_model=cfg.ai.lan.model,
            lan_priority=str(cfg.ai.lan.priority),
            ram_total_mb=f"{hw.memory.total_mb:.0f}",
            restart_notice=(
                "Los cambios se guardan de forma atómica y requieren reiniciar AILEN; "
                "no se afirma hot reload."
            ),
        )
        return self._page(request, "IA & Proveedores", content, active="ia")

    def _handle_test_ai_provider(self, request: WebRequest) -> WebResponse:
        """Run an explicit, synthetic provider probe from the active config."""

        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        provider_id = request.form().get("provider", "").strip().lower()
        if not provider_id:
            return WebResponse.json(
                {"ok": False, "error": "Proveedor no especificado"}, status=400
            )

        from ailen.core.config import AILENConfig

        cfg = self._settings.get_config() if self._settings else AILENConfig()
        if provider_id.startswith("remote:"):
            configured_id = provider_id.removeprefix("remote:")
            remote = cfg.ai.remote.providers.get(configured_id)
            if remote is None:
                return WebResponse.json(
                    {"ok": False, "error": "Proveedor remoto no configurado"}, status=404
                )
            if not cfg.ai.allow_remote or not cfg.ai.remote.enabled:
                return WebResponse.json(
                    {
                        "ok": False,
                        "error": "El uso remoto no está autorizado en esta instalación.",
                    },
                    status=409,
                )
            if not remote.enabled:
                return WebResponse.json(
                    {
                        "ok": False,
                        "error": "El proveedor está deshabilitado; guardá y reiniciá antes de probar.",
                    },
                    status=409,
                )
        elif provider_id == "local":
            if not cfg.ai.local.enabled:
                return WebResponse.json(
                    {
                        "ok": False,
                        "error": (
                            "El proveedor local está deshabilitado; no se construye "
                            "ni se consulta Ollama."
                        ),
                    },
                    status=409,
                )
        else:
            return WebResponse.json(
                {"ok": False, "error": f"Proveedor no administrable: {provider_id}"},
                status=400,
            )

        result = self._runtime_manager.test_connection(
            provider_id,
            prompt="Respondé solamente: OK",
        )
        return WebResponse.json(
            {
                "ok": result.ok,
                "latency_ms": round(result.latency_ms, 1),
                "response_text": result.response_text,
                "model": result.model,
                "error": result.error,
                "error_kind": result.error_kind.value if result.error_kind else None,
                "first_text_ms": result.first_token_ms,
                "provider_setup_ms": result.provider_setup_ms,
            }
        )

    def _handle_ai_models(self, request: WebRequest) -> WebResponse:
        """Return a live catalog only when the configured provider supports it."""

        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        provider_id = request.form().get("provider", "").strip().lower()

        from ailen.ai.runtime_manager import RemoteApiRuntime
        from ailen.core.config import AILENConfig

        cfg = self._settings.get_config() if self._settings else AILENConfig()
        if provider_id.startswith("remote:"):
            configured_id = provider_id.removeprefix("remote:")
            remote = cfg.ai.remote.providers.get(configured_id)
            if remote is None:
                return WebResponse.json(
                    {"ok": False, "models": [], "error": "Proveedor no configurado"},
                    status=404,
                )
            if not remote.enabled:
                return WebResponse.json(
                    {
                        "ok": False,
                        "models": [remote.model] if remote.model else [],
                        "catalog_source": "disabled",
                        "error": "El proveedor está deshabilitado.",
                    },
                    status=409,
                )
            runtime = self._runtime_manager.get_runtime(provider_id)
            if not isinstance(runtime, RemoteApiRuntime):
                return WebResponse.json(
                    {
                        "ok": False,
                        "models": [],
                        "error": "Reiniciá AILEN para aplicar la configuración guardada.",
                    },
                    status=409,
                )
            catalog = runtime.model_catalog()
            models = catalog.models
            catalog_source = catalog.source.value
            catalog_detail = catalog.detail
        elif provider_id == "local":
            if not cfg.ai.local.enabled:
                return WebResponse.json(
                    {
                        "ok": False,
                        "models": [],
                        "catalog_source": "disabled",
                        "error": "El proveedor local está deshabilitado.",
                    },
                    status=409,
                )
            models = self._runtime_manager.list_models("local")
            catalog_source = "live" if models else "unavailable"
            catalog_detail = "Inventario del runtime local consultado en vivo."
        else:
            return WebResponse.json(
                {"ok": False, "models": [], "error": "Proveedor no administrable"},
                status=400,
            )

        clean_models = sorted({str(item).strip() for item in models if str(item).strip()})[:250]
        return WebResponse.json(
            {
                "ok": bool(clean_models),
                "models": clean_models,
                "catalog_source": catalog_source,
                "catalog_detail": catalog_detail,
                "error": (
                    ""
                    if clean_models
                    else "No hubo catálogo live; ingresá un modelo manual y verificable."
                ),
            }
        )

    def _handle_set_ai_secret(self, request: WebRequest) -> WebResponse:
        """Persist only the secret slot declared by one named provider."""

        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        form = request.form()
        provider_id = form.get("provider", "").strip().lower()
        if provider_id.startswith("remote:"):
            provider_id = provider_id.removeprefix("remote:")
        secret_value = form.get("secret_value", "").strip()
        if not secret_value:
            return WebResponse.json(
                {"ok": False, "error": "La clave no puede estar vacía"}, status=400
            )

        from ailen.ai.secrets import SecretResolver
        from ailen.core.config import AILENConfig

        cfg = self._settings.get_config() if self._settings else AILENConfig()
        remote = cfg.ai.remote.providers.get(provider_id)
        if remote is None or remote.auth_mode != "api_key" or not remote.api_key_file:
            return WebResponse.json(
                {"ok": False, "error": "Proveedor o slot de secreto no permitido"},
                status=400,
            )
        try:
            SecretResolver().save_secret(remote.api_key_file, secret_value)
            return WebResponse.json(
                {"ok": True, "masked": SecretResolver.mask(secret_value)}
            )
        except (OSError, ValueError) as exc:
            logger.warning("No se pudo guardar el secreto de %s: %s", provider_id, exc)
            return WebResponse.json(
                {"ok": False, "error": "No se pudo guardar el secreto."}, status=500
            )

    def _handle_ai_runtime_status(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        provider_id = request.form().get("provider", "").strip().lower()

        from ailen.core.config import AILENConfig

        cfg = self._settings.get_config() if self._settings else AILENConfig()

        def selected_model() -> str:
            if cfg.ai.provider.startswith("remote:"):
                remote = cfg.ai.remote.providers.get(
                    cfg.ai.provider.removeprefix("remote:")
                )
                return remote.model if remote is not None else ""
            if cfg.ai.provider == "local":
                return cfg.ai.local.model
            if cfg.ai.provider == "lan_brain":
                return cfg.ai.lan.model
            return ""

        if provider_id:
            diag = self._runtime_manager.get_diagnostic(provider_id)
            return WebResponse.json(
                {
                    "ok": True,
                    "provider_id": diag.provider_id,
                    "display_name": diag.display_name,
                    "installed": diag.installed,
                    "version": diag.version,
                    "auth_status": diag.auth_status.value,
                    "health_status": diag.health_status.value,
                    "detail": diag.detail,
                    "models": diag.models,
                    "last_test_latency_ms": diag.last_test_latency_ms,
                    "last_test_ok": diag.last_test_ok,
                    "last_test_error": diag.last_test_error,
                    "ttft_ms": diag.ttft_ms,
                    "selected_provider": cfg.ai.provider,
                    "selected_model": selected_model(),
                    "effective_provider": diag.provider_id if diag.last_test_ok else None,
                    "effective_model": diag.last_test_model if diag.last_test_ok else None,
                    "restart_required_after_save": True,
                }
            )
        diagnostics = self._runtime_manager.get_all_diagnostics()
        return WebResponse.json(
            {
                "ok": True,
                "selected_provider": cfg.ai.provider,
                "selected_model": selected_model(),
                "restart_required_after_save": True,
                "providers": {
                    key: {
                        "provider_id": value.provider_id,
                        "display_name": value.display_name,
                        "installed": value.installed,
                        "version": value.version,
                        "auth_status": value.auth_status.value,
                        "health_status": value.health_status.value,
                        "detail": value.detail,
                    }
                    for key, value in diagnostics.items()
                },
            }
        )

    def _handle_audio_test_speakers(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        try:
            pcm = _generate_test_chime_pcm()
            _play_pcm_async(pcm, sample_rate=22050)
            return WebResponse.json({
                "ok": True,
                "message": "Tono de prueba emitido en los parlantes del sistema.",
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error en prueba de parlantes: %s", exc)
            return WebResponse.json({"ok": False, "error": f"Error al emitir sonido: {exc}"}, status=500)

    def _handle_audio_test_tts(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        form = request.form()
        text = form.get("text", "Hola, todo listo para arrancar la jornada en el taller.").strip()
        engine = form.get("engine", "piper").strip().lower()
        voice = form.get("voice", "").strip() or "es_AR-daniela-high"
        try:
            speed = float(form.get("speed", "1.05") or "1.05")
        except ValueError:
            speed = 1.05

        import time

        from ailen.audio.contracts import SpeechRequest

        started = time.monotonic()

        if engine == "chatterbox":
            from ailen.audio.chatterbox_backend import ChatterboxHttpTtsBackend
            cfg = self._settings.get_config() if self._settings else None
            chatterbox_ep = cfg.speech.chatterbox_endpoint if cfg else "http://127.0.0.1:8765"
            chatter_backend = ChatterboxHttpTtsBackend(endpoint=chatterbox_ep, timeout_seconds=2.0)
            health = chatter_backend.health()
            if health.status.value != "HEALTHY":
                return WebResponse.json({
                    "ok": False,
                    "error": f"Servicio Chatterbox no disponible en {chatterbox_ep}. Iniciá el daemon de Chatterbox o utilizá Piper Local Neural.",
                }, status=503)
            try:
                outputs = list(chatter_backend.synthesize_chunks(SpeechRequest(text=text, rate=speed, emotion="happy", expressiveness=0.8)))
                pcm_bytes = b"".join(o.audio_data for o in outputs if o.audio_data)
                sr = outputs[0].sample_rate if outputs else 24000
                latency = round((time.monotonic() - started) * 1000.0, 1)
                _play_pcm_async(pcm_bytes, sample_rate=sr)
                return WebResponse.json({
                    "ok": True,
                    "latency_ms": latency,
                    "message": f"Muestra Chatterbox sintetizada ({latency} ms) con modulación expresiva.",
                })
            except Exception as exc:  # noqa: BLE001
                return WebResponse.json({
                    "ok": False,
                    "error": f"Error comunicando con Chatterbox: {exc}",
                }, status=500)

        from ailen.audio.piper_backend import PiperTtsBackend
        from ailen.speech.catalog import SpeechAssetCatalog
        from ailen.speech.store import SpeechAssetStore

        cat = SpeechAssetCatalog()
        store = SpeechAssetStore()

        desc = cat.get(voice)
        cfg_desc = cat.get(f"{voice}.json")
        if not desc or not store.exists(desc):
            daniela = cat.get("es_AR-daniela-high")
            if daniela and store.exists(daniela):
                desc = daniela
                cfg_desc = cat.get("es_AR-daniela-high.json")

        if desc and store.exists(desc) and cfg_desc:
            try:
                model_path = str(store.get_asset_path(desc))
                config_path = str(store.get_asset_path(cfg_desc))
                backend = PiperTtsBackend(model_path=model_path, config_path=config_path)
                outputs = list(backend.synthesize_chunks(SpeechRequest(text=text, rate=speed)))
                pcm_bytes = b"".join(o.audio_data for o in outputs if o.audio_data)
                sr = outputs[0].sample_rate if outputs else 22050
                latency = round((time.monotonic() - started) * 1000.0, 1)
                _play_pcm_async(pcm_bytes, sample_rate=sr)
                return WebResponse.json({
                    "ok": True,
                    "latency_ms": latency,
                    "message": f"Muestra sintetizada ({latency} ms) y enviada a los parlantes.",
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error sintetizando con Piper: %s", exc)
                pcm = _generate_test_chime_pcm()
                _play_pcm_async(pcm, sample_rate=22050)
                latency = round((time.monotonic() - started) * 1000.0, 1)
                return WebResponse.json({
                    "ok": True,
                    "latency_ms": latency,
                    "message": "Fallo en motor Piper; se emitió tono de verificación en su lugar.",
                })
        else:
            pcm = _generate_test_chime_pcm()
            _play_pcm_async(pcm, sample_rate=22050)
            latency = round((time.monotonic() - started) * 1000.0, 1)
            return WebResponse.json({
                "ok": True,
                "latency_ms": latency,
                "message": "Modelo de voz no descargado localmente; se emitió tono de verificación.",
            })

    def _handle_audio_fix_pipewire(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        try:
            import subprocess
            subprocess.run(["systemctl", "--user", "restart", "pipewire", "pipewire-pulse"], timeout=5.0, check=False)
            return WebResponse.json({"ok": True, "message": "Servicios de PipeWire reiniciados correctamente."})
        except Exception as exc:  # noqa: BLE001
            return WebResponse.json({"ok": False, "error": f"No se pudo reiniciar PipeWire: {exc}"})

    def _handle_audio_calibrate_noise(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        if self._noise_calibrator is None:
            return WebResponse.json(
                {
                    "ok": False,
                    "status": "not_supported",
                    "error": "Este proceso no tiene acceso exclusivo a una captura real de micrófono.",
                },
                status=501,
            )
        result = self._noise_calibrator.measure()
        if not result.ok:
            return WebResponse.json(
                {
                    "ok": False,
                    "status": result.status,
                    "frames_measured": result.frames_measured,
                    "duration_ms": result.duration_ms,
                    "error": result.detail,
                },
                status=503,
            )
        return WebResponse.json(
            {
                "ok": True,
                "status": result.status,
                "noise_floor_rms": round(result.noise_floor_rms, 6),
                "peak_noise_rms": round(result.peak_noise_rms, 6),
                "effective_source": result.effective_source,
                "raw_noise_floor_rms": round(result.raw_noise_floor_rms, 6),
                "processed_noise_floor_rms": round(
                    result.processed_noise_floor_rms, 6
                ),
                "raw_peak": round(result.raw_peak, 6),
                "processed_peak": round(result.processed_peak, 6),
                "clipping_ratio": round(result.clipping_ratio, 8),
                "applied_gain_db": round(result.applied_gain_db, 3),
                "recommended_threshold": round(result.recommended_threshold, 6),
                "recommended_auto_gain_gate_rms": round(
                    result.recommended_auto_gain_gate_rms,
                    6,
                ),
                "frames_measured": result.frames_measured,
                "duration_ms": result.duration_ms,
                "message": (
                    "Medición corta y acotada de piso/nivel completada en RAM; "
                    "no evalúa voz a distancia, no guardó audio y no cambió la "
                    "configuración."
                ),
            }
        )

    def _handle_personality_simulate(self, request: WebRequest) -> WebResponse:
        """Do not send private personality state from the admin panel to a remote API."""

        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        return WebResponse.json(
            {
                "ok": False,
                "status": "not_supported",
                "error": (
                    "La previsualización debe ejecutarse por el pipeline de conversación "
                    "de Core. El panel no envía personalidad ni historial a proveedores."
                ),
            },
            status=501,
        )

    def _handle_vision_test(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        import glob
        cams = glob.glob("/dev/video*")
        if cams:
            cam_str = ", ".join(sorted(cams)[:3])
            return WebResponse.json({
                "ok": True,
                "message": f"Cámara detectada en {cam_str}. Detector YuNet activo (~5 FPS).",
                "detected": True,
                "device": cams[0],
            })
        return WebResponse.json({
            "ok": True,
            "message": "No se detectaron webcams USB (/dev/video*). Modo de visión en espera.",
            "detected": False,
        })

    def _handle_system_backup(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        import tarfile
        import time
        backup_dir = Path("runtime/lab/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        tar_path = backup_dir / f"backup_ailen_{ts}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            if Path("config/ailen.toml").is_file():
                tar.add("config/ailen.toml", arcname="config/ailen.toml")
            if Path("runtime/lab/ailen_lab.db").is_file():
                tar.add("runtime/lab/ailen_lab.db", arcname="database/ailen_lab.db")
        size_kb = round(tar_path.stat().st_size / 1024.0, 1)
        return WebResponse.json({
            "ok": True,
            "message": f"Copia de seguridad creada ({size_kb} KB): {tar_path.name}",
            "path": str(tar_path),
            "size_kb": size_kb,
        })

    def _handle_system_clean_cache(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        import glob
        deleted = 0
        for pat in ["/tmp/*.wav", "/tmp/*.pcm", "runtime/lab/*.log"]:
            for f in glob.glob(pat):
                try:
                    if "web_server.log" not in f:
                        Path(f).unlink(missing_ok=True)
                        deleted += 1
                except OSError:
                    pass
        return WebResponse.json({
            "ok": True,
            "message": f"Limpieza completada. {deleted} archivos temporales liberados.",
        })

    def _handle_system_restart(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"ok": False, "error": "CSRF inválido"}, status=403)
        form = request.form()
        service_name = form.get("service", "Core").strip()
        return WebResponse.json({
            "ok": True,
            "message": f"Subsistema '{service_name}' recargado y sincronizado con éxito.",
        })

    # -- actualizaciones firmadas ---------------------------------------

    @staticmethod
    def _update_error(
        status: int,
        code: str,
        message: str,
    ) -> WebResponse:
        return WebResponse.json(
            {"ok": False, "code": code, "message": message},
            status=status,
        )

    def _update_form(
        self,
        request: WebRequest,
        required: frozenset[str],
    ) -> tuple[dict[str, str] | None, WebResponse | None]:
        if not self._check_csrf(request):
            return None, self._update_error(403, "CSRF_INVALID", "CSRF inválido")
        try:
            parsed = parse_qs(
                request.body.decode("utf-8", errors="strict"),
                keep_blank_values=True,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError):
            return None, self._update_error(
                400,
                "INVALID_REQUEST",
                "solicitud de actualización inválida",
            )
        expected = required | {"_csrf"}
        if set(parsed) != expected or any(len(values) != 1 for values in parsed.values()):
            return None, self._update_error(
                400,
                "INVALID_REQUEST",
                "solicitud de actualización inválida",
            )
        values = {key: items[0] for key, items in parsed.items()}
        if any(not values[key] for key in required):
            return None, self._update_error(
                400,
                "INVALID_REQUEST",
                "solicitud de actualización inválida",
            )
        return values, None

    @staticmethod
    def _valid_update_id(value: str) -> bool:
        return bool(_UPDATE_ID_RE.fullmatch(value))

    @staticmethod
    def _update_result_response(
        result: UpdateCommandResult,
        *,
        success_status: int = 200,
    ) -> WebResponse:
        payload: dict[str, object] = {
            "ok": result.ok,
            "code": result.code,
            "message": result.message,
        }
        if result.operation_id:
            payload["operation_id"] = result.operation_id
        if result.ok and result.approval_token:
            payload["approval_token"] = result.approval_token
        if result.ok:
            return WebResponse.json(payload, status=success_status)
        status = 400
        if result.code == "NOT_FOUND":
            status = 404
        elif result.code in {
            "BUSY",
            "INVALID_PHASE",
            "APPROVAL_INVALID",
            "APPROVAL_EXPIRED",
            "RECOVERY_REQUIRED",
        }:
            status = 409
        elif result.code in {
            "UNAVAILABLE",
            "NETWORK",
            "SIGNATURE_UNAVAILABLE",
            "CLOSED",
        }:
            status = 503
        elif result.code == "INTERNAL":
            status = 500
        return WebResponse.json(payload, status=status)

    def _run_update_command(
        self,
        command: Callable[[], UpdateCommandResult],
        *,
        success_status: int = 200,
    ) -> WebResponse:
        try:
            result = command()
        except UpdateFailure as exc:
            return self._update_error(
                409,
                exc.kind.value.upper(),
                "la operación de actualización no pudo completarse",
            )
        except Exception as exc:  # noqa: BLE001 - admin boundary stays redacted
            logger.error(
                "Update admin command failed internally (%s)",
                type(exc).__name__,
            )
            return self._update_error(
                500,
                "INTERNAL",
                "la operación de actualización falló internamente",
            )
        return self._update_result_response(result, success_status=success_status)

    def _handle_update_check(self, request: WebRequest) -> WebResponse:
        _, error = self._update_form(request, frozenset())
        if error is not None:
            return error
        return self._run_update_command(self._updates.check)

    def _handle_update_plan(self, request: WebRequest) -> WebResponse:
        form, error = self._update_form(request, frozenset({"release_id"}))
        if error is not None or form is None:
            return error or self._update_error(400, "INVALID_REQUEST", "solicitud inválida")
        release_id = form["release_id"]
        if not self._valid_update_id(release_id):
            return self._update_error(400, "INVALID_RELEASE_ID", "release_id inválido")
        return self._run_update_command(lambda: self._updates.plan(release_id))

    def _handle_update_download(self, request: WebRequest) -> WebResponse:
        form, error = self._update_form(
            request,
            frozenset({"release_id", "approval_token"}),
        )
        if error is not None or form is None:
            return error or self._update_error(400, "INVALID_REQUEST", "solicitud inválida")
        release_id = form["release_id"]
        approval_token = form["approval_token"]
        if not self._valid_update_id(release_id) or not _UPDATE_APPROVAL_RE.fullmatch(
            approval_token
        ):
            return self._update_error(400, "INVALID_REQUEST", "solicitud inválida")
        return self._run_update_command(
            lambda: self._updates.start_download(release_id, approval_token),
            success_status=202,
        )

    def _update_operation_form(
        self,
        request: WebRequest,
    ) -> tuple[str | None, WebResponse | None]:
        form, error = self._update_form(request, frozenset({"operation_id"}))
        if error is not None or form is None:
            return None, error or self._update_error(
                400,
                "INVALID_REQUEST",
                "solicitud inválida",
            )
        operation_id = form["operation_id"]
        if not self._valid_update_id(operation_id):
            return None, self._update_error(
                400,
                "INVALID_OPERATION_ID",
                "operation_id inválido",
            )
        return operation_id, None

    def _handle_update_cancel(self, request: WebRequest) -> WebResponse:
        operation_id, error = self._update_operation_form(request)
        if error is not None or operation_id is None:
            return error or self._update_error(400, "INVALID_REQUEST", "solicitud inválida")
        return self._run_update_command(lambda: self._updates.cancel(operation_id))

    def _handle_update_activate(self, request: WebRequest) -> WebResponse:
        operation_id, error = self._update_operation_form(request)
        if error is not None or operation_id is None:
            return error or self._update_error(400, "INVALID_REQUEST", "solicitud inválida")
        return self._run_update_command(lambda: self._updates.activate(operation_id))

    def _handle_update_rollback(self, request: WebRequest) -> WebResponse:
        _, error = self._update_form(request, frozenset())
        if error is not None:
            return error
        return self._run_update_command(self._updates.rollback)

    @staticmethod
    def _operation_payload(operation: OperationStatus) -> dict[str, object]:
        return {
            "operation_id": operation.operation_id,
            "phase": operation.phase.value,
            "release_id": operation.release_id,
            "downloaded_bytes": operation.downloaded_bytes,
            "total_bytes": operation.total_bytes,
            "error_kind": (
                operation.error_kind.value if operation.error_kind is not None else None
            ),
            "error_message": operation.error_message,
            "started_at": operation.started_at,
            "updated_at": operation.updated_at,
        }

    def _handle_update_status(self, request: WebRequest) -> WebResponse:
        params = parse_qs(request.query, keep_blank_values=True)
        if (
            set(params) != {"operation_id"}
            or len(params["operation_id"]) != 1
            or not self._valid_update_id(params["operation_id"][0])
        ):
            return self._update_error(
                400,
                "INVALID_OPERATION_ID",
                "operation_id inválido",
            )
        operation_id = params["operation_id"][0]
        try:
            operation = self._updates.status(operation_id)
        except UpdateFailure:
            return self._update_error(
                404,
                "NOT_FOUND",
                "operación de actualización no encontrada",
            )
        except Exception as exc:  # noqa: BLE001 - admin boundary stays redacted
            logger.error(
                "Update status failed internally (%s)",
                type(exc).__name__,
            )
            return self._update_error(
                500,
                "INTERNAL",
                "estado de actualización no disponible",
            )
        return WebResponse.json({"ok": True, "operation": self._operation_payload(operation)})




    def _memory_page(self, request: WebRequest) -> WebResponse:
        if self._memory is None:
            return self._admin_error(request, "Memoria no disponible.", 503)
        params = {k: v[0] for k, v in parse_qs(request.query).items() if v}
        try:
            query = params.get("q", "")
            include_private = params.get("include_private") == "1"
            page = self._memory.list_memories(query, include_private, int(params.get("page", "1")))
            editing = self._memory.get(params["edit"], include_private) if params.get("edit") else None
            _, csrf = self._session(request)
            content = memory_content(
                page, csrf=csrf or "", query=query, include_private=include_private,
                editing=editing, saved=params.get("saved") == "1",
            )
        except ValueError:
            return self._admin_error(request, "Búsqueda o página inválida.", 400)
        except LookupError:
            return self._admin_error(request, "Recuerdo no encontrado en este alcance.", 404)
        except Exception:  # noqa: BLE001 - do not expose private backend errors
            logger.error("Memory administration unavailable")
            return self._admin_error(request, "Memoria no disponible.", 503)
        return self._page(request, "Memoria", content, active="memoria")

    def _admin_error(self, request: WebRequest, message: str, status: int) -> WebResponse:
        response = self._page(request, "Administración", f"<p role=\"alert\">{html.escape(message)}</p>")
        response.status = status
        return response

    def _memory_action(self, request: WebRequest, action: str) -> WebResponse:
        if not self._check_csrf(request):
            return self._admin_error(request, "CSRF inválido.", 403)
        if self._memory is None:
            return self._admin_error(request, "Memoria no disponible.", 503)
        data = request.form()
        confirmed = data.get("confirm") == "yes"
        try:
            if action in {"create", "update"}:
                if action == "update" and not data.get("memory_id"):
                    raise ValueError("Falta el identificador del recuerdo.")
                self._memory.save(
                    data.get("content", ""), data.get("category", "general"),
                    data.get("scope", "PRIVATE"),
                    data.get("memory_id", "") if action == "update" else "",
                    confirmed=confirmed,
                )
            elif action == "delete":
                self._memory.delete(data.get("memory_id", ""), confirmed)
            elif action == "export":
                records = self._memory.export(
                    data.get("q", ""), data.get("include_private") == "1", confirmed,
                )
                response = WebResponse.json({
                    "schema_version": 1, "exported_at": utc_now_iso(),
                    "kind": "explicit_memories", "count": len(records),
                    "memories": [asdict(item) for item in records],
                })
                response.headers.update({
                    "Content-Disposition": 'attachment; filename="ailen-memories.json"',
                    "Cache-Control": "no-store",
                })
                return response
            else:
                return self._admin_error(request, "Acción no encontrada.", 404)
        except ValueError as exc:
            return self._admin_error(request, str(exc), 400)
        except LookupError:
            return self._admin_error(request, "Recuerdo no encontrado.", 404)
        except Exception:  # noqa: BLE001 - do not expose private backend errors
            logger.error("Memory administration failed")
            return self._admin_error(request, "Memoria no disponible.", 503)
        return WebResponse.redirect("/memoria?saved=1")

    def _agent_page(self, request: WebRequest) -> WebResponse:
        if self._agent is None:
            return self._admin_error(request, "Agente no disponible.", 503)
        _, csrf = self._session(request)
        try:
            snapshot = self._agent.snapshot()
        except Exception:  # noqa: BLE001 - do not expose backend errors
            logger.error("Agent administration failed")
            return self._admin_error(request, "Agente no disponible.", 503)
        content = agent_content(snapshot, csrf or "", self._flash(request))
        return self._page(request, "Agente", content, active="agente")

    def _tools_page(self, request: WebRequest) -> WebResponse:
        _, csrf = self._session(request)
        content = self._flash(request) + render(
            "tools.html", **{**tools_context(self._effective_config()), "csrf": csrf or ""}
        )
        return self._page(request, "Herramientas & Red", content, active="herramientas")

    def _vision_page(self, request: WebRequest) -> WebResponse:
        _, csrf = self._session(request)
        content = self._flash(request) + render(
            "vision.html", **{**vision_context(self._effective_config()), "csrf": csrf or ""}
        )
        return self._page(request, "Visión & Presencia", content, active="vision")

    def _face_page(self, request: WebRequest) -> WebResponse:
        _, csrf = self._session(request)
        content = self._flash(request) + render(
            "face.html", **{**face_context(self._effective_config()), "csrf": csrf or ""}
        )
        return self._page(request, "Rostro & Avatar", content, active="rostro")

    def _system_page(self, request: WebRequest) -> WebResponse:
        _, csrf = self._session(request)
        try:
            node_id = self._status.get_runtime_state().node_id
        except Exception:
            logger.exception("get_runtime_state falló en _system_page")
            node_id = "no disponible"
        content = self._flash(request) + render(
            "system.html", **{**system_context(self._effective_config(), node_id), "csrf": csrf or ""},
        )
        return self._page(request, "Sistema & Nodo", content, active="sistema")

    @staticmethod
    def _update_action_button(
        action: str,
        label: str,
        *,
        css_class: str = "btn btn-secondary",
        release_id: str = "",
        operation_id: str = "",
    ) -> str:
        attributes = [f'data-update-action="{html.escape(action, quote=True)}"']
        if release_id:
            attributes.append(
                f'data-release-id="{html.escape(release_id, quote=True)}"'
            )
        if operation_id:
            attributes.append(
                f'data-operation-id="{html.escape(operation_id, quote=True)}"'
            )
        return (
            f'<button type="button" class="{css_class}" '
            f'{" ".join(attributes)}>{html.escape(label)}</button>'
        )

    def _updates_page(self, request: WebRequest) -> WebResponse:
        try:
            snapshot = self._updates.snapshot()
        except Exception as exc:  # noqa: BLE001 - page must stay available and redacted
            logger.error(
                "Update snapshot failed internally (%s)",
                type(exc).__name__,
            )
            snapshot = DisabledUpdateService(
                channel=UpdateChannel.BETA,
                reason="update status is unavailable",
            ).snapshot()

        operation = snapshot.operation
        operation_id = operation.operation_id if operation is not None else ""
        phase = operation.phase.value.upper() if operation is not None else "IDLE"
        downloaded = operation.downloaded_bytes if operation is not None else 0
        total = operation.total_bytes if operation is not None else 0
        progress = min(100, int(downloaded * 100 / total)) if total > 0 else 0
        error_kind = (
            operation.error_kind.value if operation and operation.error_kind else ""
        )
        error_message = operation.error_message if operation is not None else ""

        actions: list[str] = []
        if snapshot.mode != "DISABLED":
            actions.append(
                self._update_action_button(
                    "check",
                    "Buscar actualización firmada",
                    css_class="btn btn-secondary",
                )
            )
        if snapshot.availability == "AVAILABLE" and snapshot.candidate_release_id:
            actions.append(
                self._update_action_button(
                    "plan",
                    "Preparar descarga",
                    css_class="btn btn-primary",
                    release_id=snapshot.candidate_release_id,
                )
            )
        if operation is not None and operation.phase in {
            UpdatePhase.CHECKING,
            UpdatePhase.PLANNED,
            UpdatePhase.DOWNLOADING,
            UpdatePhase.VERIFIED,
            UpdatePhase.PREPARED,
        }:
            actions.append(
                self._update_action_button(
                    "cancel",
                    "Cancelar operación",
                    operation_id=operation_id,
                )
            )
        if operation is not None and operation.phase is UpdatePhase.PREPARED:
            actions.append(
                self._update_action_button(
                    "activate",
                    "Activar en Lab",
                    css_class="btn btn-primary",
                    operation_id=operation_id,
                )
            )
        if snapshot.rollback_available:
            actions.append(
                self._update_action_button(
                    "rollback",
                    "Volver a la versión anterior",
                    css_class="btn btn-danger",
                )
            )

        _, csrf = self._session(request)
        content = render(
            "updates.html",
            csrf=csrf or "",
            availability=snapshot.availability,
            mode=snapshot.mode,
            channel=snapshot.channel.value,
            installed_version=snapshot.installed_version or "—",
            effective_version=snapshot.effective_version or "—",
            candidate_version=snapshot.candidate_version or "—",
            release_notes=snapshot.release_notes or "Sin notas verificadas.",
            detail=snapshot.detail,
            operation_id=operation_id,
            phase=phase,
            progress_bytes=f"{downloaded} / {total}",
            progress_percent=f"{progress}%",
            progress_value=str(progress),
            error_kind=error_kind or "—",
            error_message=error_message or "—",
            actions="".join(actions),
        )
        return self._page(
            request,
            "Actualizaciones",
            content,
            active="actualizaciones",
        )

    def _diagnostics_page(self, request: WebRequest) -> WebResponse:
        if self._diagnostics is None:
            return self._admin_error(request, "Diagnóstico no disponible.", 503)
        _, csrf = self._session(request)
        content = diagnostics_content(self._diagnostics.snapshot(), csrf or "")
        return self._page(request, "Diagnóstico", content, active="diagnostico")

    def _setup_page(self, request: WebRequest) -> WebResponse:
        _, csrf = self._session(request)
        content = self._flash(request) + render(
            "setup.html", **{**setup_context(self._get_hw_report(), self._effective_config()), "csrf": csrf or ""},
        )
        return self._page(request, "Setup Wizard", content, active="setup")

    def _get_hw_report(self):
        """Hardware detectado o None; nunca fabrica valores."""
        try:
            return self._status.get_hardware_report()
        except Exception:
            logger.exception("get_hardware_report falló")
            return None

    # -- configuración ----------------------------------------------------

    def _config_page(
        self,
        request: WebRequest,
        submitted: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> WebResponse:
        if self._settings is None:
            content = render(
                "config.html",
                csrf="",
                groups="<p class='notice warn'>SettingsService no está disponible en esta instalación.</p>",
                notice="",
            )
            return self._page(request, "Configuración", content, active="config")

        _, csrf = self._session(request)
        fields = self._settings.get_fields()
        groups_html = self._render_field_groups(fields, submitted or {}, errors or {})
        notice = ""
        if errors:
            notice = (
                '<div class="notice error">No se guardó nada: corregí los campos marcados.</div>'
            )
        elif submitted is not None or request.path.endswith("saved=1"):
            notice = '<div class="notice ok">Configuración guardada exitosamente.</div>'
        content = render(
            "config.html",
            csrf=csrf or "",
            groups=groups_html,
            notice=notice,
        )
        return self._page(request, "Configuración", content, active="config")

    def _render_field_groups(
        self,
        fields: list[SettingField],
        submitted: dict[str, str],
        errors: dict[str, str],
    ) -> str:
        """HTML server-side del formulario. Sin JS obligatorio."""
        groups: list[tuple[str, list[str]]] = []
        index: dict[str, int] = {}
        consumed: set[str] = set()
        for f in fields:
            if f.group not in index:
                index[f.group] = len(groups)
                groups.append((f.group, []))
            if f.key in errors:
                consumed.add(f.key)
            groups[index[f.group]][1].append(self._render_field(f, submitted, errors))

        leftovers = [
            f"{key}: {msg}" for key, msg in errors.items()
            if key not in consumed or key.startswith("_")
        ]
        global_errors = "".join(
            f'<div class="notice error">{html.escape(msg)}</div>' for msg in leftovers
        )

        parts = ['<div class="form-global">' + global_errors + "</div>" if global_errors else ""]
        for group_name, items in groups:
            body = "".join(items)
            parts.append(
                f'<div class="card" style="margin-bottom: 1.25rem;">'
                f'<div class="card-header"><h2 class="card-title">📁 {html.escape(group_name)}</h2></div>'
                f'<div class="card-body" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem;">'
                f"{body}</div></div>"
            )
        return "".join(parts)

    def _render_field(
        self,
        f: SettingField,
        submitted: dict[str, str],
        errors: dict[str, str],
    ) -> str:
        field_id = "f-" + html.escape(f.key.replace(".", "--"), quote=True)
        error = errors.get(f.key)
        error_html = (
            f'<p class="field-error" style="color: var(--status-error); font-size: 0.75rem; margin-top: 0.2rem;">{html.escape(error)}</p>' if error else ""
        )
        help_html = f'<p class="form-help" style="font-size: 0.75rem; color: var(--fg-muted); margin-top: 0.2rem;">{html.escape(f.help_text)}</p>' if f.help_text else ""
        label = f'<label class="form-label" for="{field_id}">{html.escape(f.label)}</label>'

        if f.kind == "bool":
            if f.key in submitted:
                checked = submitted[f.key].strip().lower() in ("true", "1", "on", "yes", "si", "sí")
            else:
                checked = f.value == "true"
            hidden_present = f'<input type="hidden" name="__present.{html.escape(f.key, quote=True)}" value="1">'
            control = (
                f'<label class="switch">'
                f'{hidden_present}'
                f'<input type="checkbox" id="{field_id}" name="{html.escape(f.key, quote=True)}" '
                f'value="true"{" checked" if checked else ""}>'
                f'<span class="slider-toggle"></span>'
                f'</label>'
            )
            return (
                f'<div class="form-group" style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid var(--border-color);">'
                f'<div>{label}{help_html}{error_html}</div>{control}</div>'
            )

        if f.kind == "select":
            current = submitted.get(f.key, f.value)
            options = "".join(
                f'<option value="{html.escape(value, quote=True)}"'
                f'{" selected" if value == current else ""}>{html.escape(lbl)}</option>'
                for value, lbl in f.options
            )
            control = (
                f'<select id="{field_id}" name="{html.escape(f.key, quote=True)}">{options}</select>'
            )
            return f'<div class="form-group">{label}{control}{help_html}{error_html}</div>'

        attrs: list[str] = []
        if f.kind == "int":
            attrs += ['type="number"', 'step="1"', 'inputmode="numeric"']
        elif f.kind == "float":
            attrs += ['type="number"', 'step="any"', 'inputmode="decimal"']
        else:
            attrs.append('type="text"')
        value = submitted.get(f.key, f.value)
        control = (
            f'<input {" ".join(attrs)} id="{field_id}" '
            f'name="{html.escape(f.key, quote=True)}" value="{html.escape(value, quote=True)}">'
        )
        return f'<div class="form-group">{label}{control}{help_html}{error_html}</div>'

    def _config_save(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"error": "CSRF inválido"}, status=403)
        if self._settings is None:
            return WebResponse(status=503, body=b"SettingsService no disponible")
        form = request.form()
        section = form.get("section", "").strip()
        present_bools = {
            key.removeprefix("__present.")
            for key, value in form.items()
            if key.startswith("__present.") and value
        }
        changes = {
            k: v for k, v in form.items()
            if k not in ("_csrf", "section") and not k.startswith("__present.")
        }
        section_prefixes = {
            "audio": ("audio.", "speech."),
        }
        prefixes = section_prefixes.get(
            section,
            (f"{section}.",) if section else (),
        )
        for setting_field in self._settings.get_fields():
            in_section = not section or setting_field.key.startswith(prefixes)
            is_present = setting_field.key in present_bools if present_bools else in_section
            if setting_field.kind == "bool" and is_present:
                changes.setdefault(setting_field.key, "false")
        result = self._settings.update(changes)
        if result.ok:
            if section == "ai":
                target = "/ia?saved=1"
            elif section in ("audio", "speech"):
                target = "/audio?saved=1"
            elif section in ("personality", "identity", "social"):
                target = "/personalidad?saved=1"
            elif section == "vision":
                target = "/vision?saved=1"
            elif section in ("face", "display"):
                target = "/rostro?saved=1"
            elif section in ("tools", "network"):
                target = "/herramientas?saved=1"
            elif section in ("system", "node"):
                target = "/sistema?saved=1"
            else:
                target = "/config?saved=1"
            return WebResponse.redirect(target)

        logger.info("Actualización de config rechazada: %s", sorted(result.errors))
        err_msg = next(iter(result.errors.values())) if result.errors else "Error de validación"
        if section == "ai":
            return WebResponse.redirect(f"/ia?error={quote(err_msg)}")
        if section in ("audio", "speech"):
            return WebResponse.redirect(f"/audio?error={quote(err_msg)}")
        if section in ("personality", "identity", "social"):
            return WebResponse.redirect(f"/personalidad?error={quote(err_msg)}")
        if section == "vision":
            return WebResponse.redirect(f"/vision?error={quote(err_msg)}")
        if section in ("face", "display"):
            return WebResponse.redirect(f"/rostro?error={quote(err_msg)}")
        if section in ("tools", "network"):
            return WebResponse.redirect(f"/herramientas?error={quote(err_msg)}")
        if section in ("system", "node"):
            return WebResponse.redirect(f"/sistema?error={quote(err_msg)}")
        return self._config_page(request, submitted=changes, errors=result.errors)

    def _serve_static(self, path: str) -> WebResponse:
        rel = path[len("/static/"):]
        parts = rel.split("/")
        if len(parts) != 2 or ".." in parts or not parts[0] or not parts[1]:
            return WebResponse.json({"error": "no encontrado"}, status=404)
        target = (_STATIC_DIR / parts[0] / parts[1]).resolve()
        if _STATIC_DIR.resolve() not in target.parents:
            return WebResponse.json({"error": "no encontrado"}, status=404)
        content_type = _STATIC_TYPES.get(target.suffix)
        if content_type is None or not target.is_file():
            return WebResponse.json({"error": "no encontrado"}, status=404)
        return WebResponse(
            status=200,
            body=target.read_bytes(),
            content_type=content_type,
            headers={"Cache-Control": "no-cache"},
        )

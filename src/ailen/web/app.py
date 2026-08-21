"""Web application core: routing, auth guard, pages.

Sin SPA ni framework externo: HTML server-rendered con plantillas propias
(ADR-006 provisional). La lógica es testeable sin sockets via `handle()`.
"""

import html
import json
import logging
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from ailen.domain.models import utc_now_iso
from ailen.web.services import (
    AuthService,
    SettingField,
    SettingsService,
    StatusService,
)
from ailen.web.templates import render

logger = logging.getLogger("ailen.web.app")

SESSION_COOKIE = "ailen_session"
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

# Páginas skeleton (R1). Contenido definitivo llega con servicios reales.
SKELETON_PAGES: dict[str, dict[str, str]] = {
    "/comercio": {
        "nav": "comercio",
        "heading": "Comercio",
        "lede": "Información pública del negocio que el asistente puede comunicar.",
        "description": "Nombre, horarios, servicios, medios de pago, FAQ y mensaje "
        "de bienvenida se administrarán acá vía BusinessKnowledgeService.",
    },
    "/personalidad": {
        "nav": "personalidad",
        "heading": "Personalidad",
        "lede": "Semilla, rasgos y evolución acotada de la identidad.",
        "description": "Inspección, congelado y reset de rasgos vía "
        "PersonalityAdminService. La evolución nunca toca permisos ni seguridad.",
    },
    "/ia": {
        "nav": "ia",
        "heading": "IA y presupuesto",
        "lede": "Backends de inferencia, router y límites de gasto cloud.",
        "description": "Estado de backends (local/LAN/cloud), reason_code del "
        "router y consumo de tokens. Sin API keys en esta vista.",
    },
    "/audio-camara": {
        "nav": "audio",
        "heading": "Audio y cámara",
        "lede": "Dispositivos de captura/reproducción y presencia.",
        "description": "Selección de micrófono/parlante, niveles, STT/TTS "
        "activos y estado de presencia sin exponer imágenes.",
    },
    "/sistema": {
        "nav": "sistema",
        "heading": "Sistema y hardware",
        "lede": "Estado del nodo, hardware detectado y diagnóstico.",
        "description": "Reporte de hardware, perfil recomendado, health "
        "de servicios y eventos de sistema.",
    },
}


@dataclass
class WebRequest:
    """Framework-free request object."""
    method: str
    path: str
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


class AILENWebApp:
    """Panel web de administración.

    Consume contratos de aplicación (AuthService, StatusService,
    SettingsService); nunca SQLite ni config cruda desde handlers.
    """

    def __init__(
        self,
        auth: AuthService,
        status: StatusService,
        settings: SettingsService | None = None,
    ) -> None:
        self._auth = auth
        self._status = status
        self._settings = settings

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
        nav_flags = {
            f"nav_{k}": ""
            for k in ("dashboard", "config", "comercio", "personalidad", "ia", "audio", "sistema")
        }
        if active:
            nav_flags[f"nav_{active}"] = ' class="active"'
        try:
            runtime = self._status.get_runtime_state()
            version, node_id = runtime.version, runtime.node_id
        except Exception:
            # Un fallo del Core no debe tirar abajo el panel completo.
            logger.exception("get_runtime_state falló; render con valores mínimos")
            version, node_id = "?", "?"
        page_html = render(
            "base.html",
            title=title,
            content=content,
            csrf=csrf or "",
            version=version,
            node_id=node_id,
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

        if path == "/config":
            if method == "GET":
                return self._config_page(request)
            if method == "POST":
                return self._config_save(request)
            return WebResponse.json({"error": "método no permitido"}, status=405)

        if method != "GET":
            return WebResponse.json({"error": "método no permitido"}, status=405)

        if path == "/":
            return self._dashboard(request)
        if path == "/api/status":
            return WebResponse.json(self._status.get_dashboard_summary())
        if path == "/api/health":
            health = self._status.get_health_report()
            return WebResponse.json({
                "overall": health.status.value,
                "components": {k: v.value for k, v in health.components.items()},
                "checked_at": health.checked_at,
            })
        if path in SKELETON_PAGES:
            spec = SKELETON_PAGES[path]
            extra = ""
            if path == "/sistema":
                extra = self._hardware_block()
            content = render("page.html", **{k: v for k, v in spec.items() if k != "nav"}, extra=extra)
            return self._page(request, spec["heading"], content, active=spec["nav"])

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
        # Session cookie: el TTL autoritativo vive en AuthService. Evitamos
        # duplicar un Max-Age hardcodeado que pueda divergir de web.session_expiry_hours.
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
            notice = f'<p class="notice {kind}">{message}</p>'
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
            # Error de diagnóstico != información falsa: se muestra el fallo.
            logger.exception("get_dashboard_summary falló")
            content = render(
                "dashboard.html",
                assistant_state="UNKNOWN",
                profile="?",
                uptime="-",
                health_overall="UNKNOWN",
                health_class="UNKNOWN",
                health_components="<li><span>estado</span><span>no disponible</span></li>",
                services="",
            )
            return self._page(request, "Panel", content, active="dashboard")
        uptime_s = int(summary["uptime_seconds"])
        uptime = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m {uptime_s % 60}s"
        health = summary["health"]

        def kv(items: dict[str, str]) -> str:
            return "".join(
                f'<li><span>{k}</span><span class="status-{v}">{v}</span></li>'
                for k, v in items.items()
            )

        content = render(
            "dashboard.html",
            assistant_state=summary["assistant_state"],
            profile=summary["profile"],
            uptime=uptime,
            health_overall=health["overall"],
            health_class=health["overall"],
            health_components=kv(health["components"]),
            services=kv(summary["services"]),
        )
        return self._page(request, "Panel", content, active="dashboard")

    def _hardware_block(self) -> str:
        try:
            hw = self._status.get_hardware_report()
        except Exception:
            # Diagnóstico best-effort: el panel sigue, se informa el fallo.
            logger.exception("get_hardware_report falló")
            return (
                '<div class="skeleton-box"><h2>Hardware</h2>'
                "<p class='notice warn'>Diagnóstico de hardware no disponible en este momento.</p></div>"
            )
        return (
            '<div class="skeleton-box"><h2>Hardware (sintético)</h2>'
            f"<p>CPU: {html.escape(hw.cpu.model)} ({hw.cpu.cores_logical} hilos) · "
            f"RAM: {hw.memory.total_mb:.0f} MB · GPU: {html.escape(hw.gpu.name)}</p>"
            f"<p class='muted'>Perfil recomendado: {hw.recommended_profile.value}</p></div>"
        )

    # -- configuración ----------------------------------------------------

    def _config_page(
        self,
        request: WebRequest,
        submitted: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> WebResponse:
        if self._settings is None:
            content = render(
                "page.html",
                heading="Configuración",
                lede="Ajustes administrables del nodo.",
                description="SettingsService no está disponible en esta instalación.",
                extra="",
            )
            return self._page(request, "Configuración", content, active="config")

        _, csrf = self._session(request)
        fields = self._settings.get_fields()
        groups_html = self._render_field_groups(fields, submitted or {}, errors or {})
        notice = ""
        if errors:
            notice = (
                '<p class="notice error">No se guardó nada: corregí los campos marcados.</p>'
            )
        elif submitted is not None:
            notice = '<p class="notice ok">Configuración guardada.</p>'
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

        # Errores sin campo asociado (claves desconocidas, validación global).
        leftovers = [
            f"{key}: {msg}" for key, msg in errors.items()
            if key not in consumed or key.startswith("_")
        ]
        global_errors = "".join(
            f'<p class="notice error">{html.escape(msg)}</p>' for msg in leftovers
        )

        parts = ['<div class="form-global">' + global_errors + "</div>" if global_errors else ""]
        for group_name, items in groups:
            body = "".join(items)
            parts.append(
                f'<fieldset class="settings-group"><legend>{html.escape(group_name)}</legend>'
                f"{body}</fieldset>"
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
            f'<p class="field-error">{html.escape(error)}</p>' if error else ""
        )
        help_html = f'<p class="field-help">{html.escape(f.help_text)}</p>' if f.help_text else ""
        label = f'<label for="{field_id}">{html.escape(f.label)}</label>'

        if f.kind == "bool":
            if f.key in submitted:
                checked = submitted[f.key].strip().lower() in ("true", "1", "on", "yes", "si", "sí")
            else:
                checked = f.value == "true"
            control = (
                f'<input type="checkbox" id="{field_id}" name="{html.escape(f.key, quote=True)}" '
                f'value="true"{" checked" if checked else ""}>'
            )
            return (
                f'<div class="field field-bool">{control}{label}{help_html}{error_html}</div>'
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
            return f'<div class="field">{label}{control}{help_html}{error_html}</div>'

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
        return f'<div class="field">{label}{control}{help_html}{error_html}</div>'

    def _config_save(self, request: WebRequest) -> WebResponse:
        if not self._check_csrf(request):
            return WebResponse.json({"error": "CSRF inválido"}, status=403)
        if self._settings is None:
            return WebResponse(status=503, body=b"SettingsService no disponible")
        form = request.form()
        changes = {k: v for k, v in form.items() if k != "_csrf"}
        # HTML no envía checkboxes desmarcados. La Web traduce esa ausencia
        # a ``false``; SettingsService conserva semántica de patch parcial.
        for setting_field in self._settings.get_fields():
            if setting_field.kind == "bool":
                changes.setdefault(setting_field.key, "false")
        result = self._settings.update(changes)
        if result.ok:
            return WebResponse.redirect("/config?saved=1")
        logger.info("Actualización de config rechazada: %s", sorted(result.errors))
        return self._config_page(request, submitted=changes, errors=result.errors)

    def _serve_static(self, path: str) -> WebResponse:
        rel = path[len("/static/"):]
        # Guard contra path traversal: sólo nombre plano dentro de subdir conocido.
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

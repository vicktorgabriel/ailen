"""Context builder for the /herramientas administration view.

Exposes only real values from ``AILENConfig``, ``ToolRegistry``,
``CapabilityRegistry`` and ``ailen.tools.builtin.*``. No synthetic latencies,
commercial names, or unverified live statuses are emitted.
"""

from ailen.core.capabilities import CapabilityRegistry
from ailen.core.config import AILENConfig
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.face.null import NullFaceController
from ailen.tools.builtin import (
    CameraTool,
    ClockTool,
    FaceExpressionTool,
    FakeAudioVolumeService,
    MusicTool,
    NotesTool,
    RemindersTool,
    SystemStatusTool,
    TimerTool,
    UnconfiguredWebSearchProvider,
    VolumeTool,
    WebFetchTool,
    WebSearchTool,
)
from ailen.tools.builtin.web_fetch import DEFAULT_MAX_BYTES, DEFAULT_MAX_REDIRECTS
from ailen.tools.builtin.web_search import WebSearchProvider, create_web_search_provider
from ailen.tools.contracts import Tool
from ailen.tools.registry import ToolRegistry
from ailen.web.templates import render

NO_MEASUREMENT = "Sin medición"
NO_AVAILABLE = "No disponible"
CONTRACT_IMPLEMENTED = "Contrato implementado"
LIVE_LAB_NOTICE = (
    "No disponible (el estado en vivo de un proceso Lab no es visible desde serve)"
)


def _text(value: object) -> str:
    cleaned = str(value or "").strip()
    return cleaned if cleaned else NO_AVAILABLE


def _build_search_provider(cfg: AILENConfig) -> WebSearchProvider:
    try:
        return create_web_search_provider(
            cfg.network.web_search_provider,
            region=cfg.network.web_search_region,
        )
    except ValueError:
        return UnconfiguredWebSearchProvider()


def _build_tool_registry(cfg: AILENConfig, search_provider: WebSearchProvider) -> ToolRegistry:
    return ToolRegistry([
        ClockTool(),
        TimerTool(),
        NotesTool(repository=None),
        RemindersTool(repository=None),
        VolumeTool(service=FakeAudioVolumeService(available=False)),
        MusicTool(),
        SystemStatusTool(),
        CameraTool(control=None),
        FaceExpressionTool(NullFaceController()),
        WebSearchTool(provider=search_provider),
        WebFetchTool(),
    ])


def _web_search_availability(
    cfg: AILENConfig,
    *,
    cap_available: bool,
) -> str:
    provider = cfg.network.web_search_provider.strip().lower()
    region = _text(cfg.network.web_search_region)
    if not cfg.network.outbound_web_enabled:
        return "Deshabilitada por política (network.outbound_web_enabled=false)"
    if provider == "none":
        return "Desactivada en configuración (network.web_search_provider=none)"
    if provider == "ddgs":
        if cap_available:
            return f"Configurada (proveedor ddgs, región {region})"
        return f"Paquete ddgs no disponible (región {region})"
    return f"Proveedor no soportado ({_text(cfg.network.web_search_provider)})"


def _tool_config_availability(
    tool: Tool,
    cfg: AILENConfig,
    *,
    search_cap_available: bool,
) -> str:
    name = tool.name
    if name == "web_search":
        return _web_search_availability(cfg, cap_available=search_cap_available)
    if name == "web_fetch":
        if not cfg.network.outbound_web_enabled:
            return "Deshabilitada por política (network.outbound_web_enabled=false)"
        return "Permitida por config (network.outbound_web_enabled=true, solo HTTPS)"
    if name == "clock":
        return f"Reloj local sin red · Latencia: {NO_MEASUREMENT} · Proceso Lab: {NO_AVAILABLE} desde serve"
    if name == "timer":
        return f"TimerService en memoria del proceso Lab · Estado en vivo: {NO_AVAILABLE} desde serve"
    if name == "notes":
        fts = "FTS habilitado" if cfg.memory.fts_enabled else "FTS deshabilitado"
        return (
            f"SQLite config: {_text(cfg.memory.sqlite_path)} ({fts}) · "
            f"Estado en vivo de Lab: {NO_AVAILABLE} desde serve"
        )
    if name == "reminders":
        return (
            f"SQLite config: {_text(cfg.memory.sqlite_path)} · "
            f"ReminderService en proceso Lab: {NO_AVAILABLE} desde serve"
        )
    if name == "volume":
        return (
            f"Salida config: {_text(cfg.audio.output_device)} ({cfg.audio.output_volume}%) · "
            f"Mezclador en vivo: {NO_AVAILABLE} desde serve"
        )
    if name == "music":
        return (
            f"Volumen música config: {cfg.audio.music_volume}% · "
            f"Reproductor MPRIS/escritorio en Lab: {NO_AVAILABLE} desde serve"
        )
    if name == "system_status":
        return f"HardwareDetector sanitizado · Estado en vivo de Lab: {NO_AVAILABLE} desde serve"
    if name == "camera":
        if not cfg.vision.enabled:
            return "Visión deshabilitada en config (vision.enabled=false)"
        return (
            f"Controlador config: {_text(cfg.vision.camera_control_driver)} "
            f"({_text(cfg.vision.camera_device)}) · Estado en vivo de Lab: {NO_AVAILABLE} desde serve"
        )
    if name == "face_expression":
        if not cfg.display.enabled or cfg.display.backend.strip().lower() == "headless":
            return "Display deshabilitado/headless en config"
        return (
            f"Estilo config: {_text(cfg.display.face_style)} · "
            f"Display activo en Lab: {NO_AVAILABLE} desde serve"
        )
    return f"Estado en vivo de Lab: {NO_AVAILABLE} desde serve"


def _mode_policy_label(tool: Tool, mode: SocialMode) -> str:
    if mode not in tool.allowed_modes:
        return f"Bloqueada en modo {mode.value}"
    if mode in {SocialMode.SHOP, SocialMode.PUBLIC} and tool.privacy_level == PrivacyLevel.PRIVATE:
        return f"Bloqueada por privacidad en modo {mode.value}"
    return f"Permitida en modo {mode.value}"


def tools_context(cfg: AILENConfig) -> dict[str, str]:
    """Build template context for ``tools.html`` strictly from real config and contracts."""
    provider_raw = cfg.network.web_search_provider
    provider_norm = provider_raw.strip().lower()
    region_raw = cfg.network.web_search_region
    region_norm = region_raw.strip().lower()
    outbound_enabled = bool(cfg.network.outbound_web_enabled)
    social_mode = cfg.social.default_mode

    search_provider = _build_search_provider(cfg)
    registry = _build_tool_registry(cfg, search_provider)
    cap_registry = CapabilityRegistry(
        registry,
        network_access_allowed=outbound_enabled,
    )
    cap_map = {item.key: item for item in cap_registry.snapshot()}
    search_cap = cap_map.get("tool.web_search")
    search_cap_available = bool(search_cap and search_cap.available)

    if not outbound_enabled:
        outbound_status = "Red saliente deshabilitada"
        outbound_pill_class = "warn"
    elif provider_norm == "none":
        outbound_status = "Red habilitada · Búsqueda desactivada"
        outbound_pill_class = "warn"
    elif search_cap_available:
        outbound_status = "Red y proveedor configurados"
        outbound_pill_class = "ok"
    else:
        outbound_status = "Proveedor no disponible"
        outbound_pill_class = "warn"

    rows_html: list[str] = []
    for tool in registry.list_tools():
        allowed_modes = ", ".join(sorted(m.value for m in tool.allowed_modes))
        rows_html.append(
            render(
                "tools_row.html",
                class_name=type(tool).__name__,
                tool_name=tool.name,
                description=tool.description,
                allowed_modes=allowed_modes,
                privacy_level=tool.privacy_level.value,
                timeout=f"{tool.timeout_seconds:g}s",
                mode_policy=_mode_policy_label(tool, social_mode),
                config_availability=_tool_config_availability(
                    tool,
                    cfg,
                    search_cap_available=search_cap_available,
                ),
                contract_status=CONTRACT_IMPLEMENTED,
            )
        )

    max_kib = DEFAULT_MAX_BYTES // 1024
    ssrf_detail = (
        f"WebFetchPolicy en código: solo HTTPS, bloqueo de loopback/RFC1918/link-local, "
        f"límite de {max_kib} KiB y máximo {DEFAULT_MAX_REDIRECTS} redirecciones."
    )

    return {
        "csrf": "",
        "outbound_status": outbound_status,
        "outbound_pill_class": outbound_pill_class,
        "chk_web_search": " checked" if outbound_enabled else "",
        "web_search_provider": _text(provider_raw),
        "web_search_region": _text(region_raw),
        "web_search_availability": _web_search_availability(
            cfg,
            cap_available=search_cap_available,
        ),
        "sel_ddgs": " selected" if provider_norm == "ddgs" else "",
        "sel_none": " selected" if provider_norm == "none" else "",
        "sel_reg_ar": " selected" if region_norm == "ar-es" else "",
        "sel_reg_es": " selected" if region_norm == "es-es" else "",
        "sel_reg_wt": " selected" if region_norm == "wt-wt" else "",
        "ssrf_status": CONTRACT_IMPLEMENTED,
        "ssrf_detail": ssrf_detail,
        "live_runtime_status": LIVE_LAB_NOTICE,
        "tool_latency": NO_MEASUREMENT,
        "social_mode": social_mode.value,
        "tools_count": str(len(registry)),
        "tools_rows": "".join(rows_html),
    }

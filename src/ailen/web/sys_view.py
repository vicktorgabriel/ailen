"""Contexto real de la página /sistema, construido sólo desde AILENConfig.

Esta vista no presenta mediciones, latencias ni benchmarks: cada valor sale de
la configuración efectiva o del runtime que entrega el llamador. Lo que no
tiene fuente se declara como ``No disponible`` en lugar de inventarse.
"""

import html

from ailen.core.config import AILENConfig, find_config_path
from ailen.domain.enums import DeviceProfile

NOT_AVAILABLE = "No disponible"


def _text(value: object) -> str:
    """Return an honest, non-empty string for a configuration value."""
    if value is None:
        return NOT_AVAILABLE
    text = str(value).strip()
    return text or NOT_AVAILABLE


def _profile_options(current: DeviceProfile) -> str:
    """Render the allowlisted DeviceProfile values, selecting the effective one."""
    options: list[str] = []
    for profile in DeviceProfile:
        value = profile.value
        selected = " selected" if profile == current else ""
        options.append(
            f'<option value="{html.escape(value, quote=True)}"{selected}>'
            f"{html.escape(value)}</option>"
        )
    return "".join(options)


def _config_path() -> str:
    """Return the configuration file actually found by the core loader."""
    path = find_config_path()
    return str(path) if path is not None else NOT_AVAILABLE


def system_context(cfg: AILENConfig, runtime_node_id: str) -> dict[str, str]:
    """Return every variable used by ``system.html``.

    ``csrf`` is returned empty on purpose: the HTTP layer must replace it with
    the real session token before rendering. User-controlled values are escaped
    by the template renderer; ``profile_options`` is the only raw HTML and is
    built from allowlisted ``DeviceProfile`` values escaped with ``html.escape``.
    """
    return {
        "csrf": "",
        "node_name": _text(cfg.node.name),
        "profile_options": _profile_options(cfg.node.profile),
        "node_id": _text(runtime_node_id),
        "web_port": str(cfg.web.port),
        "config_path": _config_path(),
        "db_path": _text(cfg.memory.sqlite_path),
    }

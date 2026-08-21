"""Tiny template renderer. Sin dependencias externas.

Soporta:
- ``{{ key }}``: sustitución con escape HTML.
- ``{{ raw:key }}``: HTML pre-construido por el servidor (confiable).

No es un motor general; suficiente para el panel skeleton. Si crece,
evaluar motor real vía ADR-006.
"""

import html
import re
from functools import lru_cache
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_PATTERN = re.compile(r"\{\{\s*(raw:)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@lru_cache(maxsize=64)
def _load(name: str) -> str:
    path = _TEMPLATES_DIR / name
    return path.read_text(encoding="utf-8")


def render(template_name: str, **context: object) -> str:
    """Render a template with the given context."""
    template = _load(template_name)

    def _sub(match: re.Match[str]) -> str:
        raw, key = match.group(1), match.group(2)
        value = context.get(key, "")
        if raw:
            return str(value)
        return html.escape(str(value), quote=True)

    return _PATTERN.sub(_sub, template)


def clear_cache() -> None:
    """Drop cached templates (tests/dev reload)."""
    _load.cache_clear()

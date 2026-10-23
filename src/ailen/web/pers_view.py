"""Context for the real personality admin view.

Every value comes from the active ``AILENConfig``. Missing data is shown as
``No disponible`` or ``Sin medición``; no synthetic measurements, latency
figures or commercial names are produced here.
"""

from math import ceil

from ailen.core.config import AILENConfig
from ailen.domain.enums import SocialMode
from ailen.web.templates import render

# Short factual descriptions taken from docs/context/PRODUCT_BEHAVIOR.md.
_SOCIAL_LABELS = {
    SocialMode.WORKSHOP: "WORKSHOP (taller / técnico)",
    SocialMode.SHOP: "SHOP (atención / cordial)",
    SocialMode.HOME: "HOME (hogar / cercano)",
    SocialMode.PUBLIC: "PUBLIC (máxima restricción de memoria)",
    SocialMode.PRIVATE: "PRIVATE (recuerdos privados autorizados)",
    SocialMode.SLEEP: "SLEEP (sin atención)",
}

# (trait id, config attribute, title, low label, high label)
_TRAITS = (
    ("humor", "base_humor", "Humor / Chispa", "Seca / Seria", "Chispeante / Pícara"),
    ("verbosity", "base_verbosity", "Verbosidad / Concisión", "Telegráfica", "Detallada"),
    ("curiosity", "base_curiosity", "Iniciativa / Curiosidad", "Pasiva", "Proactiva"),
    ("patience", "base_patience", "Paciencia / Pedagogía", "Directa", "Muy pedagógica"),
    ("sociability", "base_sociability", "Sociabilidad", "Reservada", "Muy sociable"),
    ("formality", "base_formality", "Formalidad", "Informal", "Formal"),
    ("expressiveness", "base_expressiveness", "Expresividad", "Contenida", "Muy expresiva"),
)

_SIMULATOR_DETAIL = (
    "El endpoint /api/personality/simulate responde 501: el panel no envía "
    "personalidad ni historial a proveedores. La previsualización debe "
    "ejecutarse desde el pipeline de conversación de Core."
)


def _text(value: str) -> str:
    cleaned = value.strip()
    return cleaned or "No disponible"


def _number(value: float) -> str:
    """Format a config number without inventing precision."""
    return f"{value:g}"


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _social_options(selected: SocialMode) -> str:
    return "".join(
        render(
            "pers_social_option.html",
            value=mode.value,
            label=_SOCIAL_LABELS.get(mode, mode.value),
            selected=" selected" if mode == selected else "",
        )
        for mode in SocialMode
    )


def _trait_sliders(cfg: AILENConfig) -> str:
    personality = cfg.personality
    return "".join(
        render(
            "pers_trait.html",
            trait_id=trait_id,
            field=attribute,
            title=title,
            low_label=low_label,
            high_label=high_label,
            value=_number(getattr(personality, attribute)),
            value_pct=_percent(getattr(personality, attribute)),
        )
        for trait_id, attribute, title, low_label, high_label in _TRAITS
    )


def personality_context(cfg: AILENConfig) -> dict[str, str]:
    """Return every template value sourced from ``cfg`` (CSRF comes from caller)."""
    cooldown = cfg.social.greeting_cooldown_seconds
    return {
        "display_name": _text(cfg.identity.display_name),
        "node_name": _text(cfg.node.name),
        "node_profile": cfg.node.profile.value,
        "social_mode_options": _social_options(cfg.social.default_mode),
        "val_desc": cfg.personality.description,
        "chk_auto_greet": " checked" if cfg.social.auto_greeting_enabled else "",
        "val_greet_cd": _number(cooldown),
        "val_greet_cd_max": str(max(600, ceil(cooldown))),
        "trait_sliders": _trait_sliders(cfg),
        "memory_path": _text(cfg.memory.sqlite_path),
        "memory_fts": "FTS habilitado" if cfg.memory.fts_enabled else "FTS deshabilitado",
        "memory_retention": f"{cfg.memory.retention_days} días",
        "evolution_state": (
            "Habilitada" if cfg.personality.evolution_enabled else "Deshabilitada"
        ),
        "evolution_rate": _number(cfg.personality.evolution_rate),
        "simulator_status": "No disponible",
        "simulator_detail": _SIMULATOR_DETAIL,
    }

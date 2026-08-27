"""Personality boundaries and safety constraints for AILEN.

Ensures that dynamic personality traits and evolution can only influence style,
tone, and bounded initiative without ever altering system security, tool permissions,
cloud budgets, or privacy rules.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("ailen.core.personality")

# Allowed mutable trait fields and their valid ranges [min, max]
ALLOWED_TRAIT_RANGES: dict[str, tuple[float, float]] = {
    "humor": (0.0, 1.0),
    "formality": (0.0, 1.0),
    "curiosity": (0.0, 1.0),
    "initiative": (0.0, 1.0),
    "verbosity": (0.0, 1.0),
    "patience": (0.0, 1.0),
    "expressiveness": (0.0, 1.0),
}

# Forbidden attributes that personality must never access or modify
FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset({
    "permissions",
    "allowed_tools",
    "privacy_level",
    "privacy_scope",
    "cloud_budget",
    "network_access",
    "shell_access",
    "security_rules",
    "admin_password",
    "api_keys",
    "system_commands",
})


@dataclass
class PersonalityTraits:
    """Safe, bounded stylistic traits for the assistant personality."""
    humor: float = 0.5
    formality: float = 0.5
    curiosity: float = 0.5
    initiative: float = 0.5
    verbosity: float = 0.5
    patience: float = 0.5
    expressiveness: float = 0.5

    def to_dict(self) -> dict[str, float]:
        """Convert traits to dictionary."""
        return {
            "humor": self.humor,
            "formality": self.formality,
            "curiosity": self.curiosity,
            "initiative": self.initiative,
            "verbosity": self.verbosity,
            "patience": self.patience,
            "expressiveness": self.expressiveness,
        }


class PersonalityBoundary:
    """Enforces absolute security boundaries over personality changes."""

    @staticmethod
    def is_trait_allowed(trait_name: str) -> bool:
        """Check whether a trait name is a valid stylistic parameter."""
        return trait_name in ALLOWED_TRAIT_RANGES

    @staticmethod
    def is_forbidden(key: str) -> bool:
        """Check whether an attribute is strictly forbidden for personality influence."""
        return key.lower() in FORBIDDEN_ATTRIBUTES

    @classmethod
    def clamp_trait(cls, trait_name: str, value: float) -> float:
        """Clamp a trait value to its strictly defined safe range."""
        if trait_name not in ALLOWED_TRAIT_RANGES:
            raise ValueError(f"Unknown trait: {trait_name}")
        min_v, max_v = ALLOWED_TRAIT_RANGES[trait_name]
        return max(min_v, min(max_v, float(value)))

    @classmethod
    def sanitize_delta(cls, delta: dict[str, Any]) -> dict[str, float]:
        """Sanitize an incoming personality evolution delta.
        
        Ignores or strips forbidden keys and clamps allowed traits.
        """
        sanitized: dict[str, float] = {}
        for key, value in delta.items():
            if cls.is_forbidden(key):
                # Strictly reject / strip security-sensitive attributes
                continue
            if key in ALLOWED_TRAIT_RANGES:
                try:
                    sanitized[key] = cls.clamp_trait(key, float(value))
                except (ValueError, TypeError):
                    continue
        return sanitized

    @classmethod
    def apply_delta(cls, current: PersonalityTraits, delta: dict[str, Any]) -> PersonalityTraits:
        """Produce updated traits by safely applying a delta within boundaries."""
        sanitized = cls.sanitize_delta(delta)
        current_dict = current.to_dict()
        for k, v in sanitized.items():
            current_dict[k] = v
        return PersonalityTraits(**current_dict)


@dataclass(frozen=True)
class PersonalityFeedback:
    """Deterministic result of an explicit user style preference."""

    trait: str
    value: float
    message: str


class PersonalityService:
    """Persistent bounded personality profile with slow, safe style adaptation."""

    def __init__(
        self,
        identity_id: str,
        defaults: PersonalityTraits | None = None,
        repository: Any = None,
        enabled: bool = True,
        evolution_rate: float = 1.0,
    ) -> None:
        self.identity_id = identity_id
        self.defaults = defaults or PersonalityTraits()
        self.repository = repository
        self.enabled = enabled
        self.evolution_rate = max(0.0, min(1.0, float(evolution_rate)))
        self._memory_traits: dict[str, float] = {}
        self._interruption_observations = 0

    def current(self) -> PersonalityTraits:
        """Return defaults overlaid by safe persisted values."""
        values = self.defaults.to_dict()
        persisted: dict[str, float] = dict(self._memory_traits)
        if self.repository is not None:
            try:
                persisted.update(self.repository.get_personality_traits(self.identity_id))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not load persisted personality state: %s", exc)
        for key, value in persisted.items():
            if PersonalityBoundary.is_trait_allowed(key):
                values[key] = PersonalityBoundary.clamp_trait(key, value)
        return PersonalityTraits(**values)

    def adjust(self, trait: str, delta: float, reason: str) -> PersonalityFeedback:
        """Apply one relative style adjustment within the safety boundary."""
        if not PersonalityBoundary.is_trait_allowed(trait):
            raise ValueError(f"Unknown trait: {trait}")
        current = self.current()
        old_value = getattr(current, trait)
        new_value = PersonalityBoundary.clamp_trait(
            trait, old_value + float(delta) * self.evolution_rate
        )
        self._memory_traits[trait] = new_value
        if self.repository is not None:
            try:
                self.repository.set_personality_trait(
                    identity_id=self.identity_id,
                    trait_name=trait,
                    trait_value=new_value,
                    reason=reason,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not persist personality feedback: %s", exc)
        return PersonalityFeedback(trait=trait, value=new_value, message=self._feedback_message(trait, delta))

    def apply_explicit_feedback(self, text: str) -> PersonalityFeedback | None:
        """Learn only unmistakable global style requests, never topical wording."""
        if not self.enabled:
            return None
        import unicodedata

        clean = " ".join((text or "").lower().strip().split())
        clean = "".join(
            ch for ch in unicodedata.normalize("NFD", clean)
            if unicodedata.category(ch) != "Mn"
        )
        words = set(clean.split())
        if "formal" in words and "informal" in words:
            return None

        patterns: tuple[tuple[tuple[str, ...], str, float], ...] = (
            (("habla mas informal", "hablar mas informal", "ser mas informal", "se mas informal", "quiero que seas mas informal", "menos formal"), "formality", -0.15),
            (("habla mas formal", "se mas formal", "quiero que seas mas formal"), "formality", 0.15),
            (("responde mas corto", "responder mas corto", "responde mas breve", "responder mas breve", "respuestas mas cortas", "quiero respuestas mas cortas", "se mas breve"), "verbosity", -0.15),
            (("responde mas detallado", "quiero respuestas mas detalladas", "se mas detallado"), "verbosity", 0.15),
            (("hace mas chistes", "usa mas humor", "se mas gracioso"), "humor", 0.15),
            (("hace menos chistes", "usa menos humor", "menos chistes"), "humor", -0.15),
            (("se mas curioso", "pregunta un poco mas", "pregunta mas cuando sirva"), "curiosity", 0.15),
            (("no preguntes tanto", "hace menos preguntas"), "curiosity", -0.15),
            (("toma mas iniciativa", "propone mas", "adelantate un poco mas"), "initiative", 0.15),
            (("toma menos iniciativa", "no te adelantes tanto", "propone menos"), "initiative", -0.15),
            (("se mas expresivo", "mostra mas expresividad"), "expressiveness", 0.15),
            (("se menos expresivo", "mostra menos expresividad"), "expressiveness", -0.15),
        )
        for markers, trait, delta in patterns:
            if any(marker in clean for marker in markers):
                return self.adjust(trait=trait, delta=delta, reason=text.strip())
        return None

    def observe_user_style(self, text: str) -> None:
        """Slowly mirror harmless conversational style while preserving the preset identity."""
        if not self.enabled or not text.strip():
            return
        import unicodedata

        clean = " ".join(text.lower().strip().split())
        clean = "".join(
            ch for ch in unicodedata.normalize("NFD", clean)
            if unicodedata.category(ch) != "Mn"
        )
        # Do not learn a regional filler from a single utterance. Automatic
        # evolution is deliberately weak; explicit feedback remains authoritative.
        if any(marker in clean for marker in ("jaja", "jeje", "jajaja", "me hiciste reir")):
            self._nudge_from_observation("humor", 0.004, "observed playful conversation")
        if any(marker in clean for marker in ("por favor", "podrias", "podrias explicarme")):
            self._nudge_from_observation("patience", 0.002, "observed deliberate conversation")

    def observe_interruption(self) -> None:
        """Adapt only after repeated interruptions, avoiding one noisy event changing identity."""
        if not self.enabled:
            return
        self._interruption_observations += 1
        if self._interruption_observations < 3:
            return
        self._interruption_observations = 0
        self._nudge_from_observation("verbosity", -0.010, "repeated spoken response interruptions")

    def _nudge_from_observation(self, trait: str, delta: float, reason: str) -> None:
        current = self.current()
        default_value = getattr(self.defaults, trait)
        lower = max(0.0, default_value - 0.25)
        upper = min(1.0, default_value + 0.25)
        next_value = round(
            max(lower, min(upper, getattr(current, trait) + delta * self.evolution_rate)),
            6,
        )
        if abs(next_value - getattr(current, trait)) < 1e-9:
            return
        self._memory_traits[trait] = next_value
        if self.repository is not None:
            try:
                self.repository.set_personality_trait(
                    identity_id=self.identity_id,
                    trait_name=trait,
                    trait_value=next_value,
                    reason=reason,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not persist observed personality adaptation: %s", exc)

    def prompt_style(self) -> str:
        """Encode evolving traits compactly so history keeps most of the context budget."""
        traits = self.current()
        tone = (
            "informal y rioplatense"
            if traits.formality <= 0.35
            else "natural y cuidado"
            if traits.formality <= 0.7
            else "formal y preciso"
        )
        length = (
            "respuestas breves y fluidas"
            if traits.verbosity <= 0.3
            else "conversacional"
            if traits.verbosity <= 0.5
            else "detallada cuando aporte"
        )
        parts = [f"Estilo: {tone}; {length}"]
        if traits.humor >= 0.55:
            parts.append("humor sólo si encaja")
        if traits.curiosity >= 0.65:
            parts.append("curiosidad sin preguntar por rutina")
        if traits.initiative >= 0.65:
            parts.append("proponé el siguiente paso sólo si sirve")
        if traits.expressiveness >= 0.65:
            parts.append("emoción visible según el turno")
        parts.append("variá aperturas y mantené continuidad")
        return "; ".join(parts) + "."

    @staticmethod
    def _feedback_message(trait: str, delta: float) -> str:
        direction = delta > 0
        messages = {
            "formality": "Listo, voy a hablar de forma más formal." if direction else "Listo, voy a hablar más informal y natural.",
            "verbosity": "Listo, voy a desarrollar más las respuestas." if direction else "Listo, voy a responder más corto y directo.",
            "humor": "Listo, puedo sumar un poco más de humor." if direction else "Listo, voy a usar menos humor.",
            "curiosity": "Listo, voy a mostrar un poco más de curiosidad cuando sirva." if direction else "Listo, voy a hacer menos preguntas.",
            "initiative": "Listo, voy a tomar un poco más de iniciativa." if direction else "Listo, voy a esperar más antes de proponer pasos.",
            "expressiveness": "Listo, voy a ser un poco más expresivo." if direction else "Listo, voy a ser más neutro.",
        }
        return messages.get(trait, "Listo, ajusté ese aspecto de mi estilo.")

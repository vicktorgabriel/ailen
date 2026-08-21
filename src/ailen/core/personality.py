"""Personality boundaries and safety constraints for AILEN.

Ensures that dynamic personality traits and evolution can only influence style,
tone, and bounded initiative without ever altering system security, tool permissions,
cloud budgets, or privacy rules.
"""

from dataclasses import dataclass
from typing import Any

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

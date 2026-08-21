"""Deterministic privacy policies for AILEN memory and social modes.

Enforces hard boundaries outside LLM reasoning so private memories are never
spontaneously exposed in PUBLIC or SHOP modes regardless of personality evolution.
"""

from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.domain.models import BusinessFact, MemoryItem

# Canonical allowed scopes per social mode.
# Immutable definition outside any dynamic or LLM-influenced structure.
_ALLOWED_SCOPES_BY_MODE: dict[SocialMode, frozenset[PrivacyLevel]] = {
    SocialMode.PUBLIC: frozenset({PrivacyLevel.PUBLIC}),
    SocialMode.SHOP: frozenset({PrivacyLevel.PUBLIC}),
    SocialMode.SLEEP: frozenset({PrivacyLevel.PUBLIC}),
    SocialMode.HOME: frozenset({PrivacyLevel.PUBLIC, PrivacyLevel.RESTRICTED, PrivacyLevel.PRIVATE}),
    SocialMode.WORKSHOP: frozenset({PrivacyLevel.PUBLIC, PrivacyLevel.RESTRICTED, PrivacyLevel.PRIVATE}),
    SocialMode.PRIVATE: frozenset({PrivacyLevel.PUBLIC, PrivacyLevel.RESTRICTED, PrivacyLevel.PRIVATE}),
}


class SocialPrivacyPolicy:
    """Deterministic privacy enforcement service for memory retrieval and facts."""

    @staticmethod
    def get_allowed_scopes(mode: SocialMode) -> frozenset[PrivacyLevel]:
        """Return the immutable set of allowed PrivacyLevels for a given SocialMode."""
        return _ALLOWED_SCOPES_BY_MODE.get(mode, frozenset({PrivacyLevel.PUBLIC}))

    @classmethod
    def is_scope_allowed(cls, scope: PrivacyLevel, mode: SocialMode) -> bool:
        """Check if a specific privacy scope is accessible in the given social mode."""
        return scope in cls.get_allowed_scopes(mode)

    @classmethod
    def filter_memories(
        cls,
        memories: list[MemoryItem],
        mode: SocialMode,
    ) -> list[MemoryItem]:
        """Filter memory items strictly according to social mode privacy boundaries."""
        allowed_scopes = cls.get_allowed_scopes(mode)
        return [mem for mem in memories if mem.scope in allowed_scopes]

    @classmethod
    def filter_business_facts(
        cls,
        facts: list[BusinessFact],
        mode: SocialMode,
    ) -> list[BusinessFact]:
        """Filter business facts.
        
        In PUBLIC and SHOP modes, only facts with is_public=True are accessible.
        In HOME, WORKSHOP, and PRIVATE modes, internal facts can be accessed.
        """
        if mode in (SocialMode.PUBLIC, SocialMode.SHOP, SocialMode.SLEEP):
            return [fact for fact in facts if fact.is_public]
        return list(facts)

    @classmethod
    def sanitize_context_for_mode(
        cls,
        memories: list[MemoryItem],
        facts: list[BusinessFact],
        mode: SocialMode,
    ) -> tuple[list[MemoryItem], list[BusinessFact]]:
        """Sanitize both memories and business facts for safe consumption in a given mode."""
        safe_memories = cls.filter_memories(memories, mode)
        safe_facts = cls.filter_business_facts(facts, mode)
        return safe_memories, safe_facts

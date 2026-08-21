"""Unit tests for deterministic SocialPrivacyPolicy."""

from ailen.core.privacy import SocialPrivacyPolicy
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.domain.models import BusinessFact, MemoryItem


def create_sample_memories() -> list[MemoryItem]:
    return [
        MemoryItem(
            memory_id="mem-pub",
            category="general",
            content="El local abre de 9 a 18 hs.",
            scope=PrivacyLevel.PUBLIC,
        ),
        MemoryItem(
            memory_id="mem-rst",
            category="supplier",
            content="El proveedor entrega los martes.",
            scope=PrivacyLevel.RESTRICTED,
        ),
        MemoryItem(
            memory_id="mem-prv",
            category="private_notes",
            content="La contraseña del router del taller es 1234.",
            scope=PrivacyLevel.PRIVATE,
        ),
    ]


def create_sample_facts() -> list[BusinessFact]:
    return [
        BusinessFact(
            fact_id="fact-1",
            key="horarios",
            category="info",
            value="Lunes a Viernes 9 a 18",
            is_public=True,
        ),
        BusinessFact(
            fact_id="fact-2",
            key="costo_mayorista",
            category="finanzas",
            value="Margen 45%",
            is_public=False,
        ),
    ]


def test_public_mode_blocks_private_and_restricted_memories() -> None:
    memories = create_sample_memories()
    filtered = SocialPrivacyPolicy.filter_memories(memories, SocialMode.PUBLIC)

    assert len(filtered) == 1
    assert filtered[0].memory_id == "mem-pub"
    assert filtered[0].scope == PrivacyLevel.PUBLIC


def test_shop_mode_blocks_private_and_restricted_memories() -> None:
    memories = create_sample_memories()
    filtered = SocialPrivacyPolicy.filter_memories(memories, SocialMode.SHOP)

    assert len(filtered) == 1
    assert filtered[0].memory_id == "mem-pub"
    assert filtered[0].scope == PrivacyLevel.PUBLIC


def test_home_and_workshop_modes_allow_private_memories() -> None:
    memories = create_sample_memories()

    workshop_filtered = SocialPrivacyPolicy.filter_memories(memories, SocialMode.WORKSHOP)
    assert len(workshop_filtered) == 3

    home_filtered = SocialPrivacyPolicy.filter_memories(memories, SocialMode.HOME)
    assert len(home_filtered) == 3

    private_filtered = SocialPrivacyPolicy.filter_memories(memories, SocialMode.PRIVATE)
    assert len(private_filtered) == 3


def test_business_facts_filtering_per_mode() -> None:
    facts = create_sample_facts()

    pub_facts = SocialPrivacyPolicy.filter_business_facts(facts, SocialMode.PUBLIC)
    assert len(pub_facts) == 1
    assert pub_facts[0].key == "horarios"

    shop_facts = SocialPrivacyPolicy.filter_business_facts(facts, SocialMode.SHOP)
    assert len(shop_facts) == 1
    assert shop_facts[0].key == "horarios"

    workshop_facts = SocialPrivacyPolicy.filter_business_facts(facts, SocialMode.WORKSHOP)
    assert len(workshop_facts) == 2


def test_sanitize_context_for_mode() -> None:
    memories = create_sample_memories()
    facts = create_sample_facts()

    safe_mems, safe_facts = SocialPrivacyPolicy.sanitize_context_for_mode(
        memories, facts, SocialMode.PUBLIC
    )
    assert len(safe_mems) == 1
    assert safe_mems[0].scope == PrivacyLevel.PUBLIC
    assert len(safe_facts) == 1
    assert safe_facts[0].is_public is True


def test_is_scope_allowed_deterministic() -> None:
    assert SocialPrivacyPolicy.is_scope_allowed(PrivacyLevel.PUBLIC, SocialMode.PUBLIC) is True
    assert SocialPrivacyPolicy.is_scope_allowed(PrivacyLevel.RESTRICTED, SocialMode.PUBLIC) is False
    assert SocialPrivacyPolicy.is_scope_allowed(PrivacyLevel.PRIVATE, SocialMode.PUBLIC) is False

    assert SocialPrivacyPolicy.is_scope_allowed(PrivacyLevel.PUBLIC, SocialMode.SHOP) is True
    assert SocialPrivacyPolicy.is_scope_allowed(PrivacyLevel.PRIVATE, SocialMode.SHOP) is False

    assert SocialPrivacyPolicy.is_scope_allowed(PrivacyLevel.PRIVATE, SocialMode.WORKSHOP) is True
    assert SocialPrivacyPolicy.is_scope_allowed(PrivacyLevel.PRIVATE, SocialMode.HOME) is True
    assert SocialPrivacyPolicy.is_scope_allowed(PrivacyLevel.PRIVATE, SocialMode.PRIVATE) is True

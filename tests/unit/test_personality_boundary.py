"""Unit tests for PersonalityBoundary security and style constraints."""

from ailen.core.personality import PersonalityBoundary, PersonalityService, PersonalityTraits


def test_personality_traits_defaults() -> None:
    traits = PersonalityTraits()
    assert traits.humor == 0.5
    assert traits.formality == 0.5
    assert traits.initiative == 0.5


def test_sanitize_delta_clamps_valid_traits() -> None:
    raw_delta = {
        "humor": 1.5,        # exceeds 1.0 -> should clamp to 1.0
        "formality": -0.5,   # below 0.0 -> should clamp to 0.0
        "curiosity": 0.8,    # within range -> 0.8
    }
    sanitized = PersonalityBoundary.sanitize_delta(raw_delta)

    assert sanitized["humor"] == 1.0
    assert sanitized["formality"] == 0.0
    assert sanitized["curiosity"] == 0.8


def test_sanitize_delta_strips_forbidden_security_attributes() -> None:
    malicious_delta = {
        "humor": 0.7,
        "permissions": ["all", "root"],
        "allowed_tools": ["shell_exec", "rm_rf"],
        "privacy_level": "PUBLIC",
        "cloud_budget": 999999.0,
        "admin_password": "new_password",
        "shell_access": True,
    }
    sanitized = PersonalityBoundary.sanitize_delta(malicious_delta)

    assert "humor" in sanitized
    assert "permissions" not in sanitized
    assert "allowed_tools" not in sanitized
    assert "privacy_level" not in sanitized
    assert "cloud_budget" not in sanitized
    assert "admin_password" not in sanitized
    assert "shell_access" not in sanitized


def test_apply_delta_safely() -> None:
    initial = PersonalityTraits(humor=0.4, formality=0.6)
    delta = {
        "humor": 0.9,
        "forbidden_key": "injected",
    }
    updated = PersonalityBoundary.apply_delta(initial, delta)

    assert updated.humor == 0.9
    assert updated.formality == 0.6  # Unchanged
    assert not hasattr(updated, "forbidden_key")

def test_personality_service_explicit_feedback_is_conservative() -> None:
    service = PersonalityService(
        identity_id="test",
        defaults=PersonalityTraits(formality=0.5, verbosity=0.5),
    )
    assert service.apply_explicit_feedback("explicá más este tema") is None

    feedback = service.apply_explicit_feedback("Quiero que seas más informal")
    assert feedback is not None
    assert feedback.trait == "formality"
    assert service.current().formality == 0.35


def test_personality_prompt_style_reflects_traits() -> None:
    service = PersonalityService(
        identity_id="test",
        defaults=PersonalityTraits(
            formality=0.2,
            verbosity=0.3,
            humor=0.7,
            curiosity=0.7,
            initiative=0.7,
            patience=0.7,
            expressiveness=0.7,
        ),
    )
    prompt = service.prompt_style()
    assert "informal" in prompt
    assert "breves" in prompt
    assert "humor" in prompt
    assert "curiosidad" in prompt
    assert "siguiente paso" in prompt

def test_personality_service_tolerates_asr_dropped_words_but_rejects_conflict() -> None:
    service = PersonalityService(
        identity_id="test",
        defaults=PersonalityTraits(verbosity=0.5, formality=0.5),
    )
    feedback = service.apply_explicit_feedback("de responder más corto")
    assert feedback is not None
    assert feedback.trait == "verbosity"
    assert service.current().verbosity == 0.35

    assert service.apply_explicit_feedback("creo que sea más formal más informal") is None
    assert service.current().formality == 0.5

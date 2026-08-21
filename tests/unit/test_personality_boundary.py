"""Unit tests for PersonalityBoundary security and style constraints."""

from ailen.core.personality import PersonalityBoundary, PersonalityTraits


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

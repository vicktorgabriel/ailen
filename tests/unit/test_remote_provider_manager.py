"""Contracts for configurable remote AI providers and dynamic routing."""

from __future__ import annotations

import warnings

from ailen.ai.router import ROUTE_LOCAL, RouteRequest, RuleBasedRouter
from ailen.core.config import (
    AILENConfig,
    ConfigMigrationWarning,
    RemoteProviderConfig,
    dump_config_toml,
    load_config_from_dict,
    remote_provider_presets,
    validate_config,
)
from ailen.domain.enums import DeviceProfile, PrivacyLevel


def test_default_remote_presets_are_international_and_catalog_truthful() -> None:
    presets = remote_provider_presets()

    assert presets["minimax"].endpoint == "https://api.minimax.io/v1"
    assert presets["kimi"].endpoint == "https://api.moonshot.ai/v1"
    assert all("api.minimaxi.com" not in preset.endpoint for preset in presets.values())
    assert not any(provider_id.endswith("_china") for provider_id in presets)

    assert presets["openai"].catalog_mode == "live"
    for provider_id in ("anthropic", "deepseek", "kimi", "minimax"):
        assert presets[provider_id].catalog_mode == "manual"


def test_retired_providers_migrate_to_auto_without_runtime_aliases() -> None:
    raw = {
        "schema_version": 1,
        "ai": {
            "provider": "antigravity",
            "allow_cloud": True,
            "antigravity": {"enabled": True, "model": "retired-model"},
            "opencode": {"enabled": True, "model": "retired-free-model"},
        },
    }

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        config = load_config_from_dict(raw)

    assert config.schema_version == 3
    assert config.ai.provider == "auto"
    assert config.ai.allow_remote is True
    assert not hasattr(config.ai, "antigravity")
    assert not hasattr(config.ai, "opencode")
    assert any(issubclass(item.category, ConfigMigrationWarning) for item in seen)


def test_legacy_cloud_migrates_once_to_named_remote_provider() -> None:
    raw = {
        "schema_version": 1,
        "ai": {
            "provider": "cloud",
            "cloud": {
                "enabled": True,
                "provider": "openai_compatible",
                "endpoint": "https://example.invalid/v1",
                "model": "manual-model",
                "api_key_env": "AILEN_LEGACY_KEY",
                "api_key_file": "legacy_key",
                "priority": 17,
            },
        },
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConfigMigrationWarning)
        config = load_config_from_dict(raw)

    migrated = config.ai.remote.providers["legacy_cloud"]
    assert config.ai.provider == "remote:legacy_cloud"
    assert migrated.enabled is True
    assert migrated.protocol == "openai_chat"
    assert migrated.endpoint == "https://example.invalid/v1"
    assert migrated.model == "manual-model"
    assert migrated.api_key_env == "AILEN_LEGACY_KEY"
    assert migrated.priority == 17


def test_remote_provider_mapping_round_trips_without_fixed_model_catalog() -> None:
    config = AILENConfig()
    config.ai.provider = "remote:primary"
    config.ai.allow_sanitized_external_prompts = True
    config.ai.remote.providers["primary"] = RemoteProviderConfig(
        enabled=True,
        preset="openai",
        protocol="openai_responses",
        endpoint="https://api.example.invalid/v1",
        model="operator-selected-model",
        api_key_env="AILEN_PRIMARY_KEY",
        api_key_file="remote_primary_key",
        priority=7,
        catalog_mode="live",
        qualification_status="tested",
    )

    text = dump_config_toml(config)
    loaded = load_config_from_dict(__import__("tomllib").loads(text))

    assert "[ai.remote.providers.primary]" in text
    assert "antigravity" not in text
    assert "opencode" not in text
    assert loaded.ai.remote.providers["primary"].model == "operator-selected-model"
    assert validate_config(loaded) == []


def test_router_honors_explicit_named_remote_then_dynamic_priority_fallbacks() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            intent="chat",
            privacy_level=PrivacyLevel.PRIVATE,
            internet_available=True,
            external_allowed=True,
            allow_sanitized_external_prompts=True,
            local_backend_available=True,
            preferred_backend="remote:anthropic",
            remote_backends=("remote:openai", "remote:anthropic", "remote:deepseek"),
            backend_priorities={
                "remote:deepseek": 5,
                "remote:anthropic": 10,
                "remote:openai": 20,
                "local": 50,
            },
        )
    )

    assert plan.primary_backend == "remote:anthropic"
    assert plan.fallback_backends == ["remote:deepseek", "remote:openai", ROUTE_LOCAL]
    assert plan.privacy_decision == "SANITIZED_REMOTE_CURRENT_TURN_ONLY"


def test_auto_voice_uses_low_latency_local_and_only_realtime_remote_fallbacks() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            intent="chat",
            input_modality="voice",
            profile=DeviceProfile.HYBRID,
            privacy_level=PrivacyLevel.PRIVATE,
            internet_available=True,
            external_allowed=True,
            allow_sanitized_external_prompts=True,
            local_backend_available=True,
            preferred_backend="auto",
            remote_backends=("remote:slow", "remote:fast"),
            realtime_eligible_backends={"remote:slow": False, "remote:fast": True},
            backend_priorities={"remote:slow": 1, "remote:fast": 2},
        )
    )

    assert plan.primary_backend == ROUTE_LOCAL
    assert plan.fallback_backends == ["remote:fast", "remote:slow"]
    assert plan.reason_code == "AUTO_VOICE_LOW_LATENCY"


def test_budget_blocked_remote_is_excluded_without_disabling_other_remotes() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            intent="chat",
            complexity="high",
            privacy_level=PrivacyLevel.PUBLIC,
            internet_available=True,
            external_allowed=True,
            local_backend_available=True,
            remote_backends=("remote:openai", "remote:anthropic"),
            budget_blocked_backends=frozenset({"remote:openai"}),
            backend_priorities={"remote:openai": 1, "remote:anthropic": 2},
        )
    )

    assert plan.primary_backend == "remote:anthropic"
    assert "remote:openai" not in plan.fallback_backends
    assert plan.fallback_backends == [ROUTE_LOCAL]

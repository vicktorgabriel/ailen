"""Provider registry tests for current named remote protocols."""

from ailen.ai.providers import ModelCatalogSource, ProviderRegistry
from ailen.ai.remote_backend import (
    AnthropicMessagesBackend,
    OpenAiResponsesBackend,
    build_remote_backend,
)
from ailen.core.config import RemoteProviderConfig, remote_provider_presets


def test_remote_presets_have_no_hardcoded_live_model_or_shared_secret() -> None:
    presets = remote_provider_presets()

    assert {"openai", "anthropic", "deepseek", "kimi", "minimax"} <= set(presets)
    assert all(not provider.enabled for provider in presets.values())
    assert all(provider.model == "" for provider in presets.values())
    secret_files = [
        provider.api_key_file
        for provider in presets.values()
        if provider.auth_mode == "api_key" and provider.api_key_file
    ]
    assert len(secret_files) == len(set(secret_files))


def test_protocol_builder_returns_native_adapters_and_truthful_capabilities() -> None:
    responses = build_remote_backend(
        "openai",
        RemoteProviderConfig(
            protocol="openai_responses",
            endpoint="https://api.example/v1",
            model="published-model",
        ),
        api_key="test-key",
    )
    anthropic = build_remote_backend(
        "anthropic",
        RemoteProviderConfig(
            protocol="anthropic_messages",
            endpoint="https://api.example/v1",
            model="published-model",
        ),
        api_key="test-key",
    )

    assert isinstance(responses, OpenAiResponsesBackend)
    assert isinstance(anthropic, AnthropicMessagesBackend)
    assert responses.provider_id == "remote:openai"
    assert anthropic.provider_id == "remote:anthropic"
    assert responses.capabilities().supports_streaming is True
    assert responses.capabilities().supports_tools is False


def test_manual_model_catalog_is_never_presented_as_live() -> None:
    backend = build_remote_backend(
        "custom",
        RemoteProviderConfig(
            protocol="openai_chat",
            endpoint="https://api.example/v1",
            model="operator-model",
            catalog_mode="manual",
        ),
        api_key="test-key",
    )

    catalog = backend.model_catalog()

    assert catalog.models == ["operator-model"]
    assert catalog.source is ModelCatalogSource.CONFIGURED


def test_provider_registry_uses_observable_named_route_ids() -> None:
    backend = build_remote_backend(
        "deepseek",
        RemoteProviderConfig(
            protocol="openai_chat",
            endpoint="https://api.example/v1",
            model="provider-model",
        ),
        api_key="test-key",
    )
    registry = ProviderRegistry()
    registry.register(backend)

    assert registry.has("remote:deepseek")
    assert registry.get("remote:deepseek") is backend
    assert registry.get_metadata("remote:deepseek") is not None

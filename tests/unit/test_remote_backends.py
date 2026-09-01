"""Protocol-level tests for remote AI adapters without real network traffic."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from ailen.ai.contracts import AiRequest, ChatMessage
from ailen.ai.providers import ModelCatalogSource
from ailen.ai.remote_backend import (
    AnthropicMessagesBackend,
    OpenAiResponsesBackend,
    build_remote_backend,
)
from ailen.core.config import RemoteProviderConfig
from ailen.domain.enums import ServiceStatus


def _stream_response(lines: list[bytes]) -> MagicMock:
    response = MagicMock()
    response.readline.side_effect = [*lines, b""]
    response.__enter__.return_value = response
    return response


def test_openai_responses_uses_native_stream_and_disables_storage() -> None:
    backend = OpenAiResponsesBackend(
        endpoint="https://api.example.invalid/v1",
        model="chosen-live-model",
        api_key="provider-secret",
        provider_name="remote:openai",
    )
    response = _stream_response(
        [
            b'event: response.output_text.delta\n',
            b'data: {"type":"response.output_text.delta","delta":"Hola"}\n',
            b'event: response.output_text.delta\n',
            b'data: {"type":"response.output_text.delta","delta":" mundo"}\n',
            b'event: response.completed\n',
            b'data: {"type":"response.completed","response":{"model":"chosen-live-model","status":"completed","usage":{"input_tokens":9,"output_tokens":2}}}\n',
        ]
    )
    deltas: list[str] = []

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = backend.generate_stream(
            AiRequest(
                request_id="responses-stream",
                system_context="Minimal public system prompt",
                messages=[ChatMessage(role="user", content="Turno actual")],
            ),
            lambda delta: deltas.append(delta) or True,
        )

    request = urlopen.call_args.args[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.example.invalid/v1/responses"
    assert payload["model"] == "chosen-live-model"
    assert payload["store"] is False
    assert payload["stream"] is True
    assert payload["instructions"] == "Minimal public system prompt"
    assert payload["input"] == [{"role": "user", "content": "Turno actual"}]
    assert deltas == ["Hola", " mundo"]
    assert result.text == "Hola mundo"
    assert result.usage.input_tokens == 9
    assert result.usage.output_tokens == 2
    assert backend.capabilities().supports_tools is False
    assert backend.capabilities().supports_streaming is True


def test_openai_live_catalog_uses_the_official_models_endpoint() -> None:
    backend = OpenAiResponsesBackend(
        endpoint="https://api.openai.com/v1",
        model="operator-selected-model",
        api_key="synthetic-provider-secret",
        provider_name="remote:openai",
        catalog_mode="live",
    )
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"data": [{"id": "model-b"}, {"id": "model-a"}]}
    ).encode("utf-8")
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        catalog = backend.model_catalog()

    request = urlopen.call_args.args[0]
    assert request.full_url == "https://api.openai.com/v1/models"
    assert catalog.source is ModelCatalogSource.LIVE
    assert catalog.models == ["model-a", "model-b"]


def test_manual_catalog_provider_health_does_not_probe_a_generic_models_url() -> None:
    backend = AnthropicMessagesBackend(
        endpoint="https://api.anthropic.com/v1",
        model="operator-selected-model",
        api_key="synthetic-provider-secret",
        provider_name="remote:anthropic",
        catalog_mode="manual",
    )

    with patch("urllib.request.urlopen") as urlopen:
        health = backend.health()

    assert health.status is ServiceStatus.UNKNOWN
    assert "explicit connection test" in health.detail
    urlopen.assert_not_called()


def test_anthropic_messages_parses_real_sse_text_delta() -> None:
    backend = AnthropicMessagesBackend(
        endpoint="https://api.anthropic.invalid/v1",
        model="operator-model",
        api_key="anthropic-secret",
        provider_name="remote:anthropic",
        anthropic_version="2023-06-01",
    )
    response = _stream_response(
        [
            b'event: message_start\n',
            b'data: {"type":"message_start","message":{"model":"operator-model","usage":{"input_tokens":7,"output_tokens":0}}}\n',
            b'event: content_block_delta\n',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Qué "}}\n'.encode(),
            b'event: content_block_delta\n',
            b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"tal"}}\n',
            b'event: message_delta\n',
            b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}\n',
            b'event: message_stop\n',
            b'data: {"type":"message_stop"}\n',
        ]
    )

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = backend.generate_stream(
            AiRequest(
                request_id="anthropic-stream",
                system_context="System",
                messages=[ChatMessage(role="user", content="Hola")],
            ),
            lambda _delta: True,
        )

    request = urlopen.call_args.args[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.anthropic.invalid/v1/messages"
    assert request.headers["X-api-key"] == "anthropic-secret"
    assert request.headers["Anthropic-version"] == "2023-06-01"
    assert payload["system"] == "System"
    assert payload["messages"] == [{"role": "user", "content": "Hola"}]
    assert payload["stream"] is True
    assert result.text == "Qué tal"
    assert result.finish_reason == "end_turn"
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 2


def test_remote_factory_selects_protocol_and_keeps_provider_identity() -> None:
    config = RemoteProviderConfig(
        enabled=True,
        preset="anthropic",
        protocol="anthropic_messages",
        endpoint="https://api.example.invalid/v1",
        model="manual-model",
        api_key_env="AILEN_TEST_ANTHROPIC_KEY",
        api_key_file="test_anthropic_key",
    )

    backend = build_remote_backend("primary", config, api_key="separate-secret")

    assert isinstance(backend, AnthropicMessagesBackend)
    assert backend.provider_name == "remote:primary"
    assert backend.model == "manual-model"

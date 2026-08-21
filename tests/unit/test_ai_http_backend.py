"""Unit tests for generic HTTP backend and specific wrappers."""

import json
from unittest.mock import MagicMock, patch

from ailen.ai.cloud_backend import CloudAiBackend
from ailen.ai.contracts import AiRequest, ChatMessage
from ailen.ai.http_backend import GenericOpenAiBackend
from ailen.ai.lan_backend import LanBrainAiBackend
from ailen.ai.local_backend import LocalAiBackend


def test_generic_openai_backend_generate_success() -> None:
    backend = GenericOpenAiBackend(
        endpoint="http://127.0.0.1:8080/v1",
        model="test-model",
        input_cost_per_million=0.15,
        output_cost_per_million=0.60,
    )

    mock_resp_data = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hola, soy un modelo de prueba."},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        },
    }

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        req = AiRequest(
            request_id="req-1",
            system_context="Sys context",
            messages=[ChatMessage(role="user", content="Hola")],
        )
        resp = backend.generate(req)

        assert resp.text == "Hola, soy un modelo de prueba."
        assert resp.finish_reason == "stop"
        assert resp.usage.input_tokens == 100
        assert resp.usage.output_tokens == 50
        assert resp.usage.estimated_cost is not None
        assert resp.usage.estimated_cost > 0.0


def test_generic_openai_backend_handles_timeout() -> None:
    backend = GenericOpenAiBackend(endpoint="http://127.0.0.1:8080/v1")

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        req = AiRequest(request_id="req-1", messages=[ChatMessage(role="user", content="Hola")])
        resp = backend.generate(req)

        assert resp.text == ""
        assert resp.finish_reason == "timeout"


def test_cloud_backend_missing_key_fails_closed_without_network() -> None:
    backend = CloudAiBackend(
        endpoint="https://example.invalid/v1",
        model="test-model",
        api_key=None,
        api_key_env="AILEN_TEST_MISSING_CLOUD_KEY",
        api_key_file=None,
    )
    req = AiRequest(request_id="req-cloud", messages=[ChatMessage(role="user", content="Hola")])

    with patch("urllib.request.urlopen") as urlopen:
        health = backend.health()
        resp = backend.generate(req)

    assert health.status.value == "DISABLED"
    assert resp.finish_reason == "unreachable"
    urlopen.assert_not_called()


def test_backend_wrappers_initialization() -> None:
    local_b = LocalAiBackend(endpoint="http://127.0.0.1:8080/v1", model="qwen2.5-0.5b")
    assert local_b.is_local is True
    assert local_b.requires_internet is False

    lan_b = LanBrainAiBackend(endpoint="http://192.168.1.50:8080/v1", trusted=True)
    assert lan_b.trusted is True
    assert lan_b.requires_internet is False

    cloud_b = CloudAiBackend(endpoint="https://api.openai.com/v1", model="gpt-4o-mini", api_key="sk-test-123")
    assert cloud_b.api_key == "sk-test-123"
    assert cloud_b.requires_internet is True

"""Unit tests for the lightweight OpenAI-compatible transport."""

import json
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

from ailen.ai.contracts import AiErrorKind, AiRequest, ChatMessage
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


def test_remote_backend_missing_key_fails_closed_without_network() -> None:
    backend = GenericOpenAiBackend(
        endpoint="https://example.invalid/v1",
        model="test-model",
        api_key=None,
        provider_name="remote:test",
        requires_internet=True,
        requires_api_key=True,
    )
    req = AiRequest(request_id="req-cloud", messages=[ChatMessage(role="user", content="Hola")])

    with patch("urllib.request.urlopen") as urlopen:
        health = backend.health()
        resp = backend.generate(req)

    assert health.status.value == "DISABLED"
    assert resp.finish_reason == "error"
    assert resp.error_kind is AiErrorKind.AUTHENTICATION
    urlopen.assert_not_called()


def test_remote_stream_missing_key_fails_closed_without_network() -> None:
    backend = GenericOpenAiBackend(
        endpoint="https://example.invalid/v1",
        model="test-model",
        api_key=None,
        provider_name="remote:test",
        requires_internet=True,
        requires_api_key=True,
    )

    with patch("urllib.request.urlopen") as urlopen:
        response = backend.generate_stream(
            AiRequest(request_id="cloud-stream-missing-key"),
            lambda _delta: True,
        )

    assert response.error_kind is AiErrorKind.AUTHENTICATION
    urlopen.assert_not_called()


def test_backend_wrappers_initialization() -> None:
    local_b = LocalAiBackend(endpoint="http://127.0.0.1:8080/v1", model="qwen2.5-0.5b")
    assert local_b.is_local is True
    assert local_b.requires_internet is False

    lan_b = LanBrainAiBackend(endpoint="http://192.168.1.50:8080/v1", trusted=True)
    assert lan_b.trusted is True
    assert lan_b.requires_internet is False

    remote_b = GenericOpenAiBackend(
        endpoint="https://api.example/v1",
        model="published-model",
        api_key="test-key",
        provider_name="remote:test",
        requires_internet=True,
        requires_api_key=True,
    )
    assert remote_b.api_key == "test-key"
    assert remote_b.requires_internet is True


def test_generic_backend_never_exposes_reasoning_content_as_answer() -> None:
    backend = GenericOpenAiBackend(endpoint="http://127.0.0.1:8080/v1", model="test-model")
    payload = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "reasoning_content": "private hidden reasoning must not be surfaced",
            },
            "finish_reason": "stop",
        }]
    }
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps(payload).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        response = backend.generate(AiRequest(request_id="r-hidden"))

    assert response.text == ""
    assert "private hidden reasoning" not in response.text


def test_generic_openai_backend_streaming_sse() -> None:
    backend = GenericOpenAiBackend(endpoint="https://api.example/v1", model="fast-model")
    lines = [
        b'data: {"model":"fast-model","choices":[{"delta":{"reasoning_content":"hidden"},"finish_reason":null}]}\n',
        b'data: {"model":"fast-model","choices":[{"delta":{"content":"Hola"},"finish_reason":null}]}\n',
        b'data: {"choices":[{"delta":{"content":" mundo"},"finish_reason":null}]}\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
        b'data: {"model":"fast-model","choices":[],"usage":{"prompt_tokens":8,"completion_tokens":3}}\n',
        b'data: [DONE]\n',
        b'',
    ]
    mock_response = MagicMock()
    mock_response.readline.side_effect = lines
    mock_response.__enter__.return_value = mock_response
    deltas: list[str] = []

    with patch("urllib.request.urlopen", return_value=mock_response):
        response = backend.generate_stream(
            AiRequest(
                request_id="stream-1",
                messages=[ChatMessage(role="user", content="Hola")],
            ),
            lambda delta: deltas.append(delta) or True,
        )

    assert response.text == "Hola mundo"
    assert response.finish_reason == "stop"
    assert response.model == "fast-model"
    assert deltas == ["Hola", " mundo"]
    assert response.usage.input_tokens == 8
    assert response.usage.output_tokens == 3
    assert "hidden" not in response.text
    assert backend.capabilities().supports_streaming is True


def test_stream_with_only_reasoning_is_an_invalid_visible_response() -> None:
    backend = GenericOpenAiBackend(endpoint="https://api.example/v1", model="reasoning-model")
    lines = [
        b'data: {"choices":[{"delta":{"reasoning_content":"hidden"},"finish_reason":null}]}\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n',
        b'data: [DONE]\n',
    ]
    response = MagicMock()
    response.readline.side_effect = lines
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response):
        result = backend.generate_stream(AiRequest(request_id="reasoning-only"), lambda _: True)

    assert result.text == ""
    assert result.finish_reason == "length"
    assert result.error_kind is AiErrorKind.INVALID_RESPONSE


def _http_error(code: int, body: str, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    fp = MagicMock()
    fp.read.return_value = body.encode("utf-8")
    return urllib.error.HTTPError(
        url="https://api.example/v1/chat/completions",
        code=code,
        msg="provider error",
        hdrs=headers,
        fp=fp,
    )


def test_http_backend_classifies_rate_limit_and_retry_after() -> None:
    backend = GenericOpenAiBackend(endpoint="https://api.example/v1", model="m1")
    with patch(
        "urllib.request.urlopen",
        side_effect=_http_error(429, '{"error":{"message":"quota exceeded"}}', retry_after="7"),
    ):
        response = backend.generate(AiRequest(request_id="rate-limit"))

    assert response.error_kind is AiErrorKind.RATE_LIMIT
    assert response.retry_after_seconds == 7.0
    assert response.finish_reason == "rate_limited"


def test_http_backend_classifies_authentication_and_invalid_model() -> None:
    backend = GenericOpenAiBackend(endpoint="https://api.example/v1", model="missing")
    with patch(
        "urllib.request.urlopen",
        side_effect=_http_error(401, '{"error":{"message":"invalid API key"}}'),
    ):
        auth = backend.generate(AiRequest(request_id="auth"))
    with patch(
        "urllib.request.urlopen",
        side_effect=_http_error(400, '{"error":{"message":"model missing is not available"}}'),
    ):
        invalid_model = backend.generate(AiRequest(request_id="model"))

    assert auth.error_kind is AiErrorKind.AUTHENTICATION
    assert invalid_model.error_kind is AiErrorKind.INVALID_MODEL


def test_http_backend_sends_selected_model_and_never_declares_tools() -> None:
    backend = GenericOpenAiBackend(endpoint="https://api.example/v1", model="selected-model")
    payload = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "model": "selected-model",
    }
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        backend.generate(AiRequest(request_id="selected"))

    outbound = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert outbound["model"] == "selected-model"
    assert backend.capabilities().supports_tools is False
    assert backend.metadata.supports_reasoning_effort is False


def test_http_health_probe_is_cached_between_conversation_turns() -> None:
    backend = GenericOpenAiBackend(endpoint="https://api.example/v1", model="selected")
    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        first = backend.health()
        second = backend.health()

    assert first.status == second.status
    assert urlopen.call_count == 1


def test_http_health_404_models_is_degraded_not_claimed_healthy() -> None:
    backend = GenericOpenAiBackend(
        endpoint="https://api.example/v1",
        model="selected",
        api_key="secret",
        provider_name="remote:test",
        requires_internet=True,
        requires_api_key=True,
    )

    with patch("urllib.request.urlopen", side_effect=_http_error(404, "not found")):
        health = backend.health()

    assert health.status.value == "DEGRADED"
    assert "catalog" in health.detail.lower()


def test_http_stream_reports_actual_serialized_request_size() -> None:
    backend = GenericOpenAiBackend(
        endpoint="https://api.example/v1",
        model="selected",
    )
    response = MagicMock()
    response.readline.side_effect = [
        b'data: {"model":"selected","choices":[{"delta":{"content":"Hola"}}]}\n',
        b"data: [DONE]\n",
    ]
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = backend.generate_stream(
            AiRequest(
                request_id="size",
                messages=[ChatMessage(role="user", content="Turno actual")],
            ),
            lambda _delta: True,
        )

    outbound = urlopen.call_args.args[0].data
    assert result.request_chars == len(outbound)

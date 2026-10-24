"""Unit tests for the lightweight OpenAI-compatible transport."""

import json
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from ailen.ai.contracts import AiErrorKind, AiRequest, ChatMessage, ToolCallRequest
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


def test_stream_filters_split_harmony_analysis_before_callback() -> None:
    backend = GenericOpenAiBackend(endpoint="https://api.example/v1", model="fast-model")
    chunks = [
        "<|chan", "nel|>analysis<|mes", "sage|>razonamiento secreto<|end|>",
        "<|channel|>final<|message|>Hola.",
    ]
    lines = [
        ("data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}) + "\n").encode()
        for chunk in chunks
    ] + [b"data: [DONE]\n", b""]
    response = MagicMock()
    response.readline.side_effect = lines
    response.__enter__.return_value = response
    deltas: list[str] = []

    with patch("urllib.request.urlopen", return_value=response):
        result = backend.generate_stream(
            AiRequest(request_id="harmony-stream"),
            lambda delta: deltas.append(delta) or True,
        )

    assert "razonamiento secreto" not in "".join(deltas)
    assert result.text == "Hola."
    assert "".join(deltas) == "Hola."


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


def test_local_openai_backend_sends_native_tools_and_parses_provider_call_id() -> None:
    backend = LocalAiBackend(endpoint="http://127.0.0.1:18080/v1", model="gpt-oss-20b")
    response_payload = {
        "model": "gpt-oss-20b",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-clock-1",
                    "type": "function",
                    "function": {"name": "clock", "arguments": '{"format":"time"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }
    response = MagicMock()
    response.read.return_value = json.dumps(response_payload).encode("utf-8")
    response.__enter__.return_value = response
    request = AiRequest(
        request_id="native-tools",
        messages=[
            ChatMessage(role="user", content="¿Qué hora es?"),
            ChatMessage(role="assistant", content="", tool_calls=[
                ToolCallRequest("clock", {"format": "time"}, "history-call"),
            ]),
            ChatMessage(role="tool", content="hora actual", tool_call_id="history-call"),
        ],
        tool_specs=[{
            "type": "function",
            "function": {
                "name": "clock",
                "description": "Consultar hora",
                "parameters": {"type": "object", "properties": {}},
            },
        }],
    )

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = backend.generate(request)

    outbound = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert outbound["tools"] == request.tool_specs
    assert outbound["tool_choice"] == "auto"
    assert outbound["messages"][1]["tool_calls"][0]["id"] == "history-call"
    assert outbound["messages"][2]["tool_call_id"] == "history-call"
    assert backend.capabilities().supports_tools is True
    assert result.error_kind is None
    assert result.tool_calls[0].name == "clock"
    assert result.tool_calls[0].arguments == {"format": "time"}
    assert result.tool_calls[0].call_id == "call-clock-1"


def test_local_openai_backend_strips_harmony_analysis_and_ignores_reasoning_content() -> None:
    backend = LocalAiBackend(endpoint="http://127.0.0.1:18080/v1", model="gpt-oss-20b")
    response = MagicMock()
    response.read.return_value = json.dumps({
        "choices": [{"message": {
            "content": "<|channel|>analysis<|message|>privado<|end|>"
            "<|channel|>final<|message|>Visible.<|end|>",
            "reasoning_content": "razonamiento separado",
        }, "finish_reason": "stop"}],
    }).encode("utf-8")
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response):
        result = backend.generate(AiRequest(request_id="harmony-local"))

    assert result.text == "Visible."
    assert "privado" not in result.text
    assert "razonamiento" not in result.text


def test_openai_compatible_analysis_only_is_classified_as_empty_invalid_response() -> None:
    backend = LocalAiBackend(endpoint="http://127.0.0.1:18080/v1", model="gpt-oss-20b")
    response = backend._parse_success_response(json.dumps({
        "choices": [{
            "message": {"content": "<|channel|>analysis<|message|>solo análisis<|end|>"},
            "finish_reason": "stop",
        }],
        "usage": {"completion_tokens": 38},
    }), 10.0, request_chars=100)

    assert response.text == ""
    assert response.finish_reason == "empty_response"
    assert response.error_kind is AiErrorKind.INVALID_RESPONSE


def test_local_openai_backend_rejects_non_object_tool_arguments() -> None:
    backend = LocalAiBackend(endpoint="http://127.0.0.1:18080/v1", model="gpt-oss-20b")
    response = MagicMock()
    response.read.return_value = json.dumps({
        "choices": [{"message": {
            "tool_calls": [{"id": "bad", "function": {"name": "clock", "arguments": "[]"}}],
        }, "finish_reason": "tool_calls"}],
    }).encode("utf-8")
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response):
        result = backend.generate(AiRequest(request_id="bad-tool-args", tool_specs=[{"type": "function"}]))

    assert result.tool_calls == []
    assert result.error_kind is AiErrorKind.INVALID_RESPONSE
    assert result.finish_reason == "malformed_response"


def test_remote_openai_compatible_backend_never_sends_tool_specs() -> None:
    backend = GenericOpenAiBackend(
        endpoint="https://api.example/v1", model="remote",
        provider_name="remote:test", requires_internet=True,
    )

    with patch("urllib.request.urlopen") as urlopen:
        result = backend.generate(AiRequest(
            request_id="remote-tools",
            tool_specs=[{"type": "function", "function": {"name": "do_it"}}],
        ))

    assert result.error_kind is AiErrorKind.INVALID_RESPONSE
    urlopen.assert_not_called()


@pytest.mark.parametrize("method", ["generate", "generate_stream"])
@pytest.mark.parametrize("message", [
    ChatMessage(role="tool", content="sensitive", tool_call_id="call-1"),
    ChatMessage(role="assistant", content="", tool_calls=[ToolCallRequest("x", {}, "call-1")]),
])
def test_remote_openai_backend_rejects_native_tool_history_without_network(
    message: ChatMessage, method: str,
) -> None:
    backend = GenericOpenAiBackend(endpoint="https://api.example/v1", model="remote")

    with patch("urllib.request.urlopen") as urlopen:
        request = AiRequest(request_id="remote-history", messages=[message])
        if method == "generate":
            response = backend.generate(request)
        else:
            response = backend.generate_stream(request, lambda _delta: True)

    assert response.error_kind is AiErrorKind.INVALID_RESPONSE
    urlopen.assert_not_called()


def test_local_tool_request_disables_parallel_calls_in_payload() -> None:
    backend = LocalAiBackend(endpoint="http://127.0.0.1:18080/v1", model="gpt-oss-20b")
    response = MagicMock()
    response.read.return_value = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    response.__enter__.return_value = response
    request = AiRequest(request_id="serial-tools", tool_specs=[{
        "type": "function", "function": {"name": "clock", "parameters": {"type": "object"}},
    }])

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        backend.generate(request)

    payload = json.loads(urlopen.call_args.args[0].data)
    assert payload["parallel_tool_calls"] is False


def test_local_server_rejection_of_parallel_tool_flag_retries_without_it() -> None:
    backend = LocalAiBackend(endpoint="http://127.0.0.1:18080/v1", model="gpt-oss-20b")
    response = MagicMock()
    response.read.return_value = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    response.__enter__.return_value = response
    captured: list[dict] = []

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        payload = json.loads(request.data)
        captured.append(payload)
        if "parallel_tool_calls" in payload:
            raise _http_error(400, "unsupported parameter parallel_tool_calls")
        return response

    with patch("urllib.request.urlopen", side_effect=urlopen):
        result = backend.generate(AiRequest(
            request_id="parallel-compat", tool_specs=[{
                "type": "function", "function": {"name": "clock", "parameters": {"type": "object"}},
            }],
        ))
        backend.generate(AiRequest(
            request_id="parallel-compat-next", tool_specs=[{
                "type": "function", "function": {"name": "clock", "parameters": {"type": "object"}},
            }],
        ))

    assert result.text == "ok"
    assert len(captured) == 3
    assert captured[0]["parallel_tool_calls"] is False
    assert "parallel_tool_calls" not in captured[1]
    assert "parallel_tool_calls" not in captured[2]


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

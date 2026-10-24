"""Tests for the native low-latency Ollama backend."""

import json
from unittest.mock import MagicMock

import pytest

from ailen.ai.contracts import AiRequest, ChatMessage
from ailen.ai.ollama_backend import OllamaNativeBackend


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._raw = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return False

    def read(self, _limit: int = -1) -> bytes:
        return self._raw


def test_ollama_native_generate_disables_thinking(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({
            "model": "qwen3.5:9b",
            "done_reason": "stop",
            "message": {"role": "assistant", "content": "Sí."},
            "prompt_eval_count": 12,
            "prompt_eval_duration": 24_000_000,
            "eval_count": 3,
            "eval_duration": 60_000_000,
            "load_duration": 5_000_000,
        })

    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", fake_urlopen)
    backend = OllamaNativeBackend(model="qwen3.5:9b", timeout_seconds=60.0, think=False)
    request = AiRequest(
        request_id="r1",
        messages=[ChatMessage(role="user", content="si")],
        max_output_tokens=64,
        timeout_seconds=30.0,
    )
    response = backend.generate(request)

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 30.0
    assert captured["payload"]["think"] is False
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["options"]["num_predict"] == 64
    assert response.text == "Sí."
    assert response.provider == "ollama"
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 3
    assert response.usage.generation_tokens_per_second == pytest.approx(50.0)
    assert response.usage.prompt_eval_ms == pytest.approx(24.0)
    assert response.usage.generation_ms == pytest.approx(60.0)
    assert response.usage.load_ms == pytest.approx(5.0)


def test_ollama_native_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaNativeBackend(endpoint="http://example.com:11434/v1", model="qwen")


def test_remote_ollama_is_not_advertised_as_local_even_when_explicitly_allowed() -> None:
    backend = OllamaNativeBackend(
        endpoint="http://192.168.1.20:11434/v1", model="qwen", allow_remote=True,
    )

    assert backend.capabilities().is_local is False
    assert backend.capabilities().supports_tools is True


def test_remote_ollama_rejects_native_tool_schemas_before_network(monkeypatch) -> None:
    backend = OllamaNativeBackend(
        endpoint="http://192.168.1.20:11434/v1", model="qwen", allow_remote=True,
    )
    called = False

    def forbidden_urlopen(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("a remote Ollama host must not receive tool schemas")

    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", forbidden_urlopen)
    response = backend.generate(AiRequest(
        request_id="remote-ollama-tools",
        tool_specs=[{"type": "function", "function": {"name": "clock"}}],
    ))

    assert response.error_kind.value == "invalid_response"
    assert called is False


def test_ollama_native_never_returns_harmony_analysis_or_thinking(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        return _FakeResponse({"message": {
            "content": "<|channel|>analysis<|message|>razonamiento privado<|end|>"
            "<|channel|>final<|message|>Respuesta visible.<|end|>",
            "thinking": "razonamiento separado",
        }})

    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", fake_urlopen)
    response = OllamaNativeBackend(model="qwen3.5:9b").generate(AiRequest(request_id="harmony"))

    assert response.text == "Respuesta visible."
    assert "razonamiento" not in response.text


def test_ollama_native_sends_tool_specs_and_parses_object_arguments(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({
            "model": "qwen3.5:9b",
            "done_reason": "tool_calls",
            "message": {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "clock", "arguments": {"format": "time"}},
            }]},
        })

    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", fake_urlopen)
    backend = OllamaNativeBackend(model="qwen3.5:9b")
    tools = [{"type": "function", "function": {
        "name": "clock", "description": "Consultar hora",
        "parameters": {"type": "object", "properties": {}},
    }}]

    response = backend.generate(AiRequest(
        request_id="ollama-tool", messages=[ChatMessage(role="user", content="Hora")],
        tool_specs=tools,
    ))

    assert backend.capabilities().supports_tools is True
    assert captured["payload"]["tools"] == tools
    assert response.error_kind is None
    assert response.tool_calls[0].name == "clock"
    assert response.tool_calls[0].arguments == {"format": "time"}


def test_ollama_native_rejects_invalid_tool_arguments(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        return _FakeResponse({"message": {"tool_calls": [{
            "function": {"name": "clock", "arguments": "true"},
        }]}})

    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", fake_urlopen)
    response = OllamaNativeBackend(model="qwen3.5:9b").generate(AiRequest(
        request_id="bad-ollama-tool", tool_specs=[{"type": "function"}],
    ))

    from ailen.ai.contracts import AiErrorKind

    assert response.error_kind is AiErrorKind.INVALID_RESPONSE
    assert response.tool_calls == []


def test_ollama_stream_does_not_emit_harmony_analysis_from_split_markers(monkeypatch) -> None:
    chunks = [
        "<|chan", "nel|>analysis<|mes", "sage|>razonamiento secreto<|end|>",
        "<|channel|>final<|message|>Hola.",
    ]
    response = MagicMock()
    response.__iter__.return_value = iter([
        json.dumps({"message": {"content": chunk}, "done": i == len(chunks) - 1}).encode()
        for i, chunk in enumerate(chunks)
    ])
    response.__enter__.return_value = response
    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", lambda *_a, **_k: response)
    deltas: list[str] = []

    result = OllamaNativeBackend(model="qwen3.5:9b").generate_stream(
        AiRequest(request_id="ollama-harmony-stream"),
        lambda delta: deltas.append(delta) or True,
    )

    assert "razonamiento secreto" not in "".join(deltas)
    assert "Hola." == result.text
    assert "".join(deltas) == "Hola."


def test_ollama_native_warmup_loads_without_prompt(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"model": "qwen3.5:9b", "done": True})

    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", fake_urlopen)
    backend = OllamaNativeBackend(model="qwen3.5:9b", timeout_seconds=12.0, keep_alive="15m")
    assert backend.warmup() is True
    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    assert captured["timeout"] == 12.0
    assert captured["payload"] == {
        "model": "qwen3.5:9b",
        "prompt": "",
        "stream": False,
        "keep_alive": "15m",
    }


def test_ollama_native_releases_model_with_official_keep_alive_zero(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"model": "tiny", "done": True, "done_reason": "unload"})

    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", fake_urlopen)
    backend = OllamaNativeBackend(model="tiny", timeout_seconds=12.0)

    assert backend.release_if_idle() is True
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 2.0
    assert captured["payload"] == {
        "model": "tiny",
        "messages": [],
        "stream": False,
        "keep_alive": 0,
    }


class _FakeStreamingResponse:
    def __init__(self, payloads: list[dict], status: int = 200) -> None:
        self._lines = [json.dumps(item).encode("utf-8") + b"\n" for item in payloads]
        self.status = status

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return False

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._lines)


def test_ollama_native_stream_can_stop_after_first_complete_phrase(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeStreamingResponse([
            {"model": "qwen3:1.7b", "message": {"content": "Qué bueno"}, "done": False},
            {"model": "qwen3:1.7b", "message": {"content": ", che."}, "done": False},
            {"model": "qwen3:1.7b", "message": {"content": " Ahora descansá."}, "done": False},
        ])

    monkeypatch.setattr("ailen.ai.ollama_backend.urllib.request.urlopen", fake_urlopen)
    backend = OllamaNativeBackend(model="qwen3:1.7b", context_tokens=1536)
    request = AiRequest(
        request_id="voice-1",
        messages=[ChatMessage(role="user", content="Terminé el trabajo")],
        max_output_tokens=48,
        timeout_seconds=15.0,
    )
    accumulated = ""

    def on_delta(delta: str) -> bool:
        nonlocal accumulated
        accumulated += delta
        return not accumulated.endswith(".")

    response = backend.generate_stream(request, on_delta)

    assert captured["payload"]["stream"] is True
    assert captured["payload"]["think"] is False
    assert captured["payload"]["options"]["num_ctx"] == 1536
    assert captured["timeout"] == 15.0
    assert response.text == "Qué bueno, che."
    assert response.finish_reason == "client_stop"

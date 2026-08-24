"""Tests for the native low-latency Ollama backend."""

import json

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
            "eval_count": 3,
            "eval_duration": 60_000_000,
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


def test_ollama_native_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaNativeBackend(endpoint="http://example.com:11434/v1", model="qwen")


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

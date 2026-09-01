"""Lazy common-AiBackend adapter around an AILEN-owned llama.cpp server."""

from pathlib import Path

from ailen.ai.contracts import AiRequest, AiResponse, BackendCapabilities, BackendHealth
from ailen.ai.managed_local_backend import ManagedLocalAiBackend
from ailen.domain.enums import ServiceStatus


class FakeRuntime:
    def __init__(self) -> None:
        self.is_running = False
        self.owned_by_ailen = False
        self.starts = 0
        self.stops = 0

    def start(self, **kwargs):  # type: ignore[no-untyped-def]
        self.starts += 1
        self.is_running = True
        self.owned_by_ailen = True
        return True

    def stop(self) -> None:
        self.stops += 1
        self.is_running = False
        self.owned_by_ailen = False


class FakeClient:
    def health(self) -> BackendHealth:
        return BackendHealth(ServiceStatus.HEALTHY, "ready")

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(supports_streaming=True, is_local=True)

    def generate(self, request: AiRequest) -> AiResponse:
        del request
        return AiResponse(text="respuesta local", provider="llama_cpp", model="tiny")

    def generate_stream(self, request, on_text_delta):  # type: ignore[no-untyped-def]
        del request
        on_text_delta("respuesta local")
        return AiResponse(text="respuesta local", provider="llama_cpp", model="tiny")


def test_managed_llama_is_not_started_until_first_inference(tmp_path: Path) -> None:
    model = tmp_path / "tiny.gguf"
    model.write_bytes(b"synthetic")
    runtime = FakeRuntime()
    backend = ManagedLocalAiBackend(
        runtime=runtime,  # type: ignore[arg-type]
        model_path=model,
        model_alias="tiny",
        client_factory=lambda _endpoint, _model, _timeout: FakeClient(),  # type: ignore[arg-type]
    )

    assert backend.health().status is ServiceStatus.DEGRADED
    assert runtime.starts == 0

    response = backend.generate(AiRequest(request_id="one"))

    assert response.text == "respuesta local"
    assert runtime.starts == 1


def test_managed_llama_releases_under_pressure_and_reloads_on_next_turn(tmp_path: Path) -> None:
    model = tmp_path / "tiny.gguf"
    model.write_bytes(b"synthetic")
    runtime = FakeRuntime()
    backend = ManagedLocalAiBackend(
        runtime=runtime,  # type: ignore[arg-type]
        model_path=model,
        model_alias="tiny",
        client_factory=lambda _endpoint, _model, _timeout: FakeClient(),  # type: ignore[arg-type]
    )

    backend.generate(AiRequest(request_id="one"))
    assert backend.release_if_idle() is True
    assert runtime.stops == 1
    backend.generate(AiRequest(request_id="two"))
    assert runtime.starts == 2

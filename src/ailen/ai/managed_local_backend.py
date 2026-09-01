"""Lazy common-AI adapter for an AILEN-owned llama.cpp server."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ailen.ai.contracts import (
    AiBackend,
    AiErrorKind,
    AiRequest,
    AiResponse,
    BackendCapabilities,
    BackendHealth,
    StreamingAiBackend,
)
from ailen.ai.local_backend import LocalAiBackend
from ailen.domain.enums import ServiceStatus

ClientFactory = Callable[[str, str, float], AiBackend]


class ManagedRuntime(Protocol):
    """Minimal lifecycle boundary implemented by the runtime layer."""

    @property
    def is_running(self) -> bool: ...

    @property
    def owned_by_ailen(self) -> bool: ...

    def start(
        self,
        model_path: str | Path,
        host: str = "127.0.0.1",
        port: int = 8080,
        context_size: int = 2048,
        gpu_layers: int | str = 0,
        model_alias: str | None = None,
        timeout: float = 10.0,
    ) -> bool: ...

    def stop(self) -> None: ...


class ManagedLocalAiBackend(AiBackend, StreamingAiBackend):
    """Start llama.cpp on first inference and release it safely under pressure."""

    def __init__(
        self,
        runtime: ManagedRuntime,
        model_path: str | Path,
        model_alias: str,
        context_size: int = 2048,
        gpu_layers: int | str = 0,
        timeout_seconds: float = 20.0,
        host: str = "127.0.0.1",
        port: int = 8080,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.runtime = runtime
        self.model_path = Path(model_path).resolve()
        self.model = model_alias
        self.context_size = max(512, context_size)
        self.gpu_layers = gpu_layers
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.host = host
        self.port = port
        self._client_factory = client_factory or self._default_client_factory
        self._client: AiBackend | None = None
        self._request_lock = threading.Lock()

    @staticmethod
    def _default_client_factory(endpoint: str, model: str, timeout: float) -> AiBackend:
        return LocalAiBackend(endpoint=endpoint, model=model, timeout_seconds=timeout)

    def health(self) -> BackendHealth:
        if not self.model_path.is_file():
            return BackendHealth(ServiceStatus.UNHEALTHY, "Verified GGUF is no longer present")
        if not self.runtime.is_running:
            return BackendHealth(
                ServiceStatus.DEGRADED,
                "Verified llama.cpp model is ready for on-demand loading",
            )
        client = self._client
        return client.health() if client is not None else BackendHealth(
            ServiceStatus.DEGRADED,
            "Managed llama.cpp is starting",
        )

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_tools=False,
            supports_streaming=True,
            max_context_tokens=self.context_size,
            is_local=True,
            requires_internet=False,
        )

    def warmup(self) -> bool:
        with self._request_lock:
            return self._ensure_client() is not None

    def release_if_idle(self) -> bool:
        if not self._request_lock.acquire(blocking=False):
            return False
        try:
            if not self.runtime.is_running or not self.runtime.owned_by_ailen:
                return False
            self.runtime.stop()
            self._client = None
            return True
        finally:
            self._request_lock.release()

    def generate(self, request: AiRequest) -> AiResponse:
        with self._request_lock:
            client = self._ensure_client()
            if client is None:
                return self._unavailable()
            return client.generate(request)

    def generate_stream(
        self,
        request: AiRequest,
        on_text_delta: Callable[[str], bool | None],
    ) -> AiResponse:
        with self._request_lock:
            client = self._ensure_client()
            if client is None:
                return self._unavailable()
            if isinstance(client, StreamingAiBackend):
                return client.generate_stream(request, on_text_delta)
            response = client.generate(request)
            if response.text:
                on_text_delta(response.text)
            return response

    def _ensure_client(self) -> AiBackend | None:
        if self.runtime.is_running and self._client is not None:
            return self._client
        started = self.runtime.start(
            model_path=self.model_path,
            host=self.host,
            port=self.port,
            context_size=self.context_size,
            gpu_layers=self.gpu_layers,
            model_alias=self.model,
        )
        if not started:
            return None
        endpoint = f"http://{self.host}:{self.port}/v1"
        self._client = self._client_factory(endpoint, self.model, self.timeout_seconds)
        return self._client

    def _unavailable(self) -> AiResponse:
        return AiResponse(
            text="",
            finish_reason="unreachable",
            provider="llama_cpp",
            model=self.model,
            error_kind=AiErrorKind.UNAVAILABLE,
        )

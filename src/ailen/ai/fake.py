"""Fake AI backend for development and tests. No real inference, no Internet."""

import time

from ailen.ai.contracts import (
    AiBackend,
    AiRequest,
    AiResponse,
    AiUsage,
    BackendCapabilities,
    BackendHealth,
)
from ailen.domain.enums import ServiceStatus


class FakeAiBackend(AiBackend):
    """Deterministic, offline AI backend.

    Devuelve respuestas sintéticas eco del último mensaje. Sirve para
    levantar el sistema completo sin proveedor real.
    """

    def __init__(self, provider: str = "fake", model: str = "fake-echo-0") -> None:
        self._provider = provider
        self._model = model

    def health(self) -> BackendHealth:
        return BackendHealth(status=ServiceStatus.HEALTHY, detail="fake backend siempre disponible")

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_tools=True,
            supports_streaming=False,
            max_context_tokens=2048,
            is_local=True,
            requires_internet=False,
        )

    def generate(self, request: AiRequest) -> AiResponse:
        start = time.monotonic()
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"),
            "",
        )
        text = (
            f"[{self._model}] Respuesta simulada en modo {request.mode.value}. "
            f"Entendí: «{last_user}». Todavía no hay inferencia real configurada."
        )
        input_tokens = sum(len(m.content.split()) for m in request.messages)
        output_tokens = len(text.split())
        return AiResponse(
            text=text,
            tool_calls=[],
            finish_reason="stop",
            usage=AiUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=0.0,
                currency="USD",
            ),
            latency_ms=(time.monotonic() - start) * 1000.0,
            provider=self._provider,
            model=self._model,
        )

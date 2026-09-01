"""AI backend contracts for AILEN.

Interfaces alineadas con docs/architecture/MODULE_CONTRACTS.md sección 5.
El Core nunca conoce marcas/modelos concretos; el Router elige el backend.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from ailen.domain.enums import PrivacyLevel, ServiceStatus, SocialMode


@dataclass
class ChatMessage:
    """A single message in an AI conversation context."""
    role: str  # "user", "assistant", "system", "tool"
    content: str


@dataclass
class AiUsage:
    """Token/cost usage of an inference call."""
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    currency: str | None = None
    generation_tokens_per_second: float | None = None
    prompt_eval_ms: float | None = None
    generation_ms: float | None = None
    load_ms: float | None = None


@dataclass
class ToolCallRequest:
    """A tool invocation requested by the AI backend."""
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


class AiErrorKind(StrEnum):
    """Stable failure taxonomy shared by adapters, fallback and diagnostics."""

    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    INVALID_MODEL = "invalid_model"
    NETWORK = "network"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    INTERNAL_ERROR = "internal_error"


@dataclass
class AiAttempt:
    """One observable provider attempt in a fallback chain."""

    backend: str
    outcome: str
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    error_kind: AiErrorKind | None = None
    detail: str = ""


@dataclass
class AiRequest:
    """Request for AI inference. Context is pre-built by Core (mínimo necesario)."""
    request_id: str
    system_context: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    retrieved_memory: list[str] = field(default_factory=list)
    mode: SocialMode = SocialMode.WORKSHOP
    allowed_tools: list[str] = field(default_factory=list)
    max_output_tokens: int = 512
    temperature: float = 0.4
    timeout_seconds: float = 10.0
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AiResponse:
    """Response from an AI backend."""
    text: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop", "length", "tool_call", "error"
    usage: AiUsage = field(default_factory=AiUsage)
    latency_ms: float = 0.0
    provider: str = "unknown"
    model: str = "unknown"
    error_kind: AiErrorKind | None = None
    retry_after_seconds: float | None = None
    provider_setup_ms: float | None = None
    provider_ready_ms: float | None = None
    first_text_ms: float | None = None
    request_chars: int | None = None
    provider_tool_count: int | None = None
    attempts: list[AiAttempt] = field(default_factory=list)


@dataclass
class BackendCapabilities:
    """Declared capabilities of an AI backend."""
    supports_tools: bool = False
    supports_streaming: bool = False
    max_context_tokens: int = 4096
    is_local: bool = False
    requires_internet: bool = False


@dataclass
class BackendHealth:
    """Health of an AI backend."""
    status: ServiceStatus = ServiceStatus.UNKNOWN
    detail: str = ""


@runtime_checkable
class StreamingAiBackend(Protocol):
    """Optional token-streaming AI backend used for low-latency voice turns."""

    def generate_stream(
        self,
        request: AiRequest,
        on_text_delta: Callable[[str], bool | None],
    ) -> AiResponse:
        """Generate incrementally; callback may return False to stop early."""
        ...


@runtime_checkable
class AiBackend(Protocol):
    """Contract for AI inference backends (local, LAN Brain, named remote)."""

    def health(self) -> BackendHealth:
        """Return backend health status."""
        ...

    def capabilities(self) -> BackendCapabilities:
        """Return declared backend capabilities."""
        ...

    def generate(self, request: AiRequest) -> AiResponse:
        """Run inference and return a normalized response."""
        ...

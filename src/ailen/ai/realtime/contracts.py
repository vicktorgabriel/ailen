"""Contracts and configuration for ADR-015 realtime voice providers.

Defines the replaceable RealtimeSession protocol, event payloads, and
secret-free provider configuration. API keys are resolved exclusively at
connect time through SecretResolver.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

from ailen.ai.secrets import SecretResolver
from ailen.domain.enums import ErrorCode


class RealtimeEventType(str, Enum):
    """Normalized event types emitted by a RealtimeSession."""

    AUDIO_OUT = "audio_out"
    TRANSCRIPT_PARTIAL = "transcript_partial"
    TRANSCRIPT_FINAL = "transcript_final"
    TOOL_CALL = "tool_call"
    ERROR = "error"
    CLOSED = "closed"


@dataclass(frozen=True)
class RealtimeEvent:
    """Normalized event emitted by a realtime voice session."""

    type: RealtimeEventType
    audio: bytes = b""
    text: str = ""
    name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    error: str = ""
    error_code: ErrorCode | None = None

    @property
    def kind(self) -> RealtimeEventType:
        """Alias for event type."""
        return self.type

    @classmethod
    def audio_out(cls, pcm_bytes: bytes) -> RealtimeEvent:
        """Create an outbound audio chunk event."""
        return cls(type=RealtimeEventType.AUDIO_OUT, audio=bytes(pcm_bytes))

    @classmethod
    def transcript_partial(cls, text: str) -> RealtimeEvent:
        """Create a partial transcript event."""
        return cls(type=RealtimeEventType.TRANSCRIPT_PARTIAL, text=text)

    @classmethod
    def transcript_final(cls, text: str) -> RealtimeEvent:
        """Create a final transcript event."""
        return cls(type=RealtimeEventType.TRANSCRIPT_FINAL, text=text)

    @classmethod
    def tool_call(
        cls,
        name: str,
        args: dict[str, Any] | None = None,
        call_id: str = "",
    ) -> RealtimeEvent:
        """Create a function/tool call request event."""
        return cls(
            type=RealtimeEventType.TOOL_CALL,
            name=name,
            args=dict(args or {}),
            call_id=call_id,
        )

    @classmethod
    def error_event(
        cls,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
    ) -> RealtimeEvent:
        """Create an error event."""
        return cls(
            type=RealtimeEventType.ERROR,
            error=message,
            error_code=error_code,
        )

    @classmethod
    def closed(cls, reason: str = "") -> RealtimeEvent:
        """Create a session closed event."""
        return cls(type=RealtimeEventType.CLOSED, text=reason)


@dataclass(frozen=True)
class RealtimeProviderConfig:
    """Secret-free configuration for a realtime voice provider (ADR-015).

    Secrets must never be stored in this dataclass. Only secret reference names
    (env var name or file name inside SecretResolver's directory) are allowed.
    """

    provider_id: str
    endpoint: str
    model: str
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 30.0
    max_audio_minutes: float = 15.0
    sample_rate_hz: int = 16_000
    max_frame_bytes: int = 262_144
    max_message_bytes: int = 1_048_576
    secret_env_var: str | None = None
    secret_file_name: str | None = None
    allow_insecure_ws_for_testing: bool = False

    def __post_init__(self) -> None:
        if not self.provider_id or not self.provider_id.strip():
            raise ValueError("provider_id must not be empty")
        if not self.model or not self.model.strip():
            raise ValueError("model must not be empty")
        parsed = urlsplit(self.endpoint)
        scheme = parsed.scheme.lower()
        if scheme == "wss":
            pass
        elif scheme == "ws" and self.allow_insecure_ws_for_testing:
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Insecure ws:// endpoint is restricted to loopback hosts")
        else:
            raise ValueError("RealtimeProviderConfig.endpoint must use wss://")
        if not parsed.hostname:
            raise ValueError("RealtimeProviderConfig.endpoint must include a hostname")
        if self.connect_timeout_s <= 0 or self.read_timeout_s <= 0:
            raise ValueError("Timeouts must be positive")
        if self.max_audio_minutes <= 0:
            raise ValueError("max_audio_minutes must be positive")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.max_frame_bytes <= 0 or self.max_message_bytes < self.max_frame_bytes:
            raise ValueError("Invalid frame/message size limits")
        if self.secret_env_var and self.secret_env_var.strip().startswith("sk-"):
            raise ValueError("secret_env_var must be an environment variable name, not a raw key")

    @property
    def bytes_per_second(self) -> int:
        """PCM16LE mono byte rate derived from sample_rate_hz."""
        return self.sample_rate_hz * 2

    @property
    def route_id(self) -> str:
        """Canonical route identifier per ADR-015."""
        return f"remote_realtime:{self.provider_id}"

    def resolve_secret(self, resolver: SecretResolver) -> str | None:
        """Resolve the API secret at connect time via SecretResolver."""
        return resolver.resolve(
            env_var=self.secret_env_var,
            file_name=self.secret_file_name,
        )


@runtime_checkable
class RealtimeSession(Protocol):
    """Replaceable contract for a bidirectional realtime voice session."""

    def connect(self) -> None:
        """Open the underlying realtime session."""
        ...

    def send_audio(self, pcm16le_16k_mono: bytes) -> None:
        """Stream a chunk of PCM16LE 16 kHz mono audio to the provider."""
        ...

    def events(self) -> Iterator[RealtimeEvent]:
        """Iterate over incoming normalized realtime events."""
        ...

    def send_tool_result(self, call_id: str, result: dict[str, Any]) -> None:
        """Return a structured tool execution output for a previous tool_call."""
        ...

    def cancel(self) -> None:
        """Interrupt current assistant response generation/playback (barge-in)."""
        ...

    def close(self) -> None:
        """Close the realtime session cleanly."""
        ...

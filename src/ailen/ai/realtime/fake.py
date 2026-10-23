"""Deterministic fake realtime session for offline unit tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from typing import Any

from ailen.ai.realtime.contracts import (
    RealtimeEvent,
    RealtimeEventType,
    RealtimeProviderConfig,
)
from ailen.ai.secrets import SecretResolver


class FakeRealtimeSession:
    """In-memory deterministic implementation of RealtimeSession for testing."""

    def __init__(
        self,
        scripted_events: Iterable[RealtimeEvent] | None = None,
        config: RealtimeProviderConfig | None = None,
        secret_resolver: SecretResolver | None = None,
        require_secret: bool = False,
    ) -> None:
        self.config = config
        self._secret_resolver = secret_resolver
        self._require_secret = require_secret
        self._events: deque[RealtimeEvent] = deque(scripted_events or ())
        self.connected: bool = False
        self.closed: bool = False
        self.cancelled: bool = False
        self.cancel_count: int = 0
        self._dropping_cancelled_audio: bool = False
        self.sent_audio: list[bytes] = []
        self.tool_results: list[tuple[str, dict[str, Any]]] = []
        self.resolved_secret_present: bool = False

    def connect(self) -> None:
        """Simulate session connection and optional secret resolution."""
        if self.closed:
            raise RuntimeError("Cannot reconnect a closed FakeRealtimeSession")
        if self.config is not None and self._secret_resolver is not None:
            secret = self.config.resolve_secret(self._secret_resolver)
            self.resolved_secret_present = bool(secret)
            if self._require_secret and not secret:
                raise PermissionError(
                    f"Missing secret for realtime provider '{self.config.provider_id}'"
                )
        elif self._require_secret:
            raise PermissionError("Missing SecretResolver or config for required secret")
        self.connected = True

    def push_event(self, event: RealtimeEvent) -> None:
        """Append a deterministic event to the session queue."""
        self._events.append(event)

    def send_audio(self, pcm16le_16k_mono: bytes) -> None:
        """Record outbound PCM16LE 16 kHz mono audio bytes."""
        if not self.connected or self.closed:
            raise RuntimeError("Realtime session is not connected")
        if not isinstance(pcm16le_16k_mono, (bytes, bytearray)):
            raise TypeError("pcm16le_16k_mono must be bytes")
        if len(pcm16le_16k_mono) % 2 != 0:
            raise ValueError("PCM16LE audio chunk byte length must be even")
        self.sent_audio.append(bytes(pcm16le_16k_mono))

    def events(self) -> Iterator[RealtimeEvent]:
        """Yield queued events until exhausted or session closes."""
        if not self.connected:
            raise RuntimeError("Realtime session must be connected before reading events")
        while self._events:
            if self.closed:
                yield RealtimeEvent.closed("closed")
                return
            event = self._events.popleft()
            if self._dropping_cancelled_audio:
                if event.type == RealtimeEventType.AUDIO_OUT:
                    continue
                if event.type in {
                    RealtimeEventType.TRANSCRIPT_PARTIAL,
                    RealtimeEventType.TRANSCRIPT_FINAL,
                    RealtimeEventType.TOOL_CALL,
                }:
                    self._dropping_cancelled_audio = False
            yield event
            if event.type == RealtimeEventType.CLOSED:
                self.closed = True
                return

    def send_tool_result(self, call_id: str, result: dict[str, Any]) -> None:
        """Record tool result sent back to the realtime provider."""
        if not self.connected or self.closed:
            raise RuntimeError("Realtime session is not connected")
        self.tool_results.append((call_id, dict(result)))

    def cancel(self) -> None:
        """Cancel active assistant output (barge-in) and purge buffered audio_out until new response."""
        if not self.connected or self.closed:
            return
        self.cancelled = True
        self.cancel_count += 1
        self._dropping_cancelled_audio = True
        while self._events and self._events[0].type == RealtimeEventType.AUDIO_OUT:
            self._events.popleft()

    def close(self) -> None:
        """Close the fake session idempotently."""
        if not self.closed:
            self.closed = True
            self._events.append(RealtimeEvent.closed("closed_by_client"))

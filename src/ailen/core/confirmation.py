"""Ephemeral human approvals for ADR-014 §3; no arguments or secrets persisted.

Only trusted Core/voice handlers and authenticated, CSRF-checked panel handlers
may call ``resolve``.  ``source='panel'`` is a trust assertion by that handler,
not authentication performed by this service. Never expose it directly to an
LLM. Consumers must supply the tool and exact validated arguments again.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal


class ConfirmationState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ConfirmationRequest:
    """Immutable snapshot with a bounded, tool-authored safe action summary."""

    id: str
    tool_name: str
    summary: str
    created_at: datetime
    expires_at: datetime
    state: ConfirmationState
    arguments_hash: str


class ConfirmationService:
    """Bounded RAM-only approvals with monotonic expiry and atomic consumption.

    ``request`` raises RuntimeError at capacity. ``resolve`` and ``consume``
    return False for unknown, expired, mismatched or already-used approvals.
    Status snapshots cannot be mutated to grant approval. Successful consumption
    removes the entry; status thereafter returns None. Capacity includes live
    approvals as well as pending requests, so approving without consuming cannot
    grow memory indefinitely. Restarting the process invalidates every ID.
    """

    def __init__(
        self,
        ttl_seconds: float = 60.0,
        max_pending: int = 32,
        voice_min_confidence: float = 0.72,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(ttl_seconds) or not 0 < ttl_seconds <= 300:
            raise ValueError("confirmation TTL must be in (0, 300] seconds")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or not 1 <= max_pending <= 1024:
            raise ValueError("pending confirmation limit must be between 1 and 1024")
        if not math.isfinite(voice_min_confidence) or not 0.72 <= voice_min_confidence <= 1:
            raise ValueError("voice confirmation confidence must be between 0.72 and 1")
        self._ttl = ttl_seconds
        self._max_pending = max_pending
        self._voice_min_confidence = voice_min_confidence
        self._clock = clock
        self._lock = threading.Lock()
        self._hash_key = secrets.token_bytes(32)
        self._requests: dict[str, ConfirmationRequest] = {}
        self._deadlines: dict[str, float] = {}

    def _arguments_hash(self, arguments: dict[str, Any]) -> str:
        # A per-process keyed hash prevents dictionary attacks on small secret
        # values while retaining deterministic argument binding within a service.
        def validate_json(value: Any) -> None:
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise ValueError("JSON object keys must be strings")
                for item in value.values():
                    validate_json(item)
            elif isinstance(value, list):
                for item in value:
                    validate_json(item)
            elif type(value) not in {str, int, float, bool, type(None)}:
                raise ValueError("unsupported JSON value")

        try:
            validate_json(arguments)
            payload = json.dumps(
                arguments, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True, allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("confirmation arguments must be finite JSON data") from exc
        if not isinstance(arguments, dict) or len(payload) > 65_536:
            raise ValueError("confirmation arguments exceed the JSON object limit")
        return hmac.new(self._hash_key, payload, hashlib.sha256).hexdigest()

    def _expire(self) -> None:
        """Called only while holding the service lock."""
        now = self._clock()
        for request_id, request in self._requests.items():
            if (
                request.state in {ConfirmationState.PENDING, ConfirmationState.APPROVED}
                and now >= self._deadlines[request_id]
            ):
                self._requests[request_id] = replace(request, state=ConfirmationState.EXPIRED)

    @staticmethod
    def _sanitize_summary(summary: str, arguments: dict[str, Any]) -> str:
        """Remove control/bidi characters and known sensitive argument values.

        Summaries come only from trusted tool code (never an LLM description).
        The tool must select safe fields, e.g. action and root-relative path;
        arbitrary prose cannot be classified for privacy by this sanitizer.
        Renderers must still escape text for their output medium, e.g. HTML.
        """
        sensitive = {"content", "password", "secret", "token", "key", "credential", "auth"}

        def redact_values(value: Any, *, protected: bool = False) -> None:
            nonlocal summary
            if isinstance(value, dict):
                for key, item in value.items():
                    redact_values(item, protected=protected or any(s in key.lower() for s in sensitive))
            elif isinstance(value, list):
                for item in value:
                    redact_values(item, protected=protected)
            elif protected and isinstance(value, str) and value:
                summary = summary.replace(value, "[redacted]")

        redact_values(arguments)
        clean = "".join(
            " " if char.isspace() else char
            for char in summary
            if char.isspace() or not unicodedata.category(char).startswith("C")
        )
        return " ".join(clean.split())[:200]

    def request(
        self, tool_name: str, arguments: dict[str, Any], *, summary: str | None = None,
    ) -> ConfirmationRequest:
        """Create a prompt from the optional trusted tool summary, without content."""
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", tool_name) is None:
            raise ValueError("invalid confirmation tool identifier")
        digest = self._arguments_hash(arguments)
        if summary is not None and not isinstance(summary, str):
            raise ValueError("confirmation summary must be text")
        safe_summary = self._sanitize_summary(summary or "", arguments)
        if not safe_summary:
            safe_summary = f"Confirmar la acción de la herramienta «{tool_name}»."
        with self._lock:
            self._expire()
            if sum(r.state is ConfirmationState.PENDING for r in self._requests.values()) >= self._max_pending:
                raise RuntimeError("pending confirmation limit reached")
            # Keep terminal status observable until capacity is needed, while
            # never evicting an unexpired approval to make room for a request.
            if len(self._requests) >= self._max_pending * 2:
                for request_id, request in list(self._requests.items()):
                    if request.state in {ConfirmationState.DENIED, ConfirmationState.EXPIRED}:
                        del self._requests[request_id]
                        del self._deadlines[request_id]
            if len(self._requests) >= self._max_pending * 2:
                raise RuntimeError("live confirmation limit reached")
            created_at = datetime.now(UTC)
            request = ConfirmationRequest(
                id=secrets.token_urlsafe(32),
                tool_name=tool_name,
                summary=safe_summary,
                created_at=created_at,
                expires_at=created_at + timedelta(seconds=self._ttl),
                state=ConfirmationState.PENDING,
                arguments_hash=digest,
            )
            self._requests[request.id] = request
            self._deadlines[request.id] = self._clock() + self._ttl
            return request

    def resolve(
        self,
        request_id: str,
        approved: bool,
        source: Literal["voice", "panel"],
        stt_confidence: float | None = None,
        truncated: bool = False,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> bool:
        """Resolve once from trusted human input, optionally checking fresh args.

        The ID binds the original digest even when args are omitted here;
        ``consume`` always rechecks the actual execution arguments.
        """
        if source not in {"voice", "panel"} or not isinstance(approved, bool):
            return False
        if source == "voice" and (
            truncated
            or isinstance(stt_confidence, bool)
            or stt_confidence is None
            or not math.isfinite(stt_confidence)
            or not self._voice_min_confidence <= stt_confidence <= 1
        ):
            return False
        try:
            digest = self._arguments_hash(arguments) if arguments is not None else None
        except ValueError:
            return False
        with self._lock:
            self._expire()
            request = self._requests.get(request_id)
            if request is None or request.state is not ConfirmationState.PENDING:
                return False
            if digest is not None and not hmac.compare_digest(digest, request.arguments_hash):
                return False
            self._requests[request_id] = replace(
                request,
                state=ConfirmationState.APPROVED if approved else ConfirmationState.DENIED,
            )
            return True

    def status(self, request_id: str) -> ConfirmationRequest | None:
        """Return an immutable snapshot without refreshing its TTL."""
        with self._lock:
            self._expire()
            return self._requests.get(request_id)

    def consume(self, request_id: str, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Atomically redeem an unexpired approval once, for its exact action."""
        try:
            digest = self._arguments_hash(arguments)
        except ValueError:
            return False
        with self._lock:
            self._expire()
            request = self._requests.get(request_id)
            if (
                request is None
                or request.state is not ConfirmationState.APPROVED
                or request.tool_name != tool_name
                or not hmac.compare_digest(digest, request.arguments_hash)
            ):
                return False
            del self._requests[request_id]
            del self._deadlines[request_id]
            return True

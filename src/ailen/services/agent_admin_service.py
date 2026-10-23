"""Read-only agent administration and human confirmation actions."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ailen.core.config import AILENConfig
from ailen.core.confirmation import (
    ConfirmationRequest,
    ConfirmationService,
    ConfirmationState,
    PendingConfirmationView,
)
from ailen.domain.models import ToolEvent


@dataclass(frozen=True, slots=True)
class PendingAgentConfirmation:
    id: str
    tool_name: str
    summary: str
    seconds_remaining: int


@dataclass(frozen=True, slots=True)
class AgentToolEvent:
    tool_name: str
    status: str
    created_at: str
    arguments_redacted: str


@dataclass(frozen=True, slots=True)
class AgentSnapshot:
    max_autonomy_level: int
    file_roots: tuple[str, ...]
    confirmations: tuple[PendingAgentConfirmation, ...]
    confirmations_available: bool
    events: tuple[AgentToolEvent, ...]
    events_available: bool


class AgentAdminError(ValueError):
    """Controlled error for an unavailable, expired, or resolved request."""


class AgentAdmin(Protocol):
    def snapshot(self) -> AgentSnapshot: ...
    def approve(self, confirmation_id: str) -> None: ...
    def deny(self, confirmation_id: str) -> None: ...


class AgentEventsProvider(Protocol):
    def recent_tool_events(self, limit: int) -> Sequence[ToolEvent]: ...


class PendingConfirmationProvider(Protocol):
    def pending_requests(self) -> Sequence[PendingConfirmationView | ConfirmationRequest]: ...


def _redacted_event_arguments(value: str) -> str:
    """Defensively omit content/private values even from pre-redacted audit JSON."""

    sensitive = {"content", "password", "secret", "token", "key", "credential", "auth"}

    def redact(item: object) -> object:
        if isinstance(item, dict):
            return {
                str(key): redact(child)
                for key, child in item.items()
                if not any(part in str(key).lower() for part in sensitive)
            }
        if isinstance(item, list):
            return [redact(child) for child in item]
        if isinstance(item, str) and len(item) > 200:
            return f"[redacted len={len(item)}]"
        return item

    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return "[redacted invalid audit arguments]"
    return json.dumps(redact(parsed), ensure_ascii=False, separators=(",", ":"))[:2000]


class AgentAdminService:
    """Build a bounded administrative snapshot; caller owns auth and CSRF."""

    def __init__(
        self,
        config_provider: Callable[[], AILENConfig],
        confirmations: ConfirmationService | None,
        events_provider: AgentEventsProvider | None,
    ) -> None:
        self._config_provider = config_provider
        self._confirmations = confirmations
        self._events_provider = events_provider

    @staticmethod
    def _autonomy(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return 1
        return min(3, max(1, value))

    def _pending(self) -> tuple[tuple[PendingAgentConfirmation, ...], bool]:
        service = self._confirmations
        if service is None:
            return (), False
        lister = getattr(service, "pending_requests", None)
        if not callable(lister):
            return (), False
        try:
            requests = lister()
            now = datetime.now(UTC)
            pending = []
            for item in requests:
                if isinstance(item, PendingConfirmationView):
                    pending.append(
                        PendingAgentConfirmation(
                            id=item.id,
                            tool_name=item.tool_name[:80],
                            summary=item.summary[:200],
                            seconds_remaining=max(0, int(item.remaining_seconds)),
                        )
                    )
                elif isinstance(item, ConfirmationRequest):
                    if item.state is not ConfirmationState.PENDING:
                        continue
                    remaining = max(0, math.ceil((item.expires_at - now).total_seconds()))
                    pending.append(
                        PendingAgentConfirmation(
                            id=item.id,
                            tool_name=item.tool_name[:80],
                            summary=item.summary[:200],
                            seconds_remaining=remaining,
                        )
                    )
                elif hasattr(item, "id") and hasattr(item, "tool_name") and hasattr(item, "summary"):
                    rem = getattr(item, "remaining_seconds", None)
                    if rem is None:
                        rem = getattr(item, "seconds_remaining", 0)
                    try:
                        seconds = int(rem) if rem is not None else 0
                    except (TypeError, ValueError):
                        seconds = 0
                    pending.append(
                        PendingAgentConfirmation(
                            id=str(item.id),
                            tool_name=str(item.tool_name)[:80],
                            summary=str(item.summary)[:200],
                            seconds_remaining=max(0, seconds),
                        )
                    )
            return tuple(pending[:50]), True
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return (), False

    def snapshot(self) -> AgentSnapshot:
        try:
            cfg = self._config_provider()
            agent = cfg.agent
            autonomy = self._autonomy(getattr(agent, "max_autonomy_level", 1))
            roots_value = getattr(agent, "file_roots", ())
            roots = tuple(str(root)[:500] for root in roots_value if isinstance(root, str))[:50]
        except (AttributeError, TypeError, ValueError, RuntimeError):
            autonomy, roots = 1, ()

        confirmations, confirmations_available = self._pending()
        events_available = self._events_provider is not None
        events: tuple[AgentToolEvent, ...] = ()
        if self._events_provider is not None:
            try:
                source_events = self._events_provider.recent_tool_events(50)
                events = tuple(
                    AgentToolEvent(
                        tool_name=event.tool_name[:80],
                        status="OK" if event.success else "ERROR",
                        created_at=event.created_at,
                        arguments_redacted=_redacted_event_arguments(event.arguments_redacted),
                    )
                    for event in list(source_events)[:50]
                )
            except (AttributeError, TypeError, ValueError, RuntimeError):
                events_available = False
                events = ()
        return AgentSnapshot(autonomy, roots, confirmations, confirmations_available, events, events_available)

    def approve(self, confirmation_id: str) -> None:
        self._resolve(confirmation_id, approved=True)

    def deny(self, confirmation_id: str) -> None:
        self._resolve(confirmation_id, approved=False)

    def _resolve(self, confirmation_id: str, *, approved: bool) -> None:
        if (
            self._confirmations is None
            or not isinstance(confirmation_id, str)
            or not self._confirmations.resolve(confirmation_id, approved, source="panel")
        ):
            raise AgentAdminError("La solicitud no existe, venció o ya fue resuelta.")

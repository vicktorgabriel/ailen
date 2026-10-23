"""Realtime tool bridge, privacy policy gate, and audio budget guard (ADR-014, ADR-015)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

from ailen.ai.realtime.contracts import (
    RealtimeEvent,
    RealtimeEventType,
    RealtimeProviderConfig,
    RealtimeSession,
)
from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import AutonomyLevel, ToolContext, ToolResult
from ailen.tools.executor import ToolExecutor

DEFAULT_SAMPLE_RATE_HZ: int = 16_000
PCM16_16K_MONO_BYTES_PER_SECOND: int = DEFAULT_SAMPLE_RATE_HZ * 2  # 32,000 bytes/s
MAX_OUTBOUND_TOOL_TEXT_CHARS: int = 512


class RealtimePrivacyError(PermissionError):
    """Raised when a realtime voice session is forbidden by privacy policy."""


class RealtimeBudgetExceededError(RuntimeError):
    """Raised when a realtime session exhausts its configured audio/session minute budget."""

    def __init__(self, message: str = "Realtime audio budget exhausted") -> None:
        super().__init__(message)
        self.error_code = ErrorCode.AI_BUDGET_EXCEEDED


class BudgetGuard:
    """Tracks both PCM audio duration and monotonic session wall-clock time.

    Uses the real sample rate configured in RealtimeProviderConfig (default 16000 Hz,
    2 bytes per PCM16LE mono sample) rather than a fixed 32000 B/s constant, and
    closes the bound RealtimeSession immediately upon budget exhaustion.
    """

    def __init__(
        self,
        max_audio_minutes: float,
        session: RealtimeSession | None = None,
        bytes_per_second: int | None = None,
        *,
        sample_rate_hz: int | None = None,
        config: RealtimeProviderConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_audio_minutes <= 0:
            raise ValueError("max_audio_minutes must be positive")
        self.max_audio_minutes = float(max_audio_minutes)
        self.max_seconds = self.max_audio_minutes * 60.0

        self._custom_rate = bytes_per_second is not None or sample_rate_hz is not None
        if bytes_per_second is not None:
            if bytes_per_second <= 0:
                raise ValueError("bytes_per_second must be positive")
            self.bytes_per_second = int(bytes_per_second)
            self.sample_rate_hz = max(1, self.bytes_per_second // 2)
        else:
            resolved_sr = sample_rate_hz
            if resolved_sr is None and config is not None:
                resolved_sr = config.sample_rate_hz
            if resolved_sr is None and session is not None:
                session_cfg = getattr(session, "config", None)
                if isinstance(session_cfg, RealtimeProviderConfig):
                    resolved_sr = session_cfg.sample_rate_hz
            if resolved_sr is None:
                resolved_sr = DEFAULT_SAMPLE_RATE_HZ
            if resolved_sr <= 0:
                raise ValueError("sample_rate_hz must be positive")
            self.sample_rate_hz = int(resolved_sr)
            self.bytes_per_second = self.sample_rate_hz * 2

        self._session = session
        self._clock = clock
        self._started_at: float = float(self._clock())
        self._audio_seconds: float = 0.0
        self._exhausted: bool = False

    def bind_session(self, session: RealtimeSession) -> None:
        """Bind the session to close automatically when the budget is exhausted."""
        self._session = session
        if not self._custom_rate:
            session_cfg = getattr(session, "config", None)
            if isinstance(session_cfg, RealtimeProviderConfig):
                self.sample_rate_hz = session_cfg.sample_rate_hz
                self.bytes_per_second = session_cfg.bytes_per_second

    def start(self) -> None:
        """Reset monotonic session start clock if not yet exhausted."""
        if not self._exhausted and self._audio_seconds == 0.0:
            self._started_at = float(self._clock())

    @property
    def audio_seconds(self) -> float:
        """Total PCM audio seconds accounted for so far."""
        return self._audio_seconds

    @property
    def wall_seconds(self) -> float:
        """Elapsed monotonic wall-clock seconds since session start."""
        return max(0.0, float(self._clock()) - self._started_at)

    @property
    def consumed_seconds(self) -> float:
        """Effective budget seconds consumed (max of audio duration and wall-clock time)."""
        return max(self._audio_seconds, self.wall_seconds)

    @property
    def consumed_minutes(self) -> float:
        """Effective budget minutes consumed so far."""
        return self.consumed_seconds / 60.0

    @property
    def remaining_seconds(self) -> float:
        """Remaining seconds before budget exhaustion."""
        return max(0.0, self.max_seconds - self.consumed_seconds)

    @property
    def exhausted(self) -> bool:
        """Whether the audio or wall-clock budget has been reached or exceeded."""
        return self._exhausted or (self.consumed_seconds >= self.max_seconds)

    def check_budget(self) -> None:
        """Verify neither audio duration nor monotonic session clock exceeded max_seconds."""
        if self._exhausted or self.consumed_seconds >= self.max_seconds:
            self._exhausted = True
            if self._session is not None:
                self._session.close()
            raise RealtimeBudgetExceededError(
                f"Realtime audio budget exhausted: {self.consumed_minutes:.2f}/"
                f"{self.max_audio_minutes:.2f} min"
            )

    def record_audio_bytes(self, num_bytes: int) -> None:
        """Account for PCM16LE mono audio bytes at configured sample_rate_hz and enforce budget."""
        if num_bytes < 0:
            raise ValueError("num_bytes must be non-negative")
        self.record_seconds(num_bytes / self.bytes_per_second)

    def record_seconds(self, seconds: float) -> None:
        """Account for audio duration in seconds and close session if budget is exhausted."""
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._audio_seconds += seconds
        self.check_budget()


class ReadOnlyBudgetView:
    """Read-only proxy over BudgetGuard so callers cannot mutate or bypass the budget gate."""

    __slots__ = ("_guard",)

    def __init__(self, guard: BudgetGuard) -> None:
        object.__setattr__(self, "_guard", guard)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("ReadOnlyBudgetView is immutable")

    @property
    def max_audio_minutes(self) -> float:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.max_audio_minutes

    @property
    def max_seconds(self) -> float:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.max_seconds

    @property
    def sample_rate_hz(self) -> int:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.sample_rate_hz

    @property
    def bytes_per_second(self) -> int:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.bytes_per_second

    @property
    def audio_seconds(self) -> float:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.audio_seconds

    @property
    def wall_seconds(self) -> float:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.wall_seconds

    @property
    def consumed_seconds(self) -> float:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.consumed_seconds

    @property
    def consumed_minutes(self) -> float:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.consumed_minutes

    @property
    def remaining_seconds(self) -> float:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.remaining_seconds

    @property
    def exhausted(self) -> bool:
        guard: BudgetGuard = object.__getattribute__(self, "_guard")
        return guard.exhausted


class RealtimeToolBridge:
    """Bridges RealtimeSession tool_call events to ToolExecutor under Core policies.

    Enforces ADR-014 and ADR-015:
    - Refuses to open or continue a realtime voice session in SocialMode.SHOP or SocialMode.PUBLIC.
    - Reads SocialMode and max_autonomy from live sources on every call.
    - Combines timeout_seconds and network_access_allowed with ToolContext using the
      most restrictive value when both are supplied.
    - Never executes tool names absent from ToolRegistry.
    - Applies the minimum OutboundPrivacyPolicy filter on tool results: sends only bounded
      message/summary and includes 'data' exclusively for tools with PrivacyLevel.PUBLIC.
    - Consumes TOOL_CALL events without re-emitting them to avoid double execution.
    - Closes the session immediately when BudgetGuard exhausts max_audio_minutes.
    """

    FORBIDDEN_MODES: frozenset[SocialMode] = frozenset({SocialMode.SHOP, SocialMode.PUBLIC})

    def __init__(
        self,
        session: RealtimeSession,
        executor: ToolExecutor,
        mode: SocialMode | Callable[[], SocialMode] | None = None,
        max_autonomy: AutonomyLevel | Callable[[], AutonomyLevel] | None = None,
        context: ToolContext | Callable[[], ToolContext] | None = None,
        budget: BudgetGuard | None = None,
        max_audio_minutes: float = 15.0,
        session_id: str | None = None,
        network_access_allowed: bool | None = None,
        timeout_seconds: float | None = None,
        *,
        mode_provider: Callable[[], SocialMode] | None = None,
        autonomy_provider: Callable[[], AutonomyLevel] | None = None,
        context_provider: Callable[[], ToolContext] | None = None,
        config: RealtimeProviderConfig | None = None,
    ) -> None:
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._session = session
        self.executor = executor
        self._mode_source = mode_provider if mode_provider is not None else mode
        self._autonomy_source = (
            autonomy_provider if autonomy_provider is not None else max_autonomy
        )
        self._context_source = (
            context_provider if context_provider is not None else context
        )
        self._session_id = session_id
        self._network_access_allowed = network_access_allowed
        self._timeout_seconds = timeout_seconds
        self._executed_call_ids: set[str] = set()

        if budget is not None:
            self._budget = budget
            self._budget.bind_session(session)
        else:
            self._budget = BudgetGuard(
                max_audio_minutes=max_audio_minutes,
                session=session,
                config=config,
            )
        self._budget_view = ReadOnlyBudgetView(self._budget)

    @property
    def budget(self) -> ReadOnlyBudgetView:
        """Read-only view of the session budget guard."""
        return self._budget_view

    def _resolve_base_context(self) -> ToolContext | None:
        if self._context_source is None:
            return None
        if callable(self._context_source):
            return self._context_source()
        return self._context_source

    def _resolve_live_mode(self, base_ctx: ToolContext | None = None) -> SocialMode:
        if self._mode_source is not None:
            return self._mode_source() if callable(self._mode_source) else self._mode_source
        ctx = base_ctx if base_ctx is not None else self._resolve_base_context()
        if ctx is not None:
            return ctx.mode
        return SocialMode.WORKSHOP

    def _resolve_live_autonomy(self, base_ctx: ToolContext | None = None) -> AutonomyLevel:
        if self._autonomy_source is not None:
            return (
                self._autonomy_source()
                if callable(self._autonomy_source)
                else self._autonomy_source
            )
        ctx = base_ctx if base_ctx is not None else self._resolve_base_context()
        if ctx is not None:
            return ctx.max_autonomy
        return AutonomyLevel.N1

    def _build_live_context(self) -> ToolContext:
        base_ctx = self._resolve_base_context()
        effective_mode = self._resolve_live_mode(base_ctx)
        effective_autonomy = self._resolve_live_autonomy(base_ctx)

        if base_ctx is None:
            effective_timeout = (
                self._timeout_seconds if self._timeout_seconds is not None else 5.0
            )
            effective_network = (
                bool(self._network_access_allowed)
                if self._network_access_allowed is not None
                else False
            )
            return ToolContext(
                session_id=self._session_id,
                mode=effective_mode,
                timeout_seconds=effective_timeout,
                network_access_allowed=effective_network,
                max_autonomy=effective_autonomy,
            )

        if base_ctx.timeout_seconds <= 0:
            raise ValueError("context.timeout_seconds must be positive")

        if self._timeout_seconds is not None:
            effective_timeout = min(float(self._timeout_seconds), float(base_ctx.timeout_seconds))
        else:
            effective_timeout = float(base_ctx.timeout_seconds)

        if self._network_access_allowed is not None:
            effective_network = bool(
                self._network_access_allowed and base_ctx.network_access_allowed
            )
        else:
            effective_network = bool(base_ctx.network_access_allowed)

        if self._autonomy_source is not None and callable(self._context_source) is False:
            # Combine explicitly with base_ctx.max_autonomy when both are supplied
            pass

        return ToolContext(
            session_id=(
                self._session_id if self._session_id is not None else base_ctx.session_id
            ),
            mode=effective_mode,
            privacy_level=base_ctx.privacy_level,
            correlation_id=base_ctx.correlation_id,
            timeout_seconds=effective_timeout,
            user_id=base_ctx.user_id,
            internet_available=base_ctx.internet_available,
            network_access_allowed=effective_network,
            max_autonomy=effective_autonomy,
            confirmation_id=base_ctx.confirmation_id,
        )

    @property
    def context(self) -> ToolContext:
        """Construct the current effective ToolContext from live sources."""
        return self._build_live_context()

    @property
    def mode(self) -> SocialMode:
        """Active live social mode for the session."""
        return self._resolve_live_mode()

    @property
    def max_autonomy(self) -> AutonomyLevel:
        """Maximum live autonomy level allowed for tool calls in this session."""
        return self._resolve_live_autonomy()

    def _ensure_mode_allowed(self) -> ToolContext:
        live_ctx = self._build_live_context()
        if live_ctx.mode in self.FORBIDDEN_MODES:
            self._session.close()
            raise RealtimePrivacyError(
                f"Realtime voice session is denied in SocialMode.{live_ctx.mode.value} "
                "(ADR-015 privacy policy)"
            )
        return live_ctx

    def connect(self) -> None:
        """Validate privacy policy and budget, then open the underlying realtime session."""
        self._ensure_mode_allowed()
        self._budget.start()
        self._budget.check_budget()
        self._session.connect()

    def open(self) -> None:
        """Alias for connect()."""
        self.connect()

    def send_audio(self, pcm16le_16k_mono: bytes) -> None:
        """Check live privacy policy and budget, then forward PCM audio to the session."""
        self._ensure_mode_allowed()
        self._budget.record_audio_bytes(len(pcm16le_16k_mono))
        self._session.send_audio(pcm16le_16k_mono)

    def execute(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        call_id: str = "",
    ) -> ToolResult:
        """Alias for handle_tool_call() enforcing live privacy and allowlist gates."""
        return self.handle_tool_call(name=name, args=args, call_id=call_id)

    def handle_tool_call(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        call_id: str = "",
    ) -> ToolResult:
        """Execute an allowlisted tool via ToolExecutor and send sanitized result to session.

        Applies the minimum OutboundPrivacyPolicy filter (ADR-015 §3):
        only bounded message/summary are forwarded to the remote provider, and
        result.data is included exclusively if the registered tool declares
        PrivacyLevel.PUBLIC.
        """
        live_ctx = self._ensure_mode_allowed()
        self._budget.check_budget()

        if call_id and call_id in self._executed_call_ids:
            duplicate = ToolResult(
                success=False,
                tool_name=name,
                status_code="DUPLICATE_CALL",
                message=f"Llamada de herramienta duplicada ignorada: {call_id}",
                error_code=ErrorCode.TOOL_DENIED,
            )
            return duplicate

        if call_id:
            self._executed_call_ids.add(call_id)

        tool = self.executor.registry.get(name)
        if tool is None:
            denied = ToolResult(
                success=False,
                tool_name=name,
                status_code="UNKNOWN_TOOL",
                message=f"Herramienta no registrada: {name}",
                error_code=ErrorCode.TOOL_NOT_FOUND,
            )
            self._session.send_tool_result(
                call_id,
                self._serialize_result(denied, include_data=False),
            )
            return denied

        result = self.executor.execute(
            tool_name=name,
            args=dict(args or {}),
            context=live_ctx,
        )
        is_public = getattr(tool, "privacy_level", None) == PrivacyLevel.PUBLIC
        self._session.send_tool_result(
            call_id,
            self._serialize_result(result, include_data=is_public),
        )
        return result

    def handle_event(self, event: RealtimeEvent) -> RealtimeEvent | None:
        """Process a single incoming RealtimeEvent, enforcing live mode, budget, and tool routing.

        Returns None when a TOOL_CALL event is handled by the bridge so consumers
        do not re-execute the tool call a second time.
        """
        self._ensure_mode_allowed()
        self._budget.check_budget()
        if event.type == RealtimeEventType.AUDIO_OUT and event.audio:
            self._budget.record_audio_bytes(len(event.audio))
        elif event.type == RealtimeEventType.TOOL_CALL:
            self.handle_tool_call(
                name=event.name,
                args=event.args,
                call_id=event.call_id,
            )
            return None
        return event

    def events(self) -> Iterator[RealtimeEvent]:
        """Iterate over session events while enforcing live mode, budget, and tool execution."""
        self._ensure_mode_allowed()
        self._budget.check_budget()
        for event in self._session.events():
            try:
                processed = self.handle_event(event)
            except RealtimeBudgetExceededError as exc:
                yield RealtimeEvent.error_event(
                    str(exc),
                    error_code=ErrorCode.AI_BUDGET_EXCEEDED,
                )
                yield RealtimeEvent.closed("budget_exceeded")
                return
            if processed is not None:
                yield processed
            if event.type == RealtimeEventType.CLOSED:
                return

    def cancel(self) -> None:
        """Propagate barge-in cancellation to the underlying realtime session."""
        self._session.cancel()

    def close(self) -> None:
        """Close the underlying realtime session."""
        self._session.close()

    @staticmethod
    def _serialize_result(
        result: ToolResult,
        *,
        include_data: bool = False,
    ) -> dict[str, Any]:
        """Serialize ToolResult under the minimum OutboundPrivacyPolicy filter (ADR-015).

        Only bounded message and summary strings are sent to the remote provider.
        Structured 'data' is included exclusively when the tool has PrivacyLevel.PUBLIC;
        for PRIVATE, RESTRICTED, or unknown tools, 'data' is omitted.
        """
        bounded_message = (result.message or "")[:MAX_OUTBOUND_TOOL_TEXT_CHARS]
        bounded_summary = (result.summary or "")[:MAX_OUTBOUND_TOOL_TEXT_CHARS]
        payload: dict[str, Any] = {
            "success": result.success,
            "tool_name": result.tool_name,
            "status_code": result.status_code,
            "message": bounded_message,
            "summary": bounded_summary,
            "error_code": result.error_code.value if result.error_code else None,
        }
        if include_data:
            payload["data"] = dict(result.data)
        return payload


__all__ = [
    "DEFAULT_SAMPLE_RATE_HZ",
    "MAX_OUTBOUND_TOOL_TEXT_CHARS",
    "PCM16_16K_MONO_BYTES_PER_SECOND",
    "BudgetGuard",
    "ReadOnlyBudgetView",
    "RealtimeBudgetExceededError",
    "RealtimePrivacyError",
    "RealtimeToolBridge",
]

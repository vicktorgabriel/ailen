"""Tool executor for AILEN Core.

Enforces tool allowlisting, argument schemas, social mode permissions,
privacy levels, timeouts, event emissions, and audit logging.
Prohibits arbitrary shell execution.
"""

import json
import logging
import queue
import threading
import time
import uuid
from typing import Any

from ailen.core.events import EventBus
from ailen.domain.enums import ErrorCode, EventType, PrivacyLevel, SocialMode
from ailen.domain.models import CoreEvent
from ailen.memory.repository import MemoryRepository
from ailen.tools.contracts import ToolContext, ToolResult, validate_args
from ailen.tools.registry import ToolRegistry

logger = logging.getLogger("ailen.tools.executor")


class ToolExecutor:
    """Secure controlled executor for AILEN tools."""

    def __init__(
        self,
        registry: ToolRegistry,
        event_bus: EventBus | None = None,
        repository: MemoryRepository | None = None,
    ) -> None:
        self.registry = registry
        self.event_bus = event_bus
        self.repository = repository

    def is_side_effecting(self, tool_name: str, args: dict[str, Any] | None = None) -> bool:
        """Ask the allowlisted tool whether a request mutates state.

        Unknown tools, missing declarations and classifier failures are
        treated as side-effecting so voice safety fails closed.
        """
        tool = self.registry.get(tool_name)
        if tool is None:
            return True
        classifier = getattr(tool, "is_side_effecting", None)
        if not callable(classifier):
            logger.warning("Tool '%s' has no side-effect declaration; failing closed", tool_name)
            return True
        try:
            return bool(classifier(dict(args or {})))
        except Exception:
            logger.exception("Tool '%s' side-effect declaration failed; failing closed", tool_name)
            return True

    def execute(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        context: ToolContext | None = None,
    ) -> ToolResult:
        """Execute a tool with full policy, validation, timeout, and audit controls."""
        start_time = time.monotonic()
        ctx = context or ToolContext()
        raw_args = args or {}

        # 1. Tool registration check
        tool = self.registry.get(tool_name)
        if tool is None:
            latency_ms = (time.monotonic() - start_time) * 1000.0
            msg = f"Herramienta no registrada: {tool_name}"
            logger.warning("Tool execution rejected: %s", msg)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                status_code="UNKNOWN_TOOL",
                message=msg,
                error_code=ErrorCode.TOOL_NOT_FOUND,
                latency_ms=latency_ms,
            )

        # 2. Social Mode check
        allowed_modes = getattr(tool, "allowed_modes", None)
        if allowed_modes is not None and ctx.mode not in allowed_modes:
            latency_ms = (time.monotonic() - start_time) * 1000.0
            msg = f"Herramienta '{tool_name}' no permitida en modo {ctx.mode.value}"
            logger.warning("Tool execution mode denied: %s", msg)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                status_code="MODE_DENIED",
                message=msg,
                error_code=ErrorCode.TOOL_DENIED,
                latency_ms=latency_ms,
            )

        # 3. Privacy boundary check (Public / Shop modes reject private tools)
        tool_privacy = getattr(tool, "privacy_level", PrivacyLevel.PRIVATE)
        if ctx.mode in {SocialMode.SHOP, SocialMode.PUBLIC} and tool_privacy == PrivacyLevel.PRIVATE:
            latency_ms = (time.monotonic() - start_time) * 1000.0
            msg = f"Herramienta privada '{tool_name}' bloqueada en modo {ctx.mode.value}"
            logger.warning("Tool execution privacy denied: %s", msg)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                status_code="PRIVACY_DENIED",
                message=msg,
                error_code=ErrorCode.TOOL_DENIED,
                latency_ms=latency_ms,
            )

        # 3b. Network availability check for tools that require connectivity
        if getattr(tool, "requires_network", False) and not ctx.network_access_allowed:
            latency_ms = (time.monotonic() - start_time) * 1000.0
            msg = f"Herramienta '{tool_name}' requiere acceso de red y la política outbound está deshabilitada."
            logger.warning("Tool execution network denied: %s", msg)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                status_code="NETWORK_UNAVAILABLE",
                message=msg,
                error_code=ErrorCode.TOOL_UNAVAILABLE,
                latency_ms=latency_ms,
            )

        # 3c. Destructive tools require explicit confirmation and never run in PUBLIC/SHOP
        if getattr(tool, "destructive", False):
            if ctx.mode in {SocialMode.SHOP, SocialMode.PUBLIC}:
                latency_ms = (time.monotonic() - start_time) * 1000.0
                msg = f"Herramienta destructiva '{tool_name}' bloqueada en modo {ctx.mode.value}."
                logger.warning("Destructive tool denied in public mode: %s", msg)
                return ToolResult(
                    success=False,
                    tool_name=tool_name,
                    status_code="DESTRUCTIVE_MODE_DENIED",
                    message=msg,
                    error_code=ErrorCode.TOOL_DENIED,
                    latency_ms=latency_ms,
                )
            if raw_args.get("confirm") is not True:
                latency_ms = (time.monotonic() - start_time) * 1000.0
                msg = f"Herramienta destructiva '{tool_name}' requiere confirmación explícita (confirm=true)."
                logger.warning("Destructive tool without confirmation rejected: %s", msg)
                return ToolResult(
                    success=False,
                    tool_name=tool_name,
                    status_code="CONFIRMATION_REQUIRED",
                    message=msg,
                    error_code=ErrorCode.TOOL_DENIED,
                    latency_ms=latency_ms,
                )
            latency_ms = (time.monotonic() - start_time) * 1000.0
            msg = (
                f"Herramienta destructiva '{tool_name}' no puede ejecutarse todavía: "
                "R3C no dispone de un límite de ejecución cancelable/aislado."
            )
            logger.warning("Destructive tool rejected until cancellable executor exists: %s", msg)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                status_code="DESTRUCTIVE_EXECUTION_UNSUPPORTED",
                message=msg,
                error_code=ErrorCode.TOOL_DENIED,
                latency_ms=latency_ms,
            )

        # 4. Argument validation
        try:
            validated_args = validate_args(tool.schema, raw_args)
        except ValueError as exc:
            latency_ms = (time.monotonic() - start_time) * 1000.0
            msg = f"Argumentos inválidos para {tool_name}: {exc}"
            logger.warning("Tool arg validation failed: %s", msg)
            return ToolResult(
                success=False,
                tool_name=tool_name,
                status_code="INVALID_ARGS",
                message=msg,
                error_code=ErrorCode.TOOL_ARGS_INVALID,
                latency_ms=latency_ms,
            )

        # 5. Emit TOOL_REQUESTED event
        self._emit_event(
            EventType.TOOL_REQUESTED,
            payload={
                "tool_name": tool_name,
                "session_id": ctx.session_id,
                "mode": ctx.mode.value,
            },
            correlation_id=ctx.correlation_id,
        )

        # 6. Execute non-destructive tools behind a daemon timeout boundary.
        # Python cannot safely kill a running thread, so destructive tools are
        # rejected above until an isolated cancellable executor exists. Daemon
        # workers ensure a timed-out non-destructive tool cannot block process
        # shutdown; built-ins must still implement bounded I/O internally.
        timeout = min(ctx.timeout_seconds, getattr(tool, "timeout_seconds", 10.0))
        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def run_tool() -> None:
            try:
                result_queue.put(("ok", tool.execute(validated_args, ctx)))
            except Exception as exc:  # noqa: BLE001
                result_queue.put(("error", exc))

        worker = threading.Thread(
            target=run_tool,
            name=f"ailen-tool-{tool_name}",
            daemon=True,
        )
        worker.start()

        result: ToolResult
        try:
            outcome, payload = result_queue.get(timeout=timeout)
            if outcome == "ok":
                result = payload
            else:
                raise payload
        except queue.Empty:
            latency_ms = (time.monotonic() - start_time) * 1000.0
            msg = f"Tiempo de espera agotado ejecutando herramienta '{tool_name}' ({timeout}s)"
            logger.warning("Tool timeout: %s", msg)
            result = ToolResult(
                success=False,
                tool_name=tool_name,
                status_code="TIMEOUT",
                message=msg,
                error_code=ErrorCode.TOOL_TIMEOUT,
                latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - start_time) * 1000.0
            msg = f"Fallo al ejecutar herramienta '{tool_name}': {exc}"
            logger.error("Tool execution error: %s", exc)
            result = ToolResult(
                success=False,
                tool_name=tool_name,
                status_code="EXECUTION_ERROR",
                message=msg,
                error_code=ErrorCode.UNKNOWN_ERROR,
                latency_ms=latency_ms,
            )

        # Finalize latency & tool_name if needed
        total_latency_ms = (time.monotonic() - start_time) * 1000.0
        if result.latency_ms <= 0.0:
            result.latency_ms = total_latency_ms
        if not result.tool_name:
            result.tool_name = tool_name

        # 7. Emit TOOL_COMPLETED event
        self._emit_event(
            EventType.TOOL_COMPLETED,
            payload={
                "tool_name": tool_name,
                "success": result.success,
                "status_code": result.status_code,
                "latency_ms": result.latency_ms,
                "session_id": ctx.session_id,
            },
            correlation_id=ctx.correlation_id,
        )

        # 8. Audit log in SQLite
        if self.repository is not None:
            try:
                redacted_args = self._redact_args(raw_args)
                self.repository.log_tool_event(
                    tool_name=tool_name,
                    arguments_redacted=json.dumps(redacted_args, ensure_ascii=False),
                    result_summary=result.message or result.summary,
                    success=result.success,
                    latency_ms=result.latency_ms,
                    session_id=ctx.session_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not log tool event to SQLite: %s", exc)

        return result

    def _emit_event(self, event_type: EventType, payload: dict[str, Any], correlation_id: str | None) -> None:
        if self.event_bus is None:
            return
        try:
            event = CoreEvent(
                event_id=f"evt-{uuid.uuid4().hex[:12]}",
                event_type=event_type,
                payload=payload,
                correlation_id=correlation_id,
                source="tool_executor",
            )
            self.event_bus.publish(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not publish tool event %s: %s", event_type, exc)

    def _redact_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact sensitive fields from audit logs."""
        sensitive_keys = {"password", "secret", "token", "key", "credential", "auth"}

        def redact_value(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: (
                        "[REDACTED]"
                        if any(marker in key.lower() for marker in sensitive_keys)
                        else redact_value(item)
                    )
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [redact_value(item) for item in value]
            return value

        return redact_value(args)

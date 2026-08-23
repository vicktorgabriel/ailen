"""Unit tests for ToolExecutor."""

import time
from typing import Any, ClassVar
from unittest.mock import MagicMock

from ailen.core.events import EventBus
from ailen.domain.enums import ErrorCode, EventType, PrivacyLevel, SocialMode
from ailen.tools.builtin.clock import ClockTool
from ailen.tools.builtin.notes import NotesTool
from ailen.tools.builtin.timer import TimerTool
from ailen.tools.contracts import ToolContext, ToolResult
from ailen.tools.executor import ToolExecutor
from ailen.tools.registry import ToolRegistry


class SlowTool:
    name: str = "slow_tool"
    description: str = "Simulates slow execution"
    schema: ClassVar[dict[str, Any]] = {"properties": {}}
    permissions: ClassVar[list[str]] = []
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 0.05

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        time.sleep(0.2)
        return ToolResult(success=True, message="Done")


class CrashingTool:
    name: str = "crashing_tool"
    description: str = "Simulates tool exception"
    schema: ClassVar[dict[str, Any]] = {"properties": {}}
    permissions: ClassVar[list[str]] = []
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 2.0

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        raise RuntimeError("Fatal internal error in tool")


def test_tool_executor_success() -> None:
    clock = ClockTool()
    registry = ToolRegistry([clock])
    event_bus = EventBus()
    events_received: list[Any] = []
    event_bus.subscribe(EventType.TOOL_REQUESTED, lambda e: events_received.append(e))
    event_bus.subscribe(EventType.TOOL_COMPLETED, lambda e: events_received.append(e))

    executor = ToolExecutor(registry=registry, event_bus=event_bus)
    result = executor.execute("clock", args={"format": "time"}, context=ToolContext(mode=SocialMode.HOME))

    assert result.success is True
    assert result.status_code == "OK"
    assert "Son las" in result.message
    assert result.latency_ms > 0.0
    assert len(events_received) == 2


def test_tool_executor_unknown_tool() -> None:
    registry = ToolRegistry()
    executor = ToolExecutor(registry=registry)
    result = executor.execute("non_existent_tool")

    assert result.success is False
    assert result.status_code == "UNKNOWN_TOOL"
    assert result.error_code == ErrorCode.TOOL_NOT_FOUND


def test_tool_executor_mode_denied() -> None:
    # timer is allowed in HOME, WORKSHOP, PRIVATE, but NOT in SHOP or PUBLIC
    timer = TimerTool()
    registry = ToolRegistry([timer])
    executor = ToolExecutor(registry=registry)

    result = executor.execute(
        "timer",
        args={"action": "list"},
        context=ToolContext(mode=SocialMode.SHOP),
    )

    assert result.success is False
    assert result.status_code == "MODE_DENIED"
    assert result.error_code == ErrorCode.TOOL_DENIED


def test_tool_executor_privacy_denied_in_public() -> None:
    # NotesTool has privacy_level = PRIVATE
    notes = NotesTool()
    registry = ToolRegistry([notes])
    executor = ToolExecutor(registry=registry)

    # Calling private tool in PUBLIC mode should be denied
    result = executor.execute(
        "notes",
        args={"action": "list"},
        context=ToolContext(mode=SocialMode.PUBLIC),
    )

    assert result.success is False
    assert result.status_code in {"MODE_DENIED", "PRIVACY_DENIED"}
    assert result.error_code == ErrorCode.TOOL_DENIED


def test_tool_executor_invalid_args() -> None:
    timer = TimerTool()
    registry = ToolRegistry([timer])
    executor = ToolExecutor(registry=registry)

    # Missing required 'action' argument
    result = executor.execute("timer", args={}, context=ToolContext(mode=SocialMode.HOME))
    assert result.success is False
    assert result.status_code == "INVALID_ARGS"
    assert result.error_code == ErrorCode.TOOL_ARGS_INVALID


def test_tool_executor_timeout() -> None:
    slow = SlowTool()
    registry = ToolRegistry([slow])
    executor = ToolExecutor(registry=registry)

    result = executor.execute("slow_tool", context=ToolContext(timeout_seconds=0.05))
    assert result.success is False
    assert result.status_code == "TIMEOUT"
    assert result.error_code == ErrorCode.TOOL_TIMEOUT


def test_tool_executor_handles_tool_exception() -> None:
    crashing = CrashingTool()
    registry = ToolRegistry([crashing])
    executor = ToolExecutor(registry=registry)

    result = executor.execute("crashing_tool")
    assert result.success is False
    assert result.status_code == "EXECUTION_ERROR"
    assert result.error_code == ErrorCode.UNKNOWN_ERROR


def test_tool_executor_audit_logging() -> None:
    class AuditedTool:
        name: str = "audited"
        description: str = "Test tool with sensitive field"
        schema: ClassVar[dict[str, Any]] = {
            "properties": {
                "api_key": {"type": "str", "required": False},
                "format": {"type": "str", "required": False},
            }
        }
        permissions: ClassVar[list[str]] = []
        allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
        privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
        requires_network: bool = False
        destructive: bool = False
        timeout_seconds: float = 2.0

        def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
            return ToolResult(success=True, message="OK")

    tool = AuditedTool()
    registry = ToolRegistry([tool])
    repo_mock = MagicMock()
    executor = ToolExecutor(registry=registry, repository=repo_mock)

    executor.execute(
        "audited",
        args={"format": "time", "api_key": "secret123"},
        context=ToolContext(session_id="sess-test", mode=SocialMode.WORKSHOP),
    )

    assert repo_mock.log_tool_event.called
    call_args = repo_mock.log_tool_event.call_args[1]
    assert call_args["tool_name"] == "audited"
    assert call_args["session_id"] == "sess-test"
    assert call_args["success"] is True
    # Secret should be redacted in audit log
    assert "[REDACTED]" in call_args["arguments_redacted"]
    assert "secret123" not in call_args["arguments_redacted"]


class NetworkTool:
    name: str = "net_tool"
    description: str = "Simulates a network-dependent tool"
    schema: ClassVar[dict[str, Any]] = {"properties": {}}
    permissions: ClassVar[list[str]] = []
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = True
    destructive: bool = False
    timeout_seconds: float = 2.0

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=True, message="OK")


class DestructiveTool:
    name: str = "destructive_tool"
    description: str = "Simulates an irreversible tool"
    schema: ClassVar[dict[str, Any]] = {
        "properties": {"confirm": {"type": "bool", "required": False}}
    }
    permissions: ClassVar[list[str]] = []
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = False
    destructive: bool = True
    timeout_seconds: float = 2.0

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=True, message="DONE")


def test_tool_executor_timeout_returns_promptly() -> None:
    slow = SlowTool()
    registry = ToolRegistry([slow])
    executor = ToolExecutor(registry=registry)

    start = time.monotonic()
    result = executor.execute("slow_tool", context=ToolContext(timeout_seconds=0.05))
    elapsed = time.monotonic() - start

    assert result.success is False
    assert result.status_code == "TIMEOUT"
    # Must not block until the hung tool finishes (0.2s sleep).
    assert elapsed < 0.15


def test_tool_executor_network_unavailable_denies_network_tool() -> None:
    registry = ToolRegistry([NetworkTool()])
    executor = ToolExecutor(registry=registry)

    result = executor.execute(
        "net_tool",
        context=ToolContext(mode=SocialMode.HOME, network_access_allowed=False),
    )
    assert result.success is False
    assert result.status_code == "NETWORK_UNAVAILABLE"
    assert result.error_code == ErrorCode.TOOL_UNAVAILABLE


def test_tool_executor_allows_network_tool_when_online() -> None:
    registry = ToolRegistry([NetworkTool()])
    executor = ToolExecutor(registry=registry)

    result = executor.execute(
        "net_tool",
        context=ToolContext(mode=SocialMode.HOME, network_access_allowed=True),
    )
    assert result.success is True


def test_tool_executor_destructive_requires_confirmation() -> None:
    registry = ToolRegistry([DestructiveTool()])
    executor = ToolExecutor(registry=registry)

    denied = executor.execute("destructive_tool", args={}, context=ToolContext(mode=SocialMode.WORKSHOP))
    assert denied.success is False
    assert denied.status_code == "CONFIRMATION_REQUIRED"
    assert denied.error_code == ErrorCode.TOOL_DENIED

    confirmed = executor.execute(
        "destructive_tool",
        args={"confirm": True},
        context=ToolContext(mode=SocialMode.WORKSHOP),
    )
    assert confirmed.success is False
    assert confirmed.status_code == "DESTRUCTIVE_EXECUTION_UNSUPPORTED"
    assert confirmed.error_code == ErrorCode.TOOL_DENIED


def test_tool_executor_destructive_denied_in_public_mode() -> None:
    registry = ToolRegistry([DestructiveTool()])
    executor = ToolExecutor(registry=registry)

    result = executor.execute(
        "destructive_tool",
        args={"confirm": True},
        context=ToolContext(mode=SocialMode.PUBLIC),
    )
    assert result.success is False
    assert result.status_code == "DESTRUCTIVE_MODE_DENIED"
    assert result.error_code == ErrorCode.TOOL_DENIED


def test_tool_executor_redacts_secrets_nested_inside_lists() -> None:
    executor = ToolExecutor(registry=ToolRegistry())
    redacted = executor._redact_args({
        "items": [{"name": "ok", "api_token": "secret-value"}],
        "plain": "visible",
    })
    assert redacted["items"][0]["api_token"] == "[REDACTED]"
    assert redacted["items"][0]["name"] == "ok"
    assert redacted["plain"] == "visible"

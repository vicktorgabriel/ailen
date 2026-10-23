"""Unit tests for the ADR-014 autonomy contract.

Covers ``AutonomyLevel`` / ``autonomy_level_of`` (fail-closed tier resolution),
``ToolContext.max_autonomy`` enforcement in ``ToolExecutor`` (step 2b) and the
``AgentConfig.max_autonomy_level`` default.
"""

from typing import Any, ClassVar

import pytest

from ailen.core.config import AILENConfig
from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import (
    AutonomyLevel,
    ToolContext,
    ToolResult,
    autonomy_level_of,
)
from ailen.tools.executor import ToolExecutor
from ailen.tools.registry import ToolRegistry


class _BaseFakeTool:
    """Fake tool with permissive mode/privacy metadata so only autonomy can deny it."""

    name: str = "fake_tool"
    description: str = "Fake tool for autonomy tests"
    schema: ClassVar[dict[str, Any]] = {"properties": {}}
    permissions: ClassVar[list[str]] = []
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 2.0

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=True, tool_name=self.name, message="executed")


class UndeclaredAutonomyTool(_BaseFakeTool):
    """Tool that does not declare ``autonomy_level`` at all."""

    name: str = "undeclared_autonomy_tool"


class N2Tool(_BaseFakeTool):
    """Tool declaring autonomy tier N2."""

    name: str = "n2_tool"
    autonomy_level: AutonomyLevel = AutonomyLevel.N2


class InvalidAutonomyTool(_BaseFakeTool):
    """Tool declaring an out-of-contract autonomy tier."""

    name: str = "invalid_autonomy_tool"
    autonomy_level: int = 9


def test_undeclared_autonomy_level_is_n1_and_executes() -> None:
    tool = UndeclaredAutonomyTool()
    assert autonomy_level_of(tool) is AutonomyLevel.N1

    executor = ToolExecutor(registry=ToolRegistry([tool]))
    result = executor.execute(
        tool.name,
        context=ToolContext(mode=SocialMode.HOME, max_autonomy=AutonomyLevel.N1),
    )

    assert result.success is True
    assert result.status_code == "OK"


def test_n2_tool_denied_when_max_autonomy_is_n1() -> None:
    tool = N2Tool()
    executor = ToolExecutor(registry=ToolRegistry([tool]))

    result = executor.execute(
        tool.name,
        context=ToolContext(mode=SocialMode.HOME, max_autonomy=AutonomyLevel.N1),
    )

    assert result.success is False
    assert result.status_code == "AUTONOMY_DENIED"
    assert result.error_code == ErrorCode.TOOL_DENIED


def test_n2_tool_allowed_when_max_autonomy_is_n2() -> None:
    tool = N2Tool()
    executor = ToolExecutor(registry=ToolRegistry([tool]))

    result = executor.execute(
        tool.name,
        context=ToolContext(mode=SocialMode.HOME, max_autonomy=AutonomyLevel.N2),
    )

    assert result.success is True
    assert result.status_code == "OK"


def test_n2_tool_denied_in_shop_even_with_max_autonomy_n3() -> None:
    tool = N2Tool()
    executor = ToolExecutor(registry=ToolRegistry([tool]))

    result = executor.execute(
        tool.name,
        context=ToolContext(mode=SocialMode.SHOP, max_autonomy=AutonomyLevel.N3),
    )

    assert result.success is False
    assert result.status_code == "AUTONOMY_DENIED"
    assert result.error_code == ErrorCode.TOOL_DENIED


def test_n2_tool_denied_in_public_even_with_max_autonomy_n3() -> None:
    tool = N2Tool()
    executor = ToolExecutor(registry=ToolRegistry([tool]))

    result = executor.execute(
        tool.name,
        context=ToolContext(mode=SocialMode.PUBLIC, max_autonomy=AutonomyLevel.N3),
    )

    assert result.success is False
    assert result.status_code == "AUTONOMY_DENIED"
    assert result.error_code == ErrorCode.TOOL_DENIED


def test_invalid_autonomy_level_is_denied_even_with_n3_cap() -> None:
    tool = InvalidAutonomyTool()
    assert autonomy_level_of(tool) is None

    executor = ToolExecutor(registry=ToolRegistry([tool]))
    result = executor.execute(
        tool.name,
        context=ToolContext(mode=SocialMode.HOME, max_autonomy=AutonomyLevel.N3),
    )

    assert result.success is False
    assert result.status_code == "AUTONOMY_DENIED"
    assert result.error_code == ErrorCode.TOOL_DENIED


def test_default_agent_max_autonomy_level_is_n1() -> None:
    assert AILENConfig().agent.max_autonomy_level == 1


@pytest.mark.parametrize("invalid", [True, False, 4, "x", None, 1.0])
def test_invalid_declared_autonomy_never_executes(invalid: object) -> None:
    tool = UndeclaredAutonomyTool()
    tool.autonomy_level = invalid  # type: ignore[attr-defined]
    assert autonomy_level_of(tool) is None
    result = ToolExecutor(ToolRegistry([tool])).execute(
        tool.name, context=ToolContext(mode=SocialMode.HOME, max_autonomy=AutonomyLevel.N3),
    )
    assert not result.success and result.status_code == "AUTONOMY_DENIED"

"""Unit tests for ToolRegistry."""

import pytest

from ailen.tools.builtin.clock import ClockTool
from ailen.tools.builtin.music import MusicTool
from ailen.tools.builtin.timer import TimerTool
from ailen.tools.registry import ToolRegistry


def test_tool_registry_registration() -> None:
    registry = ToolRegistry()
    clock = ClockTool()
    timer = TimerTool()

    registry.register(clock)
    registry.register(timer)

    assert len(registry) == 2
    assert registry.has_tool("clock")
    assert registry.has_tool("timer")
    assert "clock" in registry
    assert registry.get("clock") is clock
    assert registry.get("timer") is timer
    assert registry.get("unknown") is None


def test_tool_registry_rejects_duplicates() -> None:
    registry = ToolRegistry()
    clock = ClockTool()
    registry.register(clock)

    with pytest.raises(ValueError, match="Herramienta ya registrada"):
        registry.register(clock)


def test_tool_registry_rejects_invalid_tool_name() -> None:
    registry = ToolRegistry()

    class BadTool:
        name = ""

    with pytest.raises(ValueError, match="nombre de la herramienta"):
        registry.register(BadTool())  # type: ignore[arg-type]


def test_tool_registry_unregister() -> None:
    music = MusicTool()
    registry = ToolRegistry([music])
    assert len(registry) == 1
    assert "music" in registry

    removed = registry.unregister("music")
    assert removed is music
    assert len(registry) == 0
    assert "music" not in registry

    # Unregistering non-existent returns None
    assert registry.unregister("music") is None


def test_tool_registry_list_tools_and_names() -> None:
    clock = ClockTool()
    timer = TimerTool()
    registry = ToolRegistry([clock, timer])

    tools = registry.list_tools()
    assert len(tools) == 2
    assert clock in tools
    assert timer in tools

    names = registry.list_names()
    assert set(names) == {"clock", "timer"}

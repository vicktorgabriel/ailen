"""Tests for declarative runtime capability discovery."""

from ailen.core.capabilities import CapabilityDescriptor, CapabilityRegistry
from ailen.tools.builtin import ClockTool, WebSearchTool
from ailen.tools.builtin.web_search import UnconfiguredWebSearchProvider
from ailen.tools.registry import ToolRegistry


class DynamicProvider:
    def __init__(self) -> None:
        self.ready = False

    def capabilities(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor(
                key="demo.dynamic",
                description="usar una capacidad dinámica de prueba",
                available=self.ready,
                source="test",
            )
        ]


def test_registry_discovers_tools_without_central_feature_list() -> None:
    tools = ToolRegistry([
        ClockTool(),
        WebSearchTool(provider=UnconfiguredWebSearchProvider()),
    ])
    registry = CapabilityRegistry(tools, network_access_allowed=True)
    keys = {item.key for item in registry.available()}
    assert "tool.clock" in keys
    assert "tool.web_search" not in keys


def test_registry_rechecks_dynamic_provider_availability() -> None:
    provider = DynamicProvider()
    registry = CapabilityRegistry()
    registry.register_provider(provider)
    assert registry.prompt_payload() == []

    provider.ready = True
    payload = registry.prompt_payload()
    assert payload == [
        {
            "key": "demo.dynamic",
            "description": "usar una capacidad dinámica de prueba",
        }
    ]

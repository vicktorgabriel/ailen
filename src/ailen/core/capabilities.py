"""Declarative runtime capability discovery for AILEN Core.

Capabilities are derived from registered tools and runtime providers. Conversation
code never maintains a second hardcoded feature list.
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityDescriptor:
    """One capability as exposed to the conversational model."""

    key: str
    description: str
    available: bool = True
    source: str = "runtime"




class ToolRegistryView(Protocol):
    """Minimal tool-registry surface required for capability discovery."""

    def list_tools(self) -> list[Any]:
        ...


@runtime_checkable
class CapabilityProvider(Protocol):
    """Runtime component that can describe its currently available capabilities."""

    def capabilities(self) -> list[CapabilityDescriptor]:
        ...


class CapabilityRegistry:
    """Collect capabilities dynamically from tools and runtime components."""

    def __init__(
        self,
        tool_registry: ToolRegistryView | None = None,
        *,
        network_access_allowed: bool = False,
    ) -> None:
        self.tool_registry = tool_registry
        self.network_access_allowed = network_access_allowed
        self._providers: list[CapabilityProvider] = []
        self._static: dict[str, CapabilityDescriptor] = {}

    def register(self, descriptor: CapabilityDescriptor) -> None:
        self._static[descriptor.key] = descriptor

    def register_provider(self, provider: CapabilityProvider) -> None:
        if provider not in self._providers:
            self._providers.append(provider)

    @staticmethod
    def _tool_available(tool: Any, *, network_access_allowed: bool) -> bool:
        if getattr(tool, "requires_network", False) and not network_access_allowed:
            return False
        available = getattr(tool, "is_available", None)
        if isinstance(available, bool):
            return available
        return True

    def snapshot(self) -> list[CapabilityDescriptor]:
        """Return a fresh capability snapshot; availability is evaluated now."""
        items: dict[str, CapabilityDescriptor] = dict(self._static)
        if self.tool_registry is not None:
            for tool in self.tool_registry.list_tools():
                key = f"tool.{tool.name}"
                items[key] = CapabilityDescriptor(
                    key=key,
                    description=str(tool.description).strip(),
                    available=self._tool_available(
                        tool,
                        network_access_allowed=self.network_access_allowed,
                    ),
                    source="tool",
                )

        for provider in self._providers:
            try:
                descriptors = provider.capabilities()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Capability provider unavailable: %s", exc)
                continue
            for descriptor in descriptors:
                items[descriptor.key] = descriptor
        return list(items.values())

    def available(self) -> list[CapabilityDescriptor]:
        return [item for item in self.snapshot() if item.available]

    def prompt_payload(self) -> list[dict[str, str]]:
        """Compact JSON-safe payload containing only currently executable abilities."""
        return [
            {"key": item.key, "description": item.description}
            for item in self.available()
        ]

"""Tool registry for AILEN.

Maintains an explicit, strictly allowlisted collection of tools.
Arbitrary dynamic importing of modules is prohibited.
"""

import logging

from ailen.tools.contracts import Tool

logger = logging.getLogger("ailen.tools.registry")


class ToolRegistry:
    """Explicit allowlist registry for AILEN Core tools."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        """Register a tool. Tool names must be non-empty and unique."""
        if not tool.name or not isinstance(tool.name, str):
            raise ValueError("El nombre de la herramienta debe ser una cadena no vacía.")
        if tool.name in self._tools:
            raise ValueError(f"Herramienta ya registrada con el nombre: {tool.name}")
        self._tools[tool.name] = tool
        logger.debug("Registered tool '%s' (modes=%s)", tool.name, getattr(tool, "allowed_modes", "all"))

    def unregister(self, name: str) -> Tool | None:
        """Unregister and return a tool if present."""
        return self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a registered tool by name."""
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """Return list of registered tool names."""
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

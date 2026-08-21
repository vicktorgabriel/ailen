"""Fake backend registry.

Punto único de cableado de backends simulados para desarrollo y tests.
Cuando existan backends reales se registran acá detrás de la misma fachada;
el Core y la Web no cambian.
"""

from dataclasses import dataclass, field
from typing import Any

from ailen.ai import FakeAiBackend
from ailen.audio import FakeSttBackend, FakeTtsBackend
from ailen.face import NullFaceController
from ailen.tools import build_fake_tools
from ailen.vision import FakeVisionBackend


@dataclass
class FakeBackends:
    """Contenedor de backends simulados del nodo."""
    ai: FakeAiBackend = field(default_factory=FakeAiBackend)
    stt: FakeSttBackend = field(default_factory=FakeSttBackend)
    tts: FakeTtsBackend = field(default_factory=FakeTtsBackend)
    vision: FakeVisionBackend = field(default_factory=FakeVisionBackend)
    face: NullFaceController = field(default_factory=NullFaceController)
    tools: list[Any] = field(default_factory=build_fake_tools)

    def tool_map(self) -> dict[str, Any]:
        """Return tools indexed by name."""
        return {tool.name: tool for tool in self.tools}


def build_fake_backends() -> FakeBackends:
    """Build the full fake backend set for dev/tests."""
    return FakeBackends()

"""Face contracts. Ver MODULE_CONTRACTS.md sección 14.

Face no accede a SQLite, AI ni web. Sólo recibe estados, mirada y niveles.
"""

import re
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from ailen.domain.enums import AssistantState

FACE_EXPRESSIONS: tuple[str, ...] = (
    "neutral",
    "happy",
    "curious",
    "surprised",
    "confused",
    "wink",
    "focused",
    "sad",
    "skeptical",
    "excited",
    "playful",
)

# Autonomous conversational affect excludes deliberate social gestures such as wink.
CONVERSATIONAL_EXPRESSIONS: tuple[str, ...] = tuple(
    expression for expression in FACE_EXPRESSIONS if expression != "wink"
)
_EXPRESSION_ID = re.compile(r"[a-z][a-z0-9_]{0,63}")


def bounded_expression_ids(values: Iterable[str]) -> tuple[str, ...]:
    """Return unique canonical ids safe for Core schemas and model metadata."""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip().lower()
        if clean in seen or _EXPRESSION_ID.fullmatch(clean) is None:
            continue
        seen.add(clean)
        result.append(clean)
    return tuple(result[:64])


@runtime_checkable
class FaceController(Protocol):
    """Contract for the expressive face renderer."""

    @property
    def available_expressions(self) -> tuple[str, ...]:
        """Return the renderer's trusted, bounded expression allowlist."""
        ...

    @property
    def conversational_expressions(self) -> tuple[str, ...]:
        """Return only visible expressions approved for spontaneous affect."""
        ...

    def set_state(self, state: AssistantState) -> None:
        """Apply an assistant interaction state."""
        ...

    def set_gaze(self, x: float, y: float) -> None:
        """Orient gaze toward normalized coordinates (-1.0..1.0)."""
        ...

    def set_speech_level(self, level: float) -> None:
        """Set mouth/energy level (0.0..1.0) while speaking."""
        ...

    def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
        """Apply a bounded expression; 0 seconds means renderer-native timing."""
        ...

    def sleep(self) -> None:
        """Enter low-power sleep face."""
        ...

    def wake(self) -> None:
        """Wake from sleep face."""
        ...

    def is_display_active(self) -> bool:
        """Return whether this controller currently owns a visible display."""
        ...

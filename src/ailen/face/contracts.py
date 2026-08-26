"""Face contracts. Ver MODULE_CONTRACTS.md sección 14.

Face no accede a SQLite, AI ni web. Sólo recibe estados, mirada y niveles.
"""

from typing import Protocol, runtime_checkable

from ailen.domain.enums import AssistantState


@runtime_checkable
class FaceController(Protocol):
    """Contract for the expressive face renderer."""

    def set_state(self, state: AssistantState) -> None:
        """Apply an assistant interaction state."""
        ...

    def set_gaze(self, x: float, y: float) -> None:
        """Orient gaze toward normalized coordinates (-1.0..1.0)."""
        ...

    def set_speech_level(self, level: float) -> None:
        """Set mouth/energy level (0.0..1.0) while speaking."""
        ...

    def set_expression(self, expression: str, duration_seconds: float = 5.0) -> None:
        """Apply a bounded transient named expression."""
        ...

    def sleep(self) -> None:
        """Enter low-power sleep face."""
        ...

    def wake(self) -> None:
        """Wake from sleep face."""
        ...

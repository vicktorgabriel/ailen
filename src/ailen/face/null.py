"""Null face controller. Headless/dev placeholder sin gráficos reales."""

import logging

from ailen.core.capabilities import CapabilityDescriptor
from ailen.domain.enums import AssistantState
from ailen.face.animator import FaceAnimator
from ailen.face.models import FacePose

logger = logging.getLogger("ailen.face.null")


class NullFaceController:
    """Face sin salida gráfica.

    Registra intenciones en debug, ejecuta la lógica de FaceAnimator y mantiene
    último estado; permite correr el sistema en modo headless sin backend gráfico.
    """

    def __init__(self, animator: FaceAnimator | None = None) -> None:
        self.animator = animator or FaceAnimator()
        self.state: AssistantState = AssistantState.BOOTING
        self.gaze: tuple[float, float] = (0.0, 0.0)
        self.speech_level: float = 0.0
        self.expression: str = "neutral"
        self.sleeping: bool = False

    def capabilities(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor("face.display", "mostrar una cara animada", False, "face"),
            CapabilityDescriptor("face.expression", "cambiar expresiones faciales", False, "face"),
        ]

    def set_state(self, state: AssistantState) -> None:
        self.state = state
        self.animator.set_state(state)
        logger.debug("face state -> %s", state.value)

    def set_gaze(self, x: float, y: float) -> None:
        self.gaze = (max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)))
        self.animator.set_gaze(x, y)

    def set_speech_level(self, level: float) -> None:
        self.speech_level = max(0.0, min(1.0, level))
        self.animator.set_speech_level(level)

    def set_expression(self, expression: str, duration_seconds: float = 5.0) -> None:
        self.expression = expression
        self.animator.set_expression(expression, duration_seconds)

    def sleep(self) -> None:
        self.sleeping = True
        self.animator.sleep()
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        self.sleeping = False
        self.state = AssistantState.IDLE
        self.animator.wake()
        logger.debug("face wake -> IDLE/waking")

    def get_current_pose(self, current_time: float | None = None) -> FacePose:
        """Return the calculated normalized FacePose."""
        return self.animator.step(current_time)

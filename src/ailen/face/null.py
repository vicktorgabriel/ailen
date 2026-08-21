"""Null face controller. Headless/dev placeholder sin gráficos reales."""

import logging

from ailen.domain.enums import AssistantState

logger = logging.getLogger("ailen.face.null")


class NullFaceController:
    """Face sin salida gráfica.

    Registra intenciones en debug y mantiene último estado; permite correr
    el sistema en modo headless sin backend gráfico (ADR-006 pendiente).
    """

    def __init__(self) -> None:
        self.state: AssistantState = AssistantState.BOOTING
        self.gaze: tuple[float, float] = (0.0, 0.0)
        self.speech_level: float = 0.0
        self.expression: str = "neutral"
        self.sleeping: bool = False

    def set_state(self, state: AssistantState) -> None:
        self.state = state
        logger.debug("face state -> %s", state.value)

    def set_gaze(self, x: float, y: float) -> None:
        self.gaze = (max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)))

    def set_speech_level(self, level: float) -> None:
        self.speech_level = max(0.0, min(1.0, level))

    def set_expression(self, expression: str) -> None:
        self.expression = expression

    def sleep(self) -> None:
        self.sleeping = True
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        self.sleeping = False
        self.set_state(AssistantState.IDLE)

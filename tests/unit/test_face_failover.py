"""Runtime face failover and renderer-native timing regressions."""

from __future__ import annotations

from unittest.mock import MagicMock

from ailen.ai.context import AiContextBuilder
from ailen.ai.fake import FakeAiBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.router import RuleBasedRouter
from ailen.core.conversation import ConversationCoordinator
from ailen.domain.enums import AssistantState
from ailen.face.failover import FailoverFaceController
from ailen.face.native_engine import NativeFaceEngineError, NativeFaceResult
from ailen.face.null import NullFaceController


class _FakeFace:
    def __init__(self, *, expressions: tuple[str, ...] = ("neutral", "happy")) -> None:
        self._expressions = expressions
        self.started = False
        self.closed = False
        self.state = AssistantState.IDLE
        self.gaze = (0.0, 0.0)
        self.speech = 0.0
        self.expression = ("neutral", 0.0)
        self.update_error: NativeFaceEngineError | None = None

    @property
    def available_expressions(self) -> tuple[str, ...]:
        return self._expressions

    @property
    def conversational_expressions(self) -> tuple[str, ...]:
        return tuple(
            expression
            for expression in self._expressions
            if expression not in {"neutral", "laugh_hard"}
        )

    def start_window(self, interactive_keys: bool = False) -> None:
        del interactive_keys
        self.started = True

    def is_display_active(self) -> bool:
        return self.started and not self.closed

    def set_state(self, state: AssistantState) -> None:
        self.state = state

    def set_gaze(self, x: float, y: float) -> None:
        self.gaze = (x, y)

    def set_speech_level(self, level: float) -> None:
        self.speech = level

    def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
        self.expression = (expression, duration_seconds)

    def sleep(self) -> None:
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        self.set_state(AssistantState.IDLE)

    def update(self) -> None:
        if self.update_error is not None:
            error = self.update_error
            self.update_error = None
            raise error

    def capabilities(self):  # type: ignore[no-untyped-def]
        return []

    def describe_capabilities(self):  # type: ignore[no-untyped-def]
        return []

    def close(self) -> None:
        self.closed = True


def test_fatal_native_update_switches_same_controller_to_safe_fallback() -> None:
    primary = _FakeFace(expressions=("neutral", "happy", "laugh_hard"))
    fallback = _FakeFace(expressions=("neutral", "happy"))
    controller = FailoverFaceController(primary, fallback)

    controller.start_window()
    controller.set_state(AssistantState.LISTENING)
    controller.set_gaze(0.4, -0.2)
    controller.set_speech_level(0.7)
    controller.set_expression("happy", 0.0)

    primary.update_error = NativeFaceEngineError(
        "JPEG decode failed",
        NativeFaceResult.DECODE_ERROR,
    )
    controller.update()

    assert controller.using_fallback is True
    assert primary.closed is True
    assert fallback.started is True
    assert fallback.state == AssistantState.LISTENING
    assert fallback.gaze == (0.4, -0.2)
    assert fallback.speech == 0.7
    assert fallback.expression == ("happy", 0.0)
    assert controller.available_expressions == ("neutral", "happy")


def test_nonfatal_native_error_does_not_hide_invalid_expression() -> None:
    class _MissingExpressionFace(_FakeFace):
        def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
            raise NativeFaceEngineError(
                f"unknown expression: {expression}",
                NativeFaceResult.NOT_FOUND,
            )

    primary = _MissingExpressionFace()
    fallback = _FakeFace()
    controller = FailoverFaceController(primary, fallback)

    try:
        controller.set_expression("missing")
    except NativeFaceEngineError as exc:
        assert exc.result == NativeFaceResult.NOT_FOUND
    else:
        raise AssertionError("non-fatal native error must remain visible")

    assert controller.using_fallback is False
    assert fallback.started is False


def test_native_failure_to_null_removes_conversational_face_capability() -> None:
    primary = _FakeFace(expressions=("neutral", "happy", "laugh_hard"))
    controller = FailoverFaceController(primary, NullFaceController())
    backend = FakeAiBackend(canned_response="Respuesta headless.")
    backend.generate = MagicMock(side_effect=backend.generate)
    audio = MagicMock()
    audio.last_speech_interrupted = False
    coordinator = ConversationCoordinator(
        context_builder=AiContextBuilder(),
        router=RuleBasedRouter(),
        orchestrator=AiOrchestrator(backends={"local": backend}),
        audio_coordinator=audio,
        face_controller=controller,
    )
    controller.start_window()
    assert coordinator.conversational_expressions == ("happy",)

    primary.update_error = NativeFaceEngineError(
        "decode failed",
        NativeFaceResult.DECODE_ERROR,
    )
    controller.update()

    assert controller.using_fallback is True
    assert controller.is_display_active() is False
    assert controller.available_expressions == ()
    assert controller.conversational_expressions == ()
    assert coordinator.conversational_expressions == ()
    assert all(not capability.available for capability in controller.capabilities())

    coordinator.handle_user_input("Decime algo breve")
    request = backend.generate.call_args.args[0]
    assert "[[face:expresion]]" not in request.system_context
    assert "Permitidas:" not in request.system_context

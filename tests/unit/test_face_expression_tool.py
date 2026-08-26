"""Tests for the face-expression capability and controlled tool."""

from ailen.core.capabilities import CapabilityDescriptor
from ailen.domain.enums import AssistantState
from ailen.face.animator import FaceAnimator
from ailen.tools.builtin.face_expression import FaceExpressionTool
from ailen.tools.contracts import ToolContext


class FaceStub:
    def __init__(self) -> None:
        self.expression = "neutral"
        self.duration_seconds = 0.0
        self.ready = True

    def capabilities(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor(
                "face.expression",
                "cambiar expresiones faciales",
                self.ready,
                "face",
            )
        ]

    def set_expression(self, expression: str, duration_seconds: float = 5.0) -> None:
        self.expression = expression
        self.duration_seconds = duration_seconds

    def set_state(self, state: AssistantState) -> None:
        del state

    def set_gaze(self, x: float, y: float) -> None:
        del x, y

    def set_speech_level(self, level: float) -> None:
        del level

    def close(self) -> None:
        pass


def test_face_expression_tool_changes_real_controller_state() -> None:
    face = FaceStub()
    tool = FaceExpressionTool(face)
    assert tool.is_available is True

    result = tool.execute({"expression": "happy"}, ToolContext())

    assert result.success is True
    assert face.expression == "happy"
    assert face.duration_seconds == 5.0
    assert result.data["expression"] == "happy"


def test_face_expression_tool_supports_every_bounded_expression() -> None:
    face = FaceStub()
    tool = FaceExpressionTool(face)

    for expression in FaceAnimator.SUPPORTED_EXPRESSIONS:
        result = tool.execute({"expression": expression}, ToolContext())

        assert result.success is True
        assert result.data["expression"] == expression
        assert face.expression == expression


def test_face_expression_tool_fails_closed_when_display_is_unavailable() -> None:
    face = FaceStub()
    face.ready = False
    tool = FaceExpressionTool(face)

    result = tool.execute({"expression": "wink"}, ToolContext())

    assert result.success is False
    assert result.status_code == "UNAVAILABLE"
    assert face.expression == "neutral"

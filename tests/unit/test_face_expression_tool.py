"""Tests for the face-expression capability and controlled tool."""

from ailen.core.capabilities import CapabilityDescriptor
from ailen.domain.enums import AssistantState
from ailen.face.animator import FaceAnimator
from ailen.face.contracts import FACE_EXPRESSIONS
from ailen.face.null import NullFaceController
from ailen.tools.builtin.face_expression import FaceExpressionTool
from ailen.tools.contracts import ToolContext


class FaceStub:
    def __init__(self) -> None:
        self.expression = "neutral"
        self.duration_seconds = 0.0
        self.ready = True
        self._available_expressions = FACE_EXPRESSIONS

    @property
    def available_expressions(self) -> tuple[str, ...]:
        return self._available_expressions

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
    assert face.duration_seconds == 0.0
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


def test_face_expression_tool_uses_active_renderer_allowlist() -> None:
    face = FaceStub()
    face._available_expressions = ("neutral", "embarrassed")
    tool = FaceExpressionTool(face)

    assert tool.schema["properties"]["expression"]["enum"] == ["neutral", "embarrassed"]
    result = tool.execute({"expression": "embarrassed"}, ToolContext())
    rejected = tool.execute({"expression": "happy"}, ToolContext())

    assert result.success is True
    assert face.expression == "embarrassed"
    assert rejected.success is False
    assert rejected.status_code == "TOOL_ARGS_INVALID"


def test_face_expression_tool_headless_schema_is_empty_and_unavailable() -> None:
    tool = FaceExpressionTool(NullFaceController())

    assert tool.allowed_expressions == ()
    assert tool.schema["properties"]["expression"]["enum"] == []
    result = tool.execute({"expression": "happy"}, ToolContext())
    assert result.success is False
    assert result.status_code == "UNAVAILABLE"

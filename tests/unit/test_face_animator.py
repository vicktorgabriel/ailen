"""Unit tests for FaceAnimator and normalized FacePose generation."""

import random
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ailen.domain.enums import AssistantState
from ailen.face.animator import FaceAnimator
from ailen.face.gui import TkinterFaceController
from ailen.face.models import FacePose
from ailen.face.null import NullFaceController


class ControlledClock:
    """Deterministic controllable clock for face animator tests."""

    def __init__(self, start_time: float = 100.0) -> None:
        self.time = start_time

    def __call__(self) -> float:
        return self.time

    def advance(self, dt: float) -> None:
        self.time += dt


def test_face_animator_default_idle_pose() -> None:
    clock = ControlledClock(100.0)
    rng = random.Random(42)
    animator = FaceAnimator(clock=clock, rng=rng)

    pose = animator.step()
    assert isinstance(pose, FacePose)
    assert pose.expression == "neutral"
    assert pose.left_eye_open > 0.7
    assert pose.right_eye_open > 0.7
    assert pose.mouth_open == 0.0
    assert abs(pose.gaze_x) < 0.1
    assert abs(pose.gaze_y) < 0.1


def test_face_animator_state_mappings() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock)

    # ATTENTION: wide attentive eyes
    animator.set_state(AssistantState.ATTENTION)
    pose = animator.step()
    assert pose.expression == "attentive"
    assert pose.pupil_size >= 0.55

    # LISTENING: listening expression, head tilt
    animator.set_state(AssistantState.LISTENING)
    pose = animator.step()
    assert pose.expression == "listening"
    assert pose.head_tilt != 0.0

    # PROCESSING: thinking expression
    animator.set_state(AssistantState.PROCESSING)
    pose = animator.step()
    assert pose.expression == "thinking"

    # SLEEP: eyes completely closed
    animator.set_state(AssistantState.SLEEP)
    pose = animator.step()
    assert pose.expression == "sleep"
    assert pose.left_eye_open == 0.0
    assert pose.right_eye_open == 0.0

    # ERROR: error expression
    animator.set_state(AssistantState.ERROR)
    pose = animator.step()
    assert pose.expression == "error"

    # DEGRADED: degraded expression
    animator.set_state(AssistantState.DEGRADED)
    pose = animator.step()
    assert pose.expression == "degraded"

    # SPEAKING and TOOL have explicit visual mappings too.
    animator.set_state(AssistantState.SPEAKING)
    assert animator.step().expression == "speaking"
    animator.set_state(AssistantState.TOOL)
    assert animator.step().expression == "working"

    # Returning to IDLE must clear stale expressions from prior states.
    animator.set_state(AssistantState.IDLE)
    assert animator.step().expression == "neutral"


def test_face_animator_gaze_smoothing_and_clamping() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock, gaze_smoothing_speed=5.0)

    # Set extreme target gaze outside bounds (should be clamped to [-1.0, 1.0])
    animator.set_gaze(2.5, -3.0)

    # Step immediately (dt=0): target set, current interpolation starts
    pose1 = animator.step()
    assert pose1.gaze_x <= 1.0
    assert pose1.gaze_y >= -1.0

    # Advance time: gaze moves towards target smoothly
    clock.advance(0.5)
    pose2 = animator.step()
    assert pose2.gaze_x > pose1.gaze_x
    assert pose2.gaze_y < pose1.gaze_y


def test_face_animator_speech_mouth_opening() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock)

    animator.set_state(AssistantState.SPEAKING)
    animator.set_speech_level(0.75)

    pose = animator.step()
    assert animator.speech_level == 0.75
    assert 0.1 < pose.mouth_open < 0.8

    animator.set_speech_level(0.0)
    pose_closed = animator.step()
    assert pose_closed.mouth_open == 0.0


def test_face_animator_articulates_continuously_from_bounded_chunk_energy() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock)
    animator.set_state(AssistantState.SPEAKING)
    animator.set_speech_level(0.4)

    poses = []
    for _ in range(8):
        poses.append(animator.step())
        clock.advance(0.04)

    mouth_positions = {round(pose.mouth_open, 3) for pose in poses}
    head_positions = {round(pose.head_tilt, 3) for pose in poses}
    assert len(mouth_positions) >= 5
    # Fixed speech energy now carries only subtle articulation; the larger
    # mouth dynamics come from the real PCM envelope fed by AudioCoordinator.
    assert 0.03 < max(mouth_positions) - min(mouth_positions) < 0.15
    assert len(head_positions) >= 5


def test_transient_expression_keeps_articulating_while_speaking() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock)
    animator.set_expression("happy")
    animator.set_state(AssistantState.SPEAKING)
    animator.set_speech_level(0.5)

    first = animator.step()
    clock.advance(0.09)
    second = animator.step()

    assert first.expression == second.expression == "happy"
    assert first.mouth_open != second.mouth_open


def test_face_animator_blinking_cycle() -> None:
    clock = ControlledClock(100.0)
    rng = random.Random(123)
    animator = FaceAnimator(clock=clock, rng=rng)

    # Initial state: eyes open
    pose_open = animator.step()
    assert pose_open.left_eye_open > 0.8
    assert pose_open.blink_progress == 0.0

    # Advance time to trigger scheduled blink
    interval = animator._next_blink_interval
    clock.advance(interval + 0.09)  # Peak of blink (halfway through 0.18s)

    pose_blink = animator.step()
    assert pose_blink.blink_progress > 0.8
    assert pose_blink.left_eye_open < 0.3

    # Advance past blink duration: eyes fully reopen
    clock.advance(0.15)
    pose_reopened = animator.step()
    assert pose_reopened.left_eye_open > 0.8
    assert pose_reopened.blink_progress == 0.0


def test_face_animator_sleep_and_wake() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock)

    animator.sleep()
    pose_sleep = animator.step()
    assert pose_sleep.left_eye_open == 0.0
    assert pose_sleep.expression == "sleep"

    animator.wake()
    pose_wake = animator.step()
    assert pose_wake.left_eye_open > 0.0
    assert pose_wake.expression == "waking"


def test_null_face_controller_wake_preserves_waking_expression() -> None:
    clock = ControlledClock(100.0)
    controller = NullFaceController(animator=FaceAnimator(clock=clock))
    controller.sleep()
    controller.wake()
    assert controller.state == AssistantState.IDLE
    assert controller.get_current_pose().expression == "waking"


def test_null_face_controller_with_animator() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock)
    controller = NullFaceController(animator=animator)

    controller.set_state(AssistantState.ATTENTION)
    controller.set_gaze(0.5, -0.5)
    controller.set_speech_level(0.8)

    pose = controller.get_current_pose()
    assert pose.expression == "attentive"
    assert controller.state == AssistantState.ATTENTION
    assert controller.speech_level == 0.8

def test_tkinter_face_controller_accepts_pixel_style_without_opening_window() -> None:
    controller = TkinterFaceController(style="pixel", width=640, height=360, fullscreen=False)
    assert controller.style == "pixel"
    with pytest.raises(ValueError, match="unknown face renderer style"):
        TkinterFaceController(style="unknown")


def test_portrait_renderer_assets_are_packaged() -> None:
    asset_dir = TkinterFaceController._portrait_asset_dir()
    required = {
        "ailen_portrait_base.png",
        "eyes_left.png",
        "eyes_right.png",
        "eyes_up.png",
        "eyes_down.png",
        "eyes_blink.png",
        "eyes_blink_left.png",
        "eyes_blink_right.png",
        "mouth_small.png",
        "mouth_open.png",
    }
    assert required <= {path.name for path in asset_dir.glob("*.png")}


def test_portrait_asset_failure_never_selects_pixel_implicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = TkinterFaceController(style="portrait")
    fake_tk = MagicMock()
    fake_tk.TclError = RuntimeError
    monkeypatch.setattr(controller, "_portrait_asset_dir", lambda: tmp_path)

    with pytest.raises(RuntimeError, match="portrait renderer assets are unavailable"):
        controller._load_portrait_assets(fake_tk)

    assert controller.style == "portrait"


def test_portrait_renderer_composes_base_gaze_and_speech_patches() -> None:
    controller = TkinterFaceController(style="portrait", width=800, height=480)
    canvas = MagicMock()
    controller._canvas = canvas
    base = MagicMock()
    base.width.return_value = 800
    base.height.return_value = 480
    controller._portrait_assets = {
        "base": base,
        "eyes_left": MagicMock(),
        "eyes_right": MagicMock(),
        "eyes_up": MagicMock(),
        "eyes_down": MagicMock(),
        "eyes_blink": MagicMock(),
        "eyes_blink_left": MagicMock(),
        "eyes_blink_right": MagicMock(),
        "mouth_small": MagicMock(),
        "mouth_open": MagicMock(),
    }

    controller._draw_portrait_face(
        FacePose(gaze_x=0.8, mouth_open=0.7, left_eye_open=1.0, right_eye_open=1.0),
        800,
        480,
    )

    assert canvas.create_image.call_count == 3


def test_pixel_renderer_uses_finer_grid_at_asrock_resolution() -> None:
    assert TkinterFaceController._pixel_block_size(480) == 4
    assert TkinterFaceController._pixel_block_size(240) == 2


def test_pixel_renderer_reports_requested_and_rendered_expression(caplog) -> None:
    clock = ControlledClock(100.0)
    controller = TkinterFaceController(
        style="pixel",
        width=640,
        height=360,
        animator=FaceAnimator(clock=clock),
    )
    canvas = MagicMock()
    canvas.winfo_width.return_value = 640
    canvas.winfo_height.return_value = 360
    controller._canvas = canvas

    with caplog.at_level("INFO", logger="ailen.face.gui"):
        controller.set_expression("happy", duration_seconds=2.0)
        controller._render_frame()

    assert controller._last_rendered_expression == "happy"
    assert "stage=requested expression=happy" in caplog.text
    assert "stage=rendered expression=happy" in caplog.text
    assert canvas.create_rectangle.called


def test_pixel_renderer_gives_every_allowed_expression_distinct_geometry() -> None:
    render_calls: dict[str, tuple[str, ...]] = {}

    for expression in FaceAnimator.SUPPORTED_EXPRESSIONS:
        clock = ControlledClock(100.0)
        controller = TkinterFaceController(
            style="pixel",
            width=800,
            height=480,
            animator=FaceAnimator(clock=clock),
        )
        canvas = MagicMock()
        canvas.winfo_width.return_value = 800
        canvas.winfo_height.return_value = 480
        controller._canvas = canvas
        controller.set_expression(expression, duration_seconds=2.0)

        controller._render_frame()

        render_calls[expression] = tuple(str(call) for call in canvas.method_calls)

    assert len(set(render_calls.values())) == len(FaceAnimator.SUPPORTED_EXPRESSIONS)


def test_pixel_renderer_mouth_changes_under_same_expression() -> None:
    controller = TkinterFaceController(style="pixel", width=800, height=480)
    canvas = MagicMock()
    controller._canvas = canvas

    controller._draw_pixel_face(
        pose=FacePose(expression="happy", mouth_open=0.18, mouth_width=0.8),
        width=800,
        height=480,
        eye_color="#38bdf8",
        highlight_color="#bae6fd",
        shadow_color="#0ea5e9",
        pupil_color="#075985",
        mouth_color="#38bdf8",
    )
    low_open_calls = tuple(str(call) for call in canvas.method_calls)
    canvas.reset_mock()

    controller._draw_pixel_face(
        pose=FacePose(expression="happy", mouth_open=0.78, mouth_width=0.8),
        width=800,
        height=480,
        eye_color="#38bdf8",
        highlight_color="#bae6fd",
        shadow_color="#0ea5e9",
        pupil_color="#075985",
        mouth_color="#38bdf8",
    )
    high_open_calls = tuple(str(call) for call in canvas.method_calls)

    assert low_open_calls != high_open_calls
    assert any("#bae6fd" in call for call in high_open_calls)
    assert any("#0ea5e9" in call for call in high_open_calls)

def test_face_animator_user_expressions_change_geometry() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock)

    animator.set_expression("happy")
    happy = animator.step()
    assert happy.expression == "happy"
    assert happy.mouth_width > 0.7

    animator.set_expression("surprised")
    surprised = animator.step()
    assert surprised.mouth_open > 0.2
    assert surprised.left_eye_open > happy.left_eye_open

    animator.set_expression("wink")
    wink = animator.step()
    assert wink.left_eye_open < 0.1
    assert wink.right_eye_open > 0.8


def test_face_animator_rejects_unbounded_expression_names() -> None:
    animator = FaceAnimator()
    try:
        animator.set_expression("ready")
    except ValueError as exc:
        assert "unsupported face expression" in str(exc)
    else:
        raise AssertionError("unbounded expression name was accepted")


def test_transient_expression_survives_speaking_state_then_expires() -> None:
    clock = ControlledClock(100.0)
    animator = FaceAnimator(clock=clock)
    animator.set_expression("happy", duration_seconds=2.0)

    animator.set_state(AssistantState.SPEAKING)
    assert animator.step().expression == "happy"

    clock.advance(2.1)
    assert animator.step().expression == "speaking"


def test_face_speech_gesture_energy_depends_on_emotion() -> None:
    def head_span(expression: str) -> float:
        clock = ControlledClock(100.0)
        animator = FaceAnimator(clock=clock, rng=random.Random(7))
        animator.set_expression(expression)
        animator.set_state(AssistantState.SPEAKING)
        animator.set_speech_level(0.55)
        values: list[float] = []
        for _ in range(28):
            values.append(animator.step().head_tilt)
            clock.advance(0.04)
        return max(values) - min(values)

    excited_span = head_span("excited")
    playful_span = head_span("playful")
    sad_span = head_span("sad")
    focused_span = head_span("focused")

    assert excited_span > sad_span * 1.8
    assert playful_span > focused_span * 1.5

"""Unit tests for FaceAnimator and normalized FacePose generation."""

import random

from ailen.domain.enums import AssistantState
from ailen.face.animator import FaceAnimator
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
    assert pose.mouth_open == 0.75

    animator.set_speech_level(0.0)
    pose_closed = animator.step()
    assert pose_closed.mouth_open == 0.0


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

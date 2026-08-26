"""Unit tests for Face, Vision Debouncer, and Coordinator integration."""

from ailen.core.coordinator import InteractionCoordinator
from ailen.core.events import EventBus
from ailen.core.social import SocialEngine
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState, SocialMode
from ailen.face.animator import FaceAnimator
from ailen.face.null import NullFaceController
from ailen.vision.debouncer import VisionDebouncer
from ailen.vision.fake import FakeVisionBackend
from ailen.vision.opencv_backend import OpenCvVisionBackend


class IntegratedClock:
    """Controllable clock for integrated pipeline testing."""

    def __init__(self, start: float = 1000.0) -> None:
        self.time = start

    def __call__(self) -> float:
        return self.time

    def advance(self, dt: float) -> None:
        self.time += dt


def test_full_vision_debouncer_coordinator_face_pipeline() -> None:
    clock = IntegratedClock(1000.0)
    state_mgr = StateManager(initial_state=AssistantState.IDLE)
    social_engine = SocialEngine(default_cooldown_seconds=60.0)
    event_bus = EventBus()
    animator = FaceAnimator(clock=clock)
    face_ctrl = NullFaceController(animator=animator)
    debouncer = VisionDebouncer(presence_confirm_seconds=2.0, absence_confirm_seconds=2.0, dropout_grace_seconds=0.0, clock=clock)

    coordinator = InteractionCoordinator(
        state_manager=state_mgr,
        social_engine=social_engine,
        event_bus=event_bus,
        mode=SocialMode.WORKSHOP,
        face_controller=face_ctrl,
        debouncer=debouncer,
        clock=clock,
    )

    vision = FakeVisionBackend()
    vision.start()

    # 1. Initially IDLE
    assert state_mgr.current_state == AssistantState.IDLE
    assert face_ctrl.state == AssistantState.BOOTING

    # 2. Person appears at (0.4, 0.2)
    vision.set_presence(present=True, faces_count=1, x=0.4, y=0.2)
    raw1 = vision.get_latest_presence()

    # Instantaneous update: debouncer has not reached 2.0s threshold
    coordinator.handle_raw_presence_observation(raw1)
    assert state_mgr.current_state == AssistantState.IDLE  # still idle!

    # Advance clock past debounce threshold (2.5s)
    clock.advance(2.5)
    raw2 = vision.get_latest_presence()
    decision = coordinator.handle_raw_presence_observation(raw2)

    # 3. State is now ATTENTION, social decision made, Face updated
    assert state_mgr.current_state == AssistantState.ATTENTION
    assert face_ctrl.state == AssistantState.ATTENTION
    assert face_ctrl.gaze == (0.4, 0.2)
    assert decision.action.value == "GREET"

    # Face pose has attentive eyes oriented towards (0.4, 0.2)
    pose = face_ctrl.get_current_pose()
    assert pose.expression in ("attentive", "focused")
    assert pose.gaze_x > 0.0
    assert pose.gaze_y > 0.0

    # 4. Person leaves
    vision.set_presence(present=False)
    clock.advance(0.5)
    raw_lost = vision.get_latest_presence()
    coordinator.handle_raw_presence_observation(raw_lost)
    # Still considered in ATTENTION during 0.5s dropout
    assert state_mgr.current_state == AssistantState.ATTENTION

    # Advance clock past 2.0s debounce for absence
    clock.advance(2.0)
    coordinator.handle_raw_presence_observation(raw_lost)
    # Now transitioned back to IDLE, face centered
    assert state_mgr.current_state == AssistantState.IDLE
    assert face_ctrl.state == AssistantState.IDLE
    assert face_ctrl.gaze == (0.0, 0.0)


def test_opencv_backend_graceful_degradation_without_device() -> None:
    backend = OpenCvVisionBackend(camera_device="/dev/video_non_existent_99", fps=5)
    backend.start()

    health = backend.health()
    # Health indicates disabled, degraded, or unhealthy, not an unhandled exception
    assert health.status.value in ("DISABLED", "DEGRADED", "UNHEALTHY", "UNKNOWN")

    obs = backend.get_latest_presence()
    assert obs.present is False

    backend.stop()
    assert backend.health().status.value == "DISABLED"

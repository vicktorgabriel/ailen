"""Automatic FacePack QA, presentation scaling, and canonical CLI regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ailen.cli import cmd_demo_face, create_parser
from ailen.core.config import AILENConfig
from ailen.domain.enums import AssistantState
from ailen.face.native_controller import (
    fit_presentation_scale,
    presentation_size_for_scale,
)
from ailen.face.native_engine import (
    NativeSequenceCategory,
    NativeSequenceDescriptor,
    NativeSequenceLayer,
)
from ailen.face.showcase import FacePackShowcase, build_showcase_steps

REPO_ROOT = Path(__file__).resolve().parents[2]


def _descriptor(
    sequence_id: str,
    category: NativeSequenceCategory,
    *,
    layer: NativeSequenceLayer = NativeSequenceLayer.FULL_FRAME,
    duration_ms: int = 800,
) -> NativeSequenceDescriptor:
    return NativeSequenceDescriptor(
        id=sequence_id,
        category=category,
        layer=layer,
        flags=0,
        duration_ms=duration_ms,
    )


def _qa_catalog() -> tuple[NativeSequenceDescriptor, ...]:
    return (
        _descriptor("neutral", NativeSequenceCategory.STATE),
        *(
            _descriptor(expression, NativeSequenceCategory.EMOTION)
            for expression in ("happy", "sad", "anger", "curious", "focused")
        ),
        *(
            _descriptor(expression, NativeSequenceCategory.INTENSE_EMOTION)
            for expression in (
                "laugh",
                "laugh_hard",
                "crying",
                "crying_tears",
                "falling_asleep",
                "yawn",
                "wake_up",
            )
        ),
        _descriptor(
            "blink_soft",
            NativeSequenceCategory.MICROACTION,
            layer=NativeSequenceLayer.UPPER_FACE_ROI,
        ),
        _descriptor("nod_yes", NativeSequenceCategory.MICROACTION),
        *(
            _descriptor(
                speech,
                NativeSequenceCategory.SPEECH,
                layer=NativeSequenceLayer.MOUTH_ROI,
            )
            for speech in (
                "talk_soft",
                "talk_normal",
                "talk_expressive",
                "talk_happy",
                "talk_serious",
            )
        ),
    )


class _ShowcaseFace:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    @property
    def available_expressions(self) -> tuple[str, ...]:
        return ("neutral", "happy", "sad", "anger", "curious", "focused")

    @property
    def conversational_expressions(self) -> tuple[str, ...]:
        return ("happy", "sad", "curious")

    @property
    def diagnostic_sequence_catalog(self) -> tuple[NativeSequenceDescriptor, ...]:
        return _qa_catalog()

    @property
    def diagnostic_states(self) -> tuple[str, ...]:
        return ("idle", "waiting", "listening", "processing", "sleeping")

    def set_state(self, state: AssistantState) -> None:
        self.calls.append(("state", state))

    def set_gaze(self, x: float, y: float) -> None:
        self.calls.append(("gaze", x, y))

    def set_speech_level(self, level: float) -> None:
        self.calls.append(("speech_level", level))

    def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
        self.calls.append(("expression", expression, duration_seconds))

    def trigger_diagnostic_microaction(self, microaction: str) -> None:
        self.calls.append(("microaction", microaction))

    def set_diagnostic_speech_sequence(self, sequence: str | None) -> None:
        self.calls.append(("speech_sequence", sequence))

    def sleep(self) -> None:
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        self.set_state(AssistantState.IDLE)

    def is_display_active(self) -> bool:
        return True


def test_showcase_plan_is_pack_driven_and_covers_required_layers() -> None:
    steps = build_showcase_steps(
        _qa_catalog(),
        ("idle", "waiting", "listening", "processing", "sleeping"),
    )

    assert {step.subject_id for step in steps if step.category == "state"} == {
        "idle",
        "listening",
        "processing",
        "sleeping",
    }
    assert {step.subject_id for step in steps if step.category == "gaze"} == {
        "left",
        "right",
        "up",
        "down",
    }
    assert {step.subject_id for step in steps if step.category == "speech"} == {
        "talk_soft",
        "talk_normal",
        "talk_expressive",
        "talk_happy",
        "talk_serious",
    }
    blink = next(step for step in steps if step.subject_id == "blink_soft")
    assert blink.base_expression in {"happy", "sad", "anger"}
    assert {step.subject_id for step in steps if step.category == "transition"} == {
        "laugh",
        "laugh_hard",
        "crying",
        "crying_tears",
        "falling_asleep",
        "yawn",
        "wake_up",
    }


def test_showcase_filters_by_category_or_exact_pack_id() -> None:
    catalog = _qa_catalog()
    states = ("idle", "listening", "processing", "sleeping")

    speech = build_showcase_steps(catalog, states, "speech")
    blink = build_showcase_steps(catalog, states, "blink_soft")

    assert speech and all(step.category == "speech" for step in speech)
    assert len(blink) == 1
    assert blink[0].subject_id == "blink_soft"


def test_showcase_does_not_claim_composable_gaze_for_full_frame_eye_actions() -> None:
    catalog = tuple(
        NativeSequenceDescriptor(
            id=item.id,
            category=item.category,
            layer=(
                NativeSequenceLayer.FULL_FRAME
                if item.layer == NativeSequenceLayer.UPPER_FACE_ROI
                else item.layer
            ),
            flags=item.flags,
            duration_ms=item.duration_ms,
        )
        for item in _qa_catalog()
    )

    steps = build_showcase_steps(catalog, ("idle", "listening"))

    assert not any(step.category == "gaze" for step in steps)
    blink = next(step for step in steps if step.subject_id == "blink_soft")
    assert blink.category == "microaction"
    assert blink.base_expression is None


def test_showcase_runs_one_pass_without_keyboard_input_and_keeps_idle() -> None:
    face = _ShowcaseFace()
    now = [100.0]
    showcase = FacePackShowcase(face, loop=False, clock=lambda: now[0])

    showcase.start()
    for _ in range(len(showcase.steps)):
        current = showcase.current_step
        assert current is not None
        now[0] += current.duration_seconds + 0.01
        showcase.update()

    assert showcase.completed_cycles == 1
    assert ("state", AssistantState.IDLE) in face.calls
    assert any(call[:2] == ("microaction", "blink_soft") for call in face.calls)
    assert any(call[:2] == ("speech_sequence", "talk_normal") for call in face.calls)
    adjacent_calls = tuple(zip(face.calls, face.calls[1:], strict=False))
    assert any(
        left == ("state", AssistantState.SLEEP)
        and right[:2] == ("expression", "falling_asleep")
        for left, right in adjacent_calls
    )
    assert any(
        left == ("state", AssistantState.SLEEP)
        and right[:2] == ("expression", "yawn")
        for left, right in adjacent_calls
    )


def test_presentation_scaling_fits_common_displays_without_distortion_or_crop() -> None:
    assert fit_presentation_scale(480, 480, 800, 480) == (1, 1)
    assert fit_presentation_scale(480, 480, 1280, 720) == (3, 2)
    assert fit_presentation_scale(480, 480, 1920, 1080) == (9, 4)
    assert fit_presentation_scale(480, 480, 320, 240) == (1, 2)

    for canvas_width, canvas_height in (
        (319, 239),
        (800, 480),
        (1024, 600),
        (1280, 720),
        (1920, 1080),
    ):
        ratio = fit_presentation_scale(480, 480, canvas_width, canvas_height)
        presented = presentation_size_for_scale(480, 480, *ratio)
        assert presented[0] <= canvas_width
        assert presented[1] <= canvas_height
        assert presented[0] == presented[1]


def test_demo_face_defaults_to_config_and_accepts_automatic_facepack_showcase() -> None:
    parser = create_parser()
    default_args = parser.parse_args(["demo", "face"])
    showcase_args = parser.parse_args(
        ["demo", "face", "--style", "facepack", "--showcase", "--showcase-filter", "speech"]
    )

    assert default_args.style is None
    assert default_args.fps is None
    assert showcase_args.style == "facepack"
    assert showcase_args.showcase is True
    assert showcase_args.showcase_filter == "speech"


def test_run_sh_face_uses_facepack_and_portrait_is_explicit_legacy_only() -> None:
    script = (REPO_ROOT / "run.sh").read_text(encoding="utf-8")
    face_branch = script.split("face|demo-face)", maxsplit=1)[1].split(";;", maxsplit=1)[0]

    assert "--style facepack" in face_branch
    assert "--style portrait" not in face_branch
    assert "face-portrait|portrait)" in script


def test_demo_face_constructs_facepack_through_runtime_factory(monkeypatch) -> None:
    config = AILENConfig()
    config.display.face_style = "facepack"
    captured: dict[str, object] = {}

    class _DemoFace(_ShowcaseFace):
        def __init__(self) -> None:
            super().__init__()
            self.active = False

        def start_window(self, interactive_keys: bool = False) -> None:
            captured["interactive_keys"] = interactive_keys
            self.active = True

        def is_display_active(self) -> bool:
            return self.active

        def update(self) -> None:
            pass

        def close(self) -> None:
            self.active = False

    face = _DemoFace()

    class _Factory:
        def __init__(self, received: AILENConfig) -> None:
            captured["config"] = received

        def build_face(self, *, headless: bool = False):  # type: ignore[no-untyped-def]
            captured["headless"] = headless
            return face, SimpleNamespace(
                backend="NativeFaceEngine",
                state="READY",
                detail="canonical factory",
            )

    monkeypatch.setattr("ailen.cli.load_config", lambda _path: config)
    monkeypatch.setattr("ailen.runtime.factory.LabComponentFactory", _Factory)
    args = create_parser().parse_args(["demo", "face", "--gui", "--duration", "0"])

    assert cmd_demo_face(args, None) == 0
    assert captured["config"] is config
    assert captured["headless"] is False
    assert captured["interactive_keys"] is False
    assert config.display.face_style == "facepack"

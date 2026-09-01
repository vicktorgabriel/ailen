"""Automatic FacePack visual-QA sequence runner.

This module is diagnostic-only: it consumes normalized FaceController commands,
never MP4, AI, audio, camera, memory, or tools.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from ailen.domain.enums import AssistantState
from ailen.face.contracts import FaceController
from ailen.face.native_engine import (
    NativeSequenceCategory,
    NativeSequenceDescriptor,
    NativeSequenceLayer,
)

_STATE_MAP = {
    "idle": AssistantState.IDLE,
    "waiting": AssistantState.BOOTING,
    "attentive": AssistantState.ATTENTION,
    "listening": AssistantState.LISTENING,
    "processing": AssistantState.PROCESSING,
    "sleeping": AssistantState.SLEEP,
}
_QA_STATES = ("idle", "listening", "processing", "sleeping")
_COMPOSITION_BASES = ("happy", "sad", "anger")
_SPEECH_BASES = ("happy", "sad", "anger", "curious", "focused")
_TRANSITION_RETURN_STATES = {
    "falling_asleep": AssistantState.SLEEP,
    "yawn": AssistantState.SLEEP,
    "wake_up": AssistantState.IDLE,
}


@dataclass(frozen=True)
class ShowcaseStep:
    """One automatically scheduled diagnostic operation."""

    category: str
    subject_id: str
    duration_seconds: float
    base_expression: str | None = None
    layer: NativeSequenceLayer | None = None
    gaze: tuple[float, float] | None = None

    @property
    def label(self) -> str:
        suffix = f" over {self.base_expression}" if self.base_expression else ""
        return f"{self.category}:{self.subject_id}{suffix}"


def build_showcase_steps(
    catalog: tuple[NativeSequenceDescriptor, ...],
    states: tuple[str, ...],
    filter_value: str | None = None,
) -> tuple[ShowcaseStep, ...]:
    """Build the deterministic full-corpus QA pass from active pack metadata."""

    steps: list[ShowcaseStep] = []
    expressions = tuple(
        item
        for item in catalog
        if item.category
        in {NativeSequenceCategory.EMOTION, NativeSequenceCategory.INTENSE_EMOTION}
    )
    available_expression_ids = {item.id for item in expressions}

    for state_id in _QA_STATES:
        if state_id in states:
            steps.append(ShowcaseStep("state", state_id, 3.5))

    for item in expressions:
        steps.append(
            ShowcaseStep(
                "intense_emotion"
                if item.category == NativeSequenceCategory.INTENSE_EMOTION
                else "emotion",
                item.id,
                max(1.2, item.duration_ms / 1000.0 + 0.4),
            )
        )

    upper_index = 0
    for item in catalog:
        if item.category != NativeSequenceCategory.MICROACTION:
            continue
        base: str | None = None
        if item.layer == NativeSequenceLayer.UPPER_FACE_ROI:
            valid_bases = tuple(
                base_id
                for base_id in _COMPOSITION_BASES
                if base_id in available_expression_ids
            )
            if valid_bases:
                base = valid_bases[upper_index % len(valid_bases)]
                upper_index += 1
        steps.append(
            ShowcaseStep(
                "microaction",
                item.id,
                max(1.0, item.duration_ms / 1000.0 + 0.45),
                base_expression=base,
                layer=item.layer,
            )
        )

    has_composable_upper_face = any(
        item.layer == NativeSequenceLayer.UPPER_FACE_ROI for item in catalog
    )
    gaze_base = (
        "happy"
        if has_composable_upper_face and "happy" in available_expression_ids
        else None
    )
    if gaze_base is not None:
        for gaze_id, coordinates in (
            ("left", (-0.9, 0.0)),
            ("right", (0.9, 0.0)),
            ("up", (0.0, 0.9)),
            ("down", (0.0, -0.9)),
        ):
            steps.append(
                ShowcaseStep(
                    "gaze",
                    gaze_id,
                    2.0,
                    base_expression=gaze_base,
                    gaze=coordinates,
                )
            )

    speech_index = 0
    valid_speech_bases = tuple(
        base_id for base_id in _SPEECH_BASES if base_id in available_expression_ids
    )
    for item in catalog:
        if item.category != NativeSequenceCategory.SPEECH:
            continue
        base = (
            valid_speech_bases[speech_index % len(valid_speech_bases)]
            if item.layer == NativeSequenceLayer.MOUTH_ROI and valid_speech_bases
            else None
        )
        speech_index += 1
        steps.append(
            ShowcaseStep(
                "speech",
                item.id,
                3.0,
                base_expression=base,
                layer=item.layer,
            )
        )

    for expression_id in (
        "laugh",
        "laugh_hard",
        "crying",
        "crying_tears",
        "falling_asleep",
        "yawn",
        "wake_up",
    ):
        transition_item = next(
            (entry for entry in expressions if entry.id == expression_id), None
        )
        if transition_item is not None:
            steps.append(
                ShowcaseStep(
                    "transition",
                    expression_id,
                    max(1.2, transition_item.duration_ms / 1000.0 + 0.5),
                )
            )

    clean_filter = (filter_value or "").strip().lower()
    if clean_filter and clean_filter != "all":
        known_categories = {
            "state",
            "emotion",
            "intense_emotion",
            "microaction",
            "gaze",
            "speech",
            "transition",
        }
        if clean_filter in known_categories:
            steps = [step for step in steps if step.category == clean_filter]
        else:
            steps = [step for step in steps if step.subject_id == clean_filter]
    return tuple(steps)


class FacePackShowcase:
    """Drive a Native FaceController through a looping automatic QA pass."""

    def __init__(
        self,
        controller: FaceController,
        *,
        filter_value: str | None = None,
        loop: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.controller = controller
        self.loop = loop
        self.clock = clock
        catalog = tuple(getattr(controller, "diagnostic_sequence_catalog", ()))
        states = tuple(getattr(controller, "diagnostic_states", ()))
        if not catalog or not states:
            raise RuntimeError("the active renderer does not expose FacePack QA metadata")
        self.steps = build_showcase_steps(catalog, states, filter_value)
        if not self.steps:
            raise ValueError(f"showcase filter has no matching FacePack item: {filter_value!r}")
        self._index = -1
        self._step_started_at = 0.0
        self._finished = False
        self.completed_cycles = 0

    @property
    def current_step(self) -> ShowcaseStep | None:
        return self.steps[self._index] if self._index >= 0 else None

    def start(self) -> None:
        self._enter_step(0)

    def update(self) -> None:
        if self._finished:
            return
        if self._index < 0:
            self.start()
        step = self.current_step
        if step is None:
            return
        elapsed = self.clock() - self._step_started_at
        if step.category == "speech":
            speech_pattern = (0.18, 0.62, 0.34, 0.82, 0.28, 0.7)
            level = speech_pattern[int(elapsed * 6.0) % len(speech_pattern)]
            self.controller.set_speech_level(level)
        if elapsed < step.duration_seconds:
            return
        next_index = self._index + 1
        if next_index >= len(self.steps):
            self.completed_cycles += 1
            if not self.loop:
                self._reset_layers()
                self.controller.set_state(AssistantState.IDLE)
                self._finished = True
                print("FACEPACK_QA pass=complete window=kept_open", flush=True)
                return
            next_index = 0
        self._enter_step(next_index)

    def close(self) -> None:
        self._reset_layers()

    def _reset_layers(self) -> None:
        self.controller.set_speech_level(0.0)
        self.controller.set_gaze(0.0, 0.0)
        set_speech_sequence = getattr(
            self.controller,
            "set_diagnostic_speech_sequence",
            None,
        )
        if callable(set_speech_sequence):
            set_speech_sequence(None)
        self.controller.set_expression("neutral", duration_seconds=0.0)

    def _enter_step(self, index: int) -> None:
        self._reset_layers()
        step = self.steps[index]
        self._index = index
        self._step_started_at = self.clock()
        print(
            f"FACEPACK_QA step={index + 1}/{len(self.steps)} item={step.label} "
            f"duration_s={step.duration_seconds:.2f}",
            flush=True,
        )
        if step.category == "state":
            self.controller.set_state(_STATE_MAP[step.subject_id])
            return
        return_state = (
            _TRANSITION_RETURN_STATES.get(step.subject_id)
            if step.category == "transition"
            else None
        )
        self.controller.set_state(return_state or AssistantState.IDLE)
        if step.base_expression is not None:
            self.controller.set_expression(
                step.base_expression,
                duration_seconds=step.duration_seconds,
            )
        if step.category in {"emotion", "intense_emotion", "transition"}:
            self.controller.set_expression(step.subject_id, duration_seconds=0.0)
        elif step.category == "microaction":
            trigger = getattr(self.controller, "trigger_diagnostic_microaction", None)
            if not callable(trigger):
                raise RuntimeError("the active renderer cannot trigger QA microactions")
            trigger(step.subject_id)
        elif step.category == "gaze" and step.gaze is not None:
            self.controller.set_gaze(*step.gaze)
        elif step.category == "speech":
            set_speech_sequence = getattr(
                self.controller,
                "set_diagnostic_speech_sequence",
                None,
            )
            if not callable(set_speech_sequence):
                raise RuntimeError("the active renderer cannot select QA speech sequences")
            set_speech_sequence(step.subject_id)
            self.controller.set_speech_level(0.35)

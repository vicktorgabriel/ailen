"""Runtime-resilient face controller that can fall back without rewiring Core.

The wrapper keeps a stable FaceController identity for Audio/Vision/Tools/Core.
Only fatal native-engine failures request a switch; ordinary errors such as an
unknown expression remain visible to the caller and do not hide bugs.
"""

from __future__ import annotations

import logging
from typing import Any

from ailen.core.capabilities import CapabilityDescriptor
from ailen.domain.enums import AssistantState
from ailen.face.contracts import FaceController
from ailen.face.native_engine import NativeFaceEngineError, NativeFaceResult

logger = logging.getLogger("ailen.face.failover")

_FATAL_NATIVE_RESULTS = {
    NativeFaceResult.IO_ERROR,
    NativeFaceResult.INVALID_PACK,
    NativeFaceResult.INCOMPATIBLE,
    NativeFaceResult.DECODE_ERROR,
    NativeFaceResult.NOT_READY,
    NativeFaceResult.INTERNAL_ERROR,
}


def _fatal_native_error(exc: NativeFaceEngineError) -> bool:
    if exc.result is None:
        return True
    try:
        return NativeFaceResult(exc.result) in _FATAL_NATIVE_RESULTS
    except ValueError:
        return True


class FailoverFaceController:
    """Keep one controller reference while switching native -> configured safe fallback on failure."""

    def __init__(self, primary: FaceController, fallback: FaceController) -> None:
        self.primary = primary
        self.fallback = fallback
        self._active: FaceController = primary
        self._pending_failure: NativeFaceEngineError | None = None
        self._window_started = False
        self._closed = False
        self._state = AssistantState.IDLE
        self._gaze = (0.0, 0.0)
        self._speech_level = 0.0
        self._expression = "neutral"
        self._expression_duration = 0.0

    @property
    def using_fallback(self) -> bool:
        return self._active is self.fallback

    @property
    def available_expressions(self) -> tuple[str, ...]:
        return self._active.available_expressions

    @property
    def conversational_expressions(self) -> tuple[str, ...]:
        return self._active.conversational_expressions

    @property
    def active_controller(self) -> FaceController:
        """Expose the active adapter for internal diagnostics, never for Core routing."""

        return self._active

    @property
    def diagnostic_sequence_catalog(self) -> tuple[Any, ...]:
        return tuple(getattr(self._active, "diagnostic_sequence_catalog", ()))

    @property
    def diagnostic_states(self) -> tuple[str, ...]:
        return tuple(getattr(self._active, "diagnostic_states", ()))

    def trigger_diagnostic_microaction(self, microaction: str) -> None:
        self._call("trigger_diagnostic_microaction", microaction)

    def set_diagnostic_speech_sequence(self, sequence: str | None) -> None:
        self._call("set_diagnostic_speech_sequence", sequence)

    def _request_failover(self, exc: NativeFaceEngineError) -> None:
        if not _fatal_native_error(exc):
            raise exc
        if self._pending_failure is None and not self.using_fallback:
            self._pending_failure = exc
            logger.error("Native face failed; headless degradation requested: %s", exc)

    def _call(self, method: str, *args: object) -> Any:
        target = self._active
        try:
            return getattr(target, method)(*args)
        except NativeFaceEngineError as exc:
            if target is not self.primary:
                raise
            self._request_failover(exc)
            return None

    def _activate_fallback(self) -> None:
        if self.using_fallback or self._closed:
            self._pending_failure = None
            return
        failure = self._pending_failure
        self._pending_failure = None
        try:
            close = getattr(self.primary, "close", None)
            if callable(close):
                close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error closing failed native face: %s", exc)

        self._active = self.fallback
        if self._window_started:
            start = getattr(self.fallback, "start_window", None)
            if callable(start):
                start(interactive_keys=False)
        self.fallback.set_state(self._state)
        self.fallback.set_gaze(*self._gaze)
        self.fallback.set_speech_level(self._speech_level)
        if self._expression != "neutral":
            try:
                if self._expression in self.fallback.available_expressions:
                    self.fallback.set_expression(
                        self._expression,
                        duration_seconds=self._expression_duration,
                    )
            except (ValueError, RuntimeError) as exc:
                logger.debug("Could not replay expression on safe face fallback: %s", exc)
        logger.warning(
            "Face renderer disabled after native FacePack failure%s",
            f" after {failure}" if failure else "",
        )

    def is_display_active(self) -> bool:
        return self._active.is_display_active()

    def start_window(self, interactive_keys: bool = False) -> None:
        self._window_started = True
        try:
            start = self._active.start_window  # type: ignore[attr-defined]
            start(interactive_keys=interactive_keys)
        except NativeFaceEngineError as exc:
            self._request_failover(exc)
            self._activate_fallback()

    def set_state(self, state: AssistantState) -> None:
        self._state = state
        self._call("set_state", state)

    def set_gaze(self, x: float, y: float) -> None:
        self._gaze = (x, y)
        self._call("set_gaze", x, y)

    def set_speech_level(self, level: float) -> None:
        self._speech_level = level
        self._call("set_speech_level", level)

    def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
        self._expression = expression.strip().lower()
        self._expression_duration = duration_seconds
        self._call("set_expression", expression, duration_seconds)

    def sleep(self) -> None:
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        self.set_state(AssistantState.IDLE)

    def update(self) -> None:
        if self._pending_failure is not None:
            self._activate_fallback()
        try:
            update = getattr(self._active, "update", None)
            if callable(update):
                update()
        except NativeFaceEngineError as exc:
            if self._active is not self.primary:
                raise
            self._request_failover(exc)
            self._activate_fallback()
            update = getattr(self._active, "update", None)
            if callable(update):
                update()

    def capabilities(self) -> list[CapabilityDescriptor]:
        provider = getattr(self._active, "capabilities", None)
        return provider() if callable(provider) else []

    def describe_capabilities(self) -> list[CapabilityDescriptor]:
        provider = getattr(self._active, "describe_capabilities", None)
        return provider() if callable(provider) else self.capabilities()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for controller in (self.primary, self.fallback):
            try:
                close = getattr(controller, "close", None)
                if callable(close):
                    close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error closing face controller: %s", exc)

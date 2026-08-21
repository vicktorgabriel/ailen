"""Audio Turn Gate for Half-Duplex Speech/Audio Coordination.

Prevents the assistant from listening to and transcribing its own speaker output
by blocking audio input while text-to-speech (TTS) playback is active.
"""

import threading
import time
from collections.abc import Callable
from enum import Enum


class GateState(str, Enum):
    """Audio turn gate state."""
    LISTENING_ALLOWED = "LISTENING_ALLOWED"
    SPEAKING_BLOCKED = "SPEAKING_BLOCKED"


class AudioTurnGate:
    """Controls half-duplex turn-taking between microphone and speaker.

    While speaking:
    - Input audio frames are rejected / dropped.
    - VAD and STT buffers are held in a safe state.

    After speaking completes:
    - Listening re-opens after a configurable settling cooldown
      to let acoustic room reverb dissipate.
    """

    def __init__(
        self,
        settling_cooldown_seconds: float = 0.15,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settling_cooldown_seconds = settling_cooldown_seconds
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()

        self._state: GateState = GateState.LISTENING_ALLOWED
        self._speaking_end_time: float = float("-inf")

    @property
    def state(self) -> GateState:
        """Current gate state."""
        with self._lock:
            return self._state

    def start_speaking(self) -> None:
        """Signal that speech synthesis/playback has started. Blocks input."""
        with self._lock:
            self._state = GateState.SPEAKING_BLOCKED

    def stop_speaking(self) -> None:
        """Signal that speech synthesis/playback has finished. Starts settling cooldown."""
        with self._lock:
            self._state = GateState.LISTENING_ALLOWED
            self._speaking_end_time = self._clock()

    def is_listening_allowed(self) -> bool:
        """Return True if microphone input should be processed, False if blocked."""
        with self._lock:
            if self._state == GateState.SPEAKING_BLOCKED:
                return False

            now = self._clock()
            return (now - self._speaking_end_time) >= self.settling_cooldown_seconds

    def filter_frame(self, frame: bytes | None) -> bytes | None:
        """Filter incoming audio frame based on gate status.

        Returns frame if listening is allowed, or None if blocked.
        """
        if frame is None:
            return None
        if self.is_listening_allowed():
            return frame
        return None

"""Structured operational telemetry and metrics for Lab Mode sessions."""

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LabSessionMetrics:
    """Collects real observational latency and throughput metrics during a lab session."""

    session_id: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    utterances_count: int = 0
    stt_success_count: int = 0
    stt_fail_count: int = 0
    stt_latencies_ms: list[float] = field(default_factory=list)

    ai_calls_count: int = 0
    ai_latencies_ms: list[float] = field(default_factory=list)
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    token_usage_complete: bool = True

    tts_calls_count: int = 0
    tts_latencies_ms: list[float] = field(default_factory=list)

    vision_observations_count: int = 0
    presence_transitions_count: int = 0
    face_frames_count: int = 0

    def finalize(self) -> None:
        """Mark session end timestamp."""
        if self.ended_at is None:
            self.ended_at = time.time()

    def record_utterance(self, success: bool, latency_ms: float = 0.0) -> None:
        """Record an STT utterance attempt and its latency."""
        self.utterances_count += 1
        if success:
            self.stt_success_count += 1
            if latency_ms > 0:
                self.stt_latencies_ms.append(latency_ms)
        else:
            self.stt_fail_count += 1

    def record_ai_call(
        self,
        latency_ms: float,
        in_tokens: int | None = None,
        out_tokens: int | None = None,
    ) -> None:
        """Record an AI inference request without fabricating missing token usage."""
        self.ai_calls_count += 1
        if latency_ms > 0:
            self.ai_latencies_ms.append(latency_ms)
        if in_tokens is None or out_tokens is None:
            self.token_usage_complete = False
            return
        self.input_tokens_total += in_tokens
        self.output_tokens_total += out_tokens

    def record_tts_call(self, latency_ms: float) -> None:
        """Record a TTS vocal synthesis call."""
        self.tts_calls_count += 1
        if latency_ms > 0:
            self.tts_latencies_ms.append(latency_ms)

    def record_vision_obs(self) -> None:
        """Increment observed vision frames."""
        self.vision_observations_count += 1

    def record_presence_transition(self) -> None:
        """Increment presence state changes."""
        self.presence_transitions_count += 1

    def record_face_frame(self) -> None:
        """Increment animated face frames."""
        self.face_frames_count += 1

    @staticmethod
    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    @staticmethod
    def _p95(values: list[float]) -> float | None:
        if not values:
            return None
        sorted_v = sorted(values)
        idx = int(len(sorted_v) * 0.95)
        idx = min(idx, len(sorted_v) - 1)
        return round(sorted_v[idx], 1)

    @property
    def duration_seconds(self) -> float:
        """Return total duration in seconds."""
        end = self.ended_at or time.time()
        return round(max(0.0, end - self.started_at), 2)

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to serializable dictionary."""
        dur = self.duration_seconds
        fps = round(self.face_frames_count / dur, 1) if dur > 0 and self.face_frames_count > 0 else None

        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": dur,
            "speech": {
                "utterances": self.utterances_count,
                "stt_success": self.stt_success_count,
                "stt_fail": self.stt_fail_count,
                "stt_latency_avg_ms": self._avg(self.stt_latencies_ms),
                "stt_latency_p95_ms": self._p95(self.stt_latencies_ms),
                "tts_calls": self.tts_calls_count,
                "tts_latency_avg_ms": self._avg(self.tts_latencies_ms),
                "tts_latency_p95_ms": self._p95(self.tts_latencies_ms),
            },
            "ai": {
                "calls": self.ai_calls_count,
                "latency_avg_ms": self._avg(self.ai_latencies_ms),
                "latency_p95_ms": self._p95(self.ai_latencies_ms),
                "tokens_in": self.input_tokens_total if self.token_usage_complete else None,
                "tokens_out": self.output_tokens_total if self.token_usage_complete else None,
                "token_usage_complete": self.token_usage_complete,
            },
            "presence": {
                "observations": self.vision_observations_count,
                "transitions": self.presence_transitions_count,
            },
            "face": {
                "frames": self.face_frames_count,
                "fps_estimate": fps,
            },
        }

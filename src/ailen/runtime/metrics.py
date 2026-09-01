"""Structured operational telemetry and metrics for Lab Mode sessions."""

import threading
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
    ai_prompt_eval_ms: list[float] = field(default_factory=list)
    ai_generation_ms: list[float] = field(default_factory=list)
    ai_load_ms: list[float] = field(default_factory=list)
    ai_first_text_ms: list[float] = field(default_factory=list)
    ai_provider_setup_ms: list[float] = field(default_factory=list)
    ai_provider_ready_ms: list[float] = field(default_factory=list)
    ai_request_chars_total: int = 0
    ai_provider_model_counts: dict[str, int] = field(default_factory=dict)
    ai_fallback_count: int = 0
    ai_fallback_causes: dict[str, int] = field(default_factory=dict)
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    token_usage_complete: bool = True
    tts_calls_count: int = 0
    tts_latencies_ms: list[float] = field(default_factory=list)

    ttfar_latencies_ms: list[float] = field(default_factory=list)

    vision_polls_count: int = 0
    vision_valid_frames_count: int = 0
    presence_transitions_count: int = 0
    face_frames_count: int = 0
    turn_stages: list[dict[str, Any]] = field(default_factory=list)
    _turn_stage_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )

    _TURN_STAGE_FIELDS = frozenset(
        {
            "accepted",
            "action_allowed",
            "audio_duration_ms",
            "backend",
            "confidence",
            "confidence_band",
            "cancelled",
            "duration_ms",
            "ended_monotonic",
            "engine",
            "error_kind",
            "expression_accepted",
            "expression_requested",
            "fallback_cause",
            "fallback_used",
            "finish_reason",
            "first_phrase_ms",
            "first_text_ms",
            "frame_count",
            "generation_id",
            "generation_cancelled",
            "intent",
            "input_tokens",
            "interrupted",
            "invoked",
            "model",
            "matched",
            "message_count",
            "output_chars",
            "output_tokens",
            "playback_stop_ms",
            "provider",
            "provider_ready_ms",
            "provider_tool_count",
            "provider_setup_ms",
            "reason_code",
            "request_to_pcm_ms",
            "request_chars",
            "result",
            "route_reason",
            "semantic_attempted",
            "sequence",
            "started_monotonic",
            "status",
            "stale",
            "success",
            "system_chars",
            "synthesizer_draining",
            "tool",
            "truncated",
            "tts_latency_ms",
            "utterance_id",
        }
    )

    def finalize(self) -> None:
        """Mark session end timestamp."""
        if self.ended_at is None:
            self.ended_at = time.time()

    def record_ttfar(self, latency_ms: float) -> None:
        """Record TTFAR proxy: end of speech to first PCM buffer submitted for playback."""
        if latency_ms > 0:
            self.ttfar_latencies_ms.append(latency_ms)

    def record_turn_stage(self, turn_id: str, stage: str, **metadata: Any) -> None:
        """Store bounded scalar telemetry; text, prompts and memory are rejected."""
        safe: dict[str, Any] = {
            "turn_id": str(turn_id).strip()[:80] or "unknown",
            "stage": str(stage).strip()[:80] or "unknown",
            "observed_at": time.time(),
        }
        for key, value in metadata.items():
            if key not in self._TURN_STAGE_FIELDS:
                continue
            if value is None or isinstance(value, (bool, int, float)):
                safe[key] = value
            elif isinstance(value, str):
                safe[key] = value.strip()[:160]
        with self._turn_stage_lock:
            self.turn_stages.append(safe)
            if len(self.turn_stages) > 512:
                del self.turn_stages[: len(self.turn_stages) - 512]

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
        prompt_eval_ms: float | None = None,
        generation_ms: float | None = None,
        load_ms: float | None = None,
        provider: str | None = None,
        model: str | None = None,
        first_text_ms: float | None = None,
        provider_setup_ms: float | None = None,
        provider_ready_ms: float | None = None,
        request_chars: int | None = None,
        fallback_used: bool = False,
        fallback_cause: str | None = None,
    ) -> None:
        """Record an AI inference request without fabricating missing token usage."""
        self.ai_calls_count += 1
        if latency_ms > 0:
            self.ai_latencies_ms.append(latency_ms)
        if prompt_eval_ms is not None and prompt_eval_ms >= 0:
            self.ai_prompt_eval_ms.append(prompt_eval_ms)
        if generation_ms is not None and generation_ms >= 0:
            self.ai_generation_ms.append(generation_ms)
        if load_ms is not None and load_ms >= 0:
            self.ai_load_ms.append(load_ms)
        if first_text_ms is not None and first_text_ms >= 0:
            self.ai_first_text_ms.append(first_text_ms)
        if provider_setup_ms is not None and provider_setup_ms >= 0:
            self.ai_provider_setup_ms.append(provider_setup_ms)
        if provider_ready_ms is not None and provider_ready_ms >= 0:
            self.ai_provider_ready_ms.append(provider_ready_ms)
        if request_chars is not None and request_chars >= 0:
            self.ai_request_chars_total += request_chars
        if provider and model:
            key = f"{provider}:{model}"
            self.ai_provider_model_counts[key] = self.ai_provider_model_counts.get(key, 0) + 1
        if fallback_used:
            self.ai_fallback_count += 1
            cause = fallback_cause or "unknown"
            self.ai_fallback_causes[cause] = self.ai_fallback_causes.get(cause, 0) + 1
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

    def record_vision_poll(self) -> None:
        """Increment runtime reads of the latest observation."""
        self.vision_polls_count += 1

    def record_vision_frame(self) -> None:
        """Increment observations backed by a newly decoded camera frame."""
        self.vision_valid_frames_count += 1

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

        with self._turn_stage_lock:
            turn_stages = [dict(stage) for stage in self.turn_stages]

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
                "ttfar_avg_ms": self._avg(self.ttfar_latencies_ms),
                "ttfar_p95_ms": self._p95(self.ttfar_latencies_ms),
            },
            "ai": {
                "calls": self.ai_calls_count,
                "latency_avg_ms": self._avg(self.ai_latencies_ms),
                "latency_p95_ms": self._p95(self.ai_latencies_ms),
                "prompt_eval_avg_ms": self._avg(self.ai_prompt_eval_ms),
                "prompt_eval_p95_ms": self._p95(self.ai_prompt_eval_ms),
                "generation_avg_ms": self._avg(self.ai_generation_ms),
                "generation_p95_ms": self._p95(self.ai_generation_ms),
                "load_avg_ms": self._avg(self.ai_load_ms),
                "first_text_avg_ms": self._avg(self.ai_first_text_ms),
                "first_text_p95_ms": self._p95(self.ai_first_text_ms),
                "provider_setup_avg_ms": self._avg(self.ai_provider_setup_ms),
                "provider_ready_avg_ms": self._avg(self.ai_provider_ready_ms),
                "request_chars_total": self.ai_request_chars_total,
                "provider_model_counts": dict(self.ai_provider_model_counts),
                "fallback_count": self.ai_fallback_count,
                "fallback_causes": dict(self.ai_fallback_causes),
                "tokens_in": self.input_tokens_total if self.token_usage_complete else None,
                "tokens_out": self.output_tokens_total if self.token_usage_complete else None,
                "token_usage_complete": self.token_usage_complete,
            },
            "presence": {
                "polls": self.vision_polls_count,
                "valid_frames": self.vision_valid_frames_count,
                "transitions": self.presence_transitions_count,
            },
            "face": {
                "frames": self.face_frames_count,
                "fps_estimate": fps,
            },
            "turns": {
                "stages": turn_stages,
                "content_persisted": False,
            },
        }

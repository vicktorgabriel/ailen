"""Confidence-aware STT fallback composition for CPU-first deployments."""

import logging

from ailen.audio.contracts import (
    AudioBackendHealth,
    AudioSegment,
    SttBackend,
    Transcript,
    TranscriptAlternative,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger(__name__)


class CascadingSttBackend:
    """Use a fast primary STT and invoke a slower fallback only when needed."""

    def __init__(
        self,
        primary: SttBackend,
        fallback: SttBackend,
        confidence_threshold: float = 0.72,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.confidence_threshold = max(0.0, min(1.0, confidence_threshold))

    def health(self) -> AudioBackendHealth:
        primary_health = self.primary.health()
        fallback_health = self.fallback.health()
        if primary_health.status == ServiceStatus.HEALTHY:
            detail = f"Primary ready; fallback={fallback_health.status.value}"
            return AudioBackendHealth(ServiceStatus.HEALTHY, detail)
        if fallback_health.status == ServiceStatus.HEALTHY:
            return AudioBackendHealth(
                ServiceStatus.DEGRADED,
                f"Primary unavailable; fallback ready ({primary_health.detail})",
            )
        return AudioBackendHealth(
            ServiceStatus.UNHEALTHY,
            f"Primary={primary_health.status.value}; fallback={fallback_health.status.value}",
        )

    def transcribe(self, segment: AudioSegment) -> Transcript:
        primary = self.primary.transcribe(segment)
        primary_text = primary.text.strip()
        needs_fallback = (
            not primary_text
            or (
                primary.confidence is not None
                and primary.confidence < self.confidence_threshold
            )
        )
        if not needs_fallback:
            logger.info(
                "stt_cascade stage=primary_selected confidence=%s chars=%d latency_ms=%.1f",
                "unknown" if primary.confidence is None else f"{primary.confidence:.3f}",
                len(primary_text),
                primary.latency_ms,
            )
            return primary

        fallback = self.fallback.transcribe(segment)
        fallback_text = fallback.text.strip()
        logger.info(
            "stt_cascade stage=fallback_attempt primary_confidence=%s primary_chars=%d "
            "fallback_chars=%d primary_latency_ms=%.1f fallback_latency_ms=%.1f",
            "unknown" if primary.confidence is None else f"{primary.confidence:.3f}",
            len(primary_text),
            len(fallback_text),
            primary.latency_ms,
            fallback.latency_ms,
        )
        if not fallback_text:
            return primary
        return Transcript(
            text=fallback_text,
            language=fallback.language or primary.language,
            confidence=fallback.confidence,
            latency_ms=primary.latency_ms + fallback.latency_ms,
            engine=f"cascade:{fallback.engine}",
            alternatives=(
                *fallback.alternatives,
                *(
                    ()
                    if not primary_text
                    else (
                        TranscriptAlternative(
                            text=primary_text,
                            confidence=primary.confidence,
                        ),
                    )
                ),
            ),
        )

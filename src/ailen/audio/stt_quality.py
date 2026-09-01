"""Heuristic STT quality evaluator and reprompt policy.

Prevents sending noisy, partial, or unintelligible utterances to the LLM.
Explicitly avoids fabricating synthetic confidence scores when engines do not provide them.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ailen.audio.contracts import TranscriptAlternative


class SttConfidenceBand(str, Enum):
    """Meaning of real acoustic confidence; UNKNOWN is never synthesized."""

    UNKNOWN = "unknown"
    NOISE = "noise"
    DOUBTFUL = "doubtful"
    CONVERSATION = "conversation"
    ACTION = "action"


@dataclass(frozen=True)
class SttQualityAssessment:
    """Heuristic assessment of a speech recognition transcript."""
    raw_text: str
    cleaned_text: str
    word_count: int
    char_count: int
    is_empty: bool
    is_too_short: bool
    is_fragment: bool
    heuristic_quality: float  # [0.0..1.0] purely heuristic readability score (NEVER labeled as model confidence)
    should_reprompt: bool
    should_drop_silently: bool
    reprompt_reason: str
    acoustic_confidence: float | None = None
    confidence_band: SttConfidenceBand = SttConfidenceBand.UNKNOWN
    selected_alternative: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "cleaned_text": self.cleaned_text,
            "word_count": self.word_count,
            "char_count": self.char_count,
            "is_empty": self.is_empty,
            "is_too_short": self.is_too_short,
            "is_fragment": self.is_fragment,
            "heuristic_quality": self.heuristic_quality,
            "should_reprompt": self.should_reprompt,
            "should_drop_silently": self.should_drop_silently,
            "reprompt_reason": self.reprompt_reason,
            "acoustic_confidence": self.acoustic_confidence,
            "confidence_band": self.confidence_band.value,
            "selected_alternative": self.selected_alternative,
        }


class SttQualityEvaluator:
    """Evaluates transcript quality using explicit heuristic rules."""

    DEFAULT_REPROMPT_MESSAGE = "No entendí bien, ¿podés repetirlo?"

    def __init__(
        self,
        min_words: int = 1,
        min_chars: int = 2,
        *,
        noise_confidence_max: float = 0.20,
        conversation_min_confidence: float = 0.45,
        action_min_confidence: float = 0.72,
    ) -> None:
        if not 0.0 <= noise_confidence_max < conversation_min_confidence <= action_min_confidence <= 1.0:
            raise ValueError(
                "confidence thresholds must satisfy 0 <= noise < conversation <= action <= 1"
            )
        self.min_words = min_words
        self.min_chars = min_chars
        self.noise_confidence_max = noise_confidence_max
        self.conversation_min_confidence = conversation_min_confidence
        self.action_min_confidence = action_min_confidence

    def evaluate(
        self,
        transcript: str,
        confidence: float | None = None,
        alternatives: tuple[TranscriptAlternative, ...] = (),
    ) -> SttQualityAssessment:
        """Analyze transcript using readability plus real engine confidence when available."""
        raw = transcript or ""
        clean = raw.strip()

        normalized_confidence = self._normalize_confidence(confidence)
        selected_alternative = False
        if normalized_confidence is None or normalized_confidence < self.conversation_min_confidence:
            viable_alternatives = [
                (alternative, self._normalize_confidence(alternative.confidence))
                for alternative in alternatives
                if alternative.text.strip()
            ]
            known_alternatives = [
                (alternative, alternative_confidence)
                for alternative, alternative_confidence in viable_alternatives
                if alternative_confidence is not None
            ]
            if known_alternatives:
                best_alternative, best_confidence = max(
                    known_alternatives,
                    key=lambda item: item[1] if item[1] is not None else -1.0,
                )
                if (
                    best_confidence is not None
                    and best_confidence >= self.conversation_min_confidence
                    and (
                        normalized_confidence is None
                        or best_confidence > normalized_confidence
                    )
                ):
                    clean = best_alternative.text.strip()
                    normalized_confidence = best_confidence
                    selected_alternative = True

        confidence_band = self._confidence_band(normalized_confidence)

        # 1. Empty check
        if not clean:
            return SttQualityAssessment(
                raw_text=raw,
                cleaned_text="",
                word_count=0,
                char_count=0,
                is_empty=True,
                is_too_short=True,
                is_fragment=True,
                heuristic_quality=0.0,
                should_reprompt=True,
                should_drop_silently=False,
                reprompt_reason="EMPTY_TRANSCRIPT",
                acoustic_confidence=normalized_confidence,
                confidence_band=confidence_band,
                selected_alternative=selected_alternative,
            )

        words = [w for w in re.split(r"\s+", clean) if w]
        char_len = len(clean)
        normalized = clean.lower().strip(" ¿?¡!.,;:")

        # Only the explicit noise band may be dropped silently, and only for a
        # tiny fragment. Substantive text and the doubtful band ask the speaker
        # to repeat rather than inventing meaning from bad acoustics.
        if confidence_band is SttConfidenceBand.NOISE:
            tiny_single = len(words) == 1 and char_len <= 5
            if tiny_single:
                return SttQualityAssessment(
                    raw_text=raw,
                    cleaned_text=clean,
                    word_count=len(words),
                    char_count=char_len,
                    is_empty=False,
                    is_too_short=tiny_single,
                    is_fragment=True,
                    heuristic_quality=(
                        normalized_confidence
                        if normalized_confidence is not None
                        else 0.0
                    ),
                    should_reprompt=False,
                    should_drop_silently=True,
                    reprompt_reason="LOW_CONFIDENCE_NOISE",
                    acoustic_confidence=normalized_confidence,
                    confidence_band=confidence_band,
                    selected_alternative=selected_alternative,
                )
            return SttQualityAssessment(
                raw_text=raw,
                cleaned_text=clean,
                word_count=len(words),
                char_count=char_len,
                is_empty=False,
                is_too_short=False,
                is_fragment=True,
                heuristic_quality=normalized_confidence or 0.0,
                should_reprompt=True,
                should_drop_silently=False,
                reprompt_reason="ACOUSTIC_NOISE_CONFIDENCE",
                acoustic_confidence=normalized_confidence,
                confidence_band=confidence_band,
                selected_alternative=selected_alternative,
            )

        if confidence_band is SttConfidenceBand.DOUBTFUL:
            return SttQualityAssessment(
                raw_text=raw,
                cleaned_text=clean,
                word_count=len(words),
                char_count=char_len,
                is_empty=False,
                is_too_short=False,
                is_fragment=True,
                heuristic_quality=normalized_confidence or 0.0,
                should_reprompt=True,
                should_drop_silently=False,
                reprompt_reason="DOUBTFUL_ACOUSTIC_CONFIDENCE",
                acoustic_confidence=normalized_confidence,
                confidence_band=confidence_band,
                selected_alternative=selected_alternative,
            )

        # Common one-word fillers/fragments from Vosk should not be handed to
        # the conversational model, which otherwise tends to complete them from
        # stale context. Keep known one-word commands usable.
        vague_single_words = {
            "es", "el", "la", "lo", "un", "una", "que", "qué", "esto", "eso",
            "ahora", "bueno", "bien", "aja", "ajá",
        }
        meaningful_single_commands = {
            "hora", "notas", "silencio", "mute", "pausa", "siguiente", "diagnóstico", "diagnostico",
        }
        if len(words) == 1 and normalized in vague_single_words and normalized not in meaningful_single_commands:
            return SttQualityAssessment(
                raw_text=raw, cleaned_text=clean, word_count=1, char_count=char_len,
                is_empty=False, is_too_short=False, is_fragment=True,
                heuristic_quality=0.25, should_reprompt=True,
                should_drop_silently=False,
                reprompt_reason="AMBIGUOUS_SINGLE_WORD_FRAGMENT",
                acoustic_confidence=normalized_confidence,
                confidence_band=confidence_band,
                selected_alternative=selected_alternative,
            )

        # 2. Too short / Noise check
        is_too_short = char_len < self.min_chars
        is_single_char = len(words) == 1 and len(words[0]) == 1 and words[0].lower() not in {"a", "y", "o", "e", "u", "sí", "no"}

        # 3. Fragment check (e.g. punctuation only or meaningless symbols)
        has_letters = bool(re.search(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]", clean))
        if not has_letters:
            return SttQualityAssessment(
                raw_text=raw,
                cleaned_text=clean,
                word_count=len(words),
                char_count=char_len,
                is_empty=False,
                is_too_short=True,
                is_fragment=True,
                heuristic_quality=0.0,
                should_reprompt=True,
                should_drop_silently=False,
                reprompt_reason="NO_ALPHANUMERIC_CONTENT",
                acoustic_confidence=normalized_confidence,
                confidence_band=confidence_band,
                selected_alternative=selected_alternative,
            )

        if is_too_short or is_single_char:
            return SttQualityAssessment(
                raw_text=raw,
                cleaned_text=clean,
                word_count=len(words),
                char_count=char_len,
                is_empty=False,
                is_too_short=True,
                is_fragment=True,
                heuristic_quality=0.2,
                should_reprompt=True,
                should_drop_silently=False,
                reprompt_reason="TRANSCRIPT_TOO_SHORT",
                acoustic_confidence=normalized_confidence,
                confidence_band=confidence_band,
                selected_alternative=selected_alternative,
            )

        # 4. Valid substantive speech
        # Compute heuristic score based on word count and length
        quality_score = min(1.0, 0.4 + (0.1 * min(6, len(words))))

        return SttQualityAssessment(
            raw_text=raw,
            cleaned_text=clean,
            word_count=len(words),
            char_count=char_len,
            is_empty=False,
            is_too_short=False,
            is_fragment=False,
            heuristic_quality=quality_score,
            should_reprompt=False,
            should_drop_silently=False,
            reprompt_reason="VALID_SPEECH",
            acoustic_confidence=normalized_confidence,
            confidence_band=confidence_band,
            selected_alternative=selected_alternative,
        )

    @staticmethod
    def _normalize_confidence(confidence: float | None) -> float | None:
        if not isinstance(confidence, (int, float)):
            return None
        return max(0.0, min(1.0, float(confidence)))

    def _confidence_band(self, confidence: float | None) -> SttConfidenceBand:
        if confidence is None:
            return SttConfidenceBand.UNKNOWN
        if confidence < self.noise_confidence_max:
            return SttConfidenceBand.NOISE
        if confidence < self.conversation_min_confidence:
            return SttConfidenceBand.DOUBTFUL
        if confidence < self.action_min_confidence:
            return SttConfidenceBand.CONVERSATION
        return SttConfidenceBand.ACTION

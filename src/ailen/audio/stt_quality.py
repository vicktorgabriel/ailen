"""Heuristic STT quality evaluator and reprompt policy.

Prevents sending noisy, partial, or unintelligible utterances to the LLM.
Explicitly avoids fabricating synthetic confidence scores when engines do not provide them.
"""

import re
from dataclasses import dataclass
from typing import Any


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
    reprompt_reason: str

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
            "reprompt_reason": self.reprompt_reason,
        }


class SttQualityEvaluator:
    """Evaluates transcript quality using explicit heuristic rules."""

    DEFAULT_REPROMPT_MESSAGE = "No entendí bien, ¿podés repetirlo?"

    def __init__(self, min_words: int = 1, min_chars: int = 2) -> None:
        self.min_words = min_words
        self.min_chars = min_chars

    def evaluate(self, transcript: str) -> SttQualityAssessment:
        """Analyze transcript and determine if it requires reprompting."""
        raw = transcript or ""
        clean = raw.strip()

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
                reprompt_reason="EMPTY_TRANSCRIPT",
            )

        words = [w for w in re.split(r"\s+", clean) if w]
        char_len = len(clean)

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
                reprompt_reason="NO_ALPHANUMERIC_CONTENT",
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
                reprompt_reason="TRANSCRIPT_TOO_SHORT",
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
            reprompt_reason="VALID_SPEECH",
        )

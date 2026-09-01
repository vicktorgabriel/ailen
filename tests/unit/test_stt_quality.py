"""Unit tests for SttQualityEvaluator and reprompt policy."""

from ailen.audio.contracts import TranscriptAlternative
from ailen.audio.stt_quality import SttConfidenceBand, SttQualityEvaluator


def test_empty_transcript_triggers_reprompt() -> None:
    evaluator = SttQualityEvaluator()
    assessment = evaluator.evaluate("")
    assert assessment.is_empty
    assert assessment.should_reprompt
    assert assessment.reprompt_reason == "EMPTY_TRANSCRIPT"
    assert assessment.heuristic_quality == 0.0

    assessment_spaces = evaluator.evaluate("   \n\t  ")
    assert assessment_spaces.is_empty
    assert assessment_spaces.should_reprompt


def test_too_short_or_symbol_only_triggers_reprompt() -> None:
    evaluator = SttQualityEvaluator()

    assessment_punct = evaluator.evaluate("...")
    assert assessment_punct.should_reprompt
    assert assessment_punct.reprompt_reason == "NO_ALPHANUMERIC_CONTENT"

    assessment_char = evaluator.evaluate("k")
    assert assessment_char.should_reprompt
    assert assessment_char.reprompt_reason == "TRANSCRIPT_TOO_SHORT"


def test_substantive_speech_passes() -> None:
    evaluator = SttQualityEvaluator()
    assessment = evaluator.evaluate("Hola AILEN cómo estás hoy")
    assert not assessment.is_empty
    assert not assessment.is_too_short
    assert not assessment.should_reprompt
    assert assessment.reprompt_reason == "VALID_SPEECH"
    assert assessment.heuristic_quality >= 0.8
    assert assessment.word_count == 5


def test_vague_single_word_fragment_reprompts() -> None:
    evaluator = SttQualityEvaluator()
    for text in ("es", "la", "ahora", "ajá"):
        assessment = evaluator.evaluate(text)
        assert assessment.should_reprompt, text
        assert assessment.reprompt_reason == "AMBIGUOUS_SINGLE_WORD_FRAGMENT"

    assert evaluator.evaluate("hora").should_reprompt is False
    assert evaluator.evaluate("notas").should_reprompt is False


def test_doubtful_short_transcript_reprompts_instead_of_being_assumed_noise() -> None:
    evaluator = SttQualityEvaluator()
    assessment = evaluator.evaluate("hola", confidence=0.31)
    assert not assessment.should_drop_silently
    assert assessment.should_reprompt
    assert assessment.reprompt_reason == "DOUBTFUL_ACOUSTIC_CONFIDENCE"


def test_confident_short_conversation_remains_valid() -> None:
    evaluator = SttQualityEvaluator()
    for text in ("sí", "no", "hola", "dale"):
        assessment = evaluator.evaluate(text, confidence=0.91)
        assert not assessment.should_drop_silently, text
        assert not assessment.should_reprompt, text


def test_low_confidence_longer_speech_requires_repetition() -> None:
    evaluator = SttQualityEvaluator()
    uncertain = evaluator.evaluate("hola como estas", confidence=0.25)
    assert not uncertain.should_drop_silently
    assert uncertain.should_reprompt
    assert uncertain.confidence_band is SttConfidenceBand.DOUBTFUL
    assert uncertain.reprompt_reason == "DOUBTFUL_ACOUSTIC_CONFIDENCE"
    usable = evaluator.evaluate("hola como estas", confidence=0.58)
    assert not usable.should_drop_silently
    assert not usable.should_reprompt
    assert usable.confidence_band is SttConfidenceBand.CONVERSATION


def test_extremely_low_confidence_multiword_is_not_valid_speech() -> None:
    evaluator = SttQualityEvaluator(noise_confidence_max=0.20)

    assessment = evaluator.evaluate("muchas ahora", confidence=0.08)

    assert assessment.should_reprompt
    assert not assessment.should_drop_silently
    assert assessment.confidence_band is SttConfidenceBand.NOISE
    assert assessment.reprompt_reason == "ACOUSTIC_NOISE_CONFIDENCE"


def test_real_higher_confidence_alternative_can_rescue_doubtful_primary() -> None:
    evaluator = SttQualityEvaluator(conversation_min_confidence=0.45)

    assessment = evaluator.evaluate(
        "muchas ahora",
        confidence=0.25,
        alternatives=(
            TranscriptAlternative("poné música ahora", 0.67),
            TranscriptAlternative("mucha ahora", 0.28),
        ),
    )

    assert not assessment.should_reprompt
    assert assessment.cleaned_text == "poné música ahora"
    assert assessment.acoustic_confidence == 0.67
    assert assessment.selected_alternative
    assert assessment.confidence_band is SttConfidenceBand.CONVERSATION


def test_missing_engine_confidence_remains_unknown_not_fabricated() -> None:
    evaluator = SttQualityEvaluator()

    assessment = evaluator.evaluate("recién terminé de comer", confidence=None)

    assert not assessment.should_reprompt
    assert assessment.acoustic_confidence is None
    assert assessment.confidence_band is SttConfidenceBand.UNKNOWN

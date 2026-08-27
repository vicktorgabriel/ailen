"""Unit tests for SttQualityEvaluator and reprompt policy."""

from ailen.audio.stt_quality import SttQualityEvaluator


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


def test_low_confidence_tiny_transcript_is_dropped_silently() -> None:
    evaluator = SttQualityEvaluator()
    assessment = evaluator.evaluate("hola", confidence=0.31)
    assert assessment.should_drop_silently
    assert not assessment.should_reprompt
    assert assessment.reprompt_reason == "LOW_CONFIDENCE_NOISE"


def test_confident_short_conversation_remains_valid() -> None:
    evaluator = SttQualityEvaluator()
    for text in ("sí", "no", "hola", "dale"):
        assessment = evaluator.evaluate(text, confidence=0.91)
        assert not assessment.should_drop_silently, text
        assert not assessment.should_reprompt, text


def test_low_confidence_longer_speech_is_dropped_only_when_very_uncertain() -> None:
    evaluator = SttQualityEvaluator()
    assert evaluator.evaluate("hola como estas", confidence=0.25).should_drop_silently
    usable = evaluator.evaluate("hola como estas", confidence=0.58)
    assert not usable.should_drop_silently
    assert not usable.should_reprompt

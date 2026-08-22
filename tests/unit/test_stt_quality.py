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

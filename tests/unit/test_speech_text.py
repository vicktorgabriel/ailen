"""Tests for text normalization before TTS."""

from ailen.audio.speech_text import (
    IncrementalSpeechSegmenter,
    normalize_text_for_speech,
    smooth_speech_pacing,
    split_speech_for_streaming,
)


def test_speech_text_strips_markdown_urls_and_symbol_noise() -> None:
    raw = "## **Hola** [manual](https://example.com) ```x = 1``` !!! *** ///"
    spoken = normalize_text_for_speech(raw)
    assert "**" not in spoken
    assert "```" not in spoken
    assert "https://" not in spoken
    assert "manual" in spoken
    assert "código omitido" in spoken


def test_speech_text_keeps_plain_spanish() -> None:
    text = "Hola, ¿cómo estás? Todo funciona bien."
    assert normalize_text_for_speech(text) == text


def test_smooth_speech_pacing_merges_short_lead() -> None:
    assert (
        smooth_speech_pacing("Che, sí. Ahora te escucho mejor.")
        == "Che, sí, ahora te escucho mejor."
    )


def test_smooth_speech_pacing_preserves_normal_or_expressive_openers() -> None:
    assert smooth_speech_pacing("Esta oración ya es suficientemente larga. Sigue otra.") == (
        "Esta oración ya es suficientemente larga. Sigue otra."
    )
    assert smooth_speech_pacing("¿En serio? Eso cambia todo.") == "¿En serio? Eso cambia todo."


def test_split_speech_for_streaming_bounds_long_sentence() -> None:
    text = (
        "Che, hoy terminé algo que me venía costando bastante, y al final encontré "
        "una solución sencilla que no había visto antes porque estaba demasiado concentrado."
    )
    chunks = split_speech_for_streaming(text, min_chars=24, max_chars=72)
    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)
    assert max(len(chunk) for chunk in chunks) <= 85
    assert " ".join(chunks).replace("  ", " ")


def test_split_speech_for_streaming_avoids_tiny_tail() -> None:
    chunks = split_speech_for_streaming(
        "Esto es una frase suficientemente larga para hablar. Sí.",
        min_chars=20,
        max_chars=60,
    )
    assert len(chunks[-1]) >= 20


def test_incremental_segmenter_emits_complete_phrase_without_waiting_for_full_reply() -> None:
    segmenter = IncrementalSpeechSegmenter(min_chars=20, max_chars=80)

    assert segmenter.feed("Esta frase ya puede empezar a sonar.") == [
        "Esta frase ya puede empezar a sonar."
    ]
    assert segmenter.feed(" La respuesta sigue") == []
    assert segmenter.finish() == ["La respuesta sigue"]


def test_incremental_segmenter_merges_short_opener_and_never_speaks_face_metadata() -> None:
    segmenter = IncrementalSpeechSegmenter(min_chars=18, max_chars=80)

    assert segmenter.feed("[[face:happy]] Sí.") == []
    assert segmenter.feed(" Me alegra mucho verte.") == ["Sí, me alegra mucho verte."]
    assert segmenter.finish() == []

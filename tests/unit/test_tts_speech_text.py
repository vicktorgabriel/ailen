"""Unit tests for TTS speech text normalization and sentence chunking."""

from ailen.audio.speech_text import normalize_text_for_speech, split_speech_into_sentences


def test_markdown_and_symbols_cleaning() -> None:
    raw = (
        "# Título Principal\n\n"
        "Hola **usuario**, mirá este enlace: https://example.com/test.\n"
        "Aquí hay código: `def foo(): pass` y un bloque:\n"
        "```python\nprint('hola')\n```\n"
        "- Lista 1\n- Lista 2\n"
        "¡Qué lindo día! 🚀✨"
    )
    clean = normalize_text_for_speech(raw)

    assert "#" not in clean
    assert "**" not in clean
    assert "https://" not in clean
    assert "print('hola')" not in clean
    assert "def foo()" not in clean
    assert "🚀" not in clean
    assert "✨" not in clean
    assert "Hola usuario" in clean
    assert "Qué lindo día" in clean


def test_split_speech_into_sentences() -> None:
    text = "Hola, soy AILEN. Estoy lista para ayudarte con tus tareas. ¿Qué necesitás hoy?"
    chunks = split_speech_into_sentences(text)
    assert len(chunks) == 3
    assert "Hola, soy AILEN." in chunks[0]
    assert "Estoy lista para ayudarte con tus tareas." in chunks[1]
    assert "¿Qué necesitás hoy?" in chunks[2]

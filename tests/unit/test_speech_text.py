"""Tests for text normalization before TTS."""

from ailen.audio.speech_text import normalize_text_for_speech


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

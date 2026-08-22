"""Text normalization and sentence chunking for speech synthesis."""

import re


def normalize_text_for_speech(text: str) -> str:
    """Clean text for Text-to-Speech synthesis without altering original AI response text.

    Removes:
    - Markdown headings, bold, italics, tables, and blockquotes.
    - Code fences and inline code blocks.
    - Raw web URLs.
    - Decorative emojis and non-speech symbols.
    """
    if not text:
        return ""

    cleaned = text

    # 1. Replace markdown links [label](url) with label
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)

    # 2. Replace code blocks ```...``` with "código omitido"
    cleaned = re.sub(r"```[\s\S]*?```", " código omitido ", cleaned)
    cleaned = re.sub(r"`[^`]*?`", " ", cleaned)

    # 3. Remove URLs
    cleaned = re.sub(r"https?://\S+", " ", cleaned)

    # 4. Remove Markdown headings (# Heading)
    cleaned = re.sub(r"^#{1,6}\s+", " ", cleaned, flags=re.MULTILINE)

    # 5. Remove Markdown list bullets (- item, * item, 1. item)
    cleaned = re.sub(r"^\s*[-*+]\s+", " ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", " ", cleaned, flags=re.MULTILINE)

    # 6. Remove blockquotes (> quote) and table pipes (|)
    cleaned = re.sub(r"^\s*>\s*", " ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\|", " ", cleaned)

    # 7. Remove bold/italics markers (**bold**, *italic*, __bold__, _italic_)
    cleaned = re.sub(r"[*_]{1,3}", "", cleaned)

    # 8. Strip emojis and decorative symbols while preserving Spanish accents and punctuation
    cleaned = re.sub(r"[^\w\s.,!?:;áéíóúÁÉÍÓÚñÑüÜ¿¡/-]", " ", cleaned)

    # 9. Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def split_speech_into_sentences(text: str, min_sentence_chars: int = 10) -> list[str]:
    """Split text into sentence chunks for incremental vocal synthesis."""
    clean = normalize_text_for_speech(text)
    if not clean:
        return []

    # Split on sentence boundaries: . ! ? ; : or newlines
    raw_sentences = re.split(r"(?<=[.!?¿¡;:])\s+", clean)
    chunks: list[str] = []
    current = ""

    for s in raw_sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        if len(current) + len(s_clean) < min_sentence_chars and chunks:
            current = f"{current} {s_clean}"
        else:
            if current:
                chunks.append(current)
            current = s_clean

    if current:
        chunks.append(current)

    return chunks if chunks else ([clean] if clean else [])

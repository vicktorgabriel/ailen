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


def smooth_speech_pacing(text: str, max_lead_chars: int = 18) -> str:
    """Merge an unusually short opening sentence into the next spoken phrase.

    TTS engines often emit one audio chunk per sentence. A tiny opener such as
    ``"Sí."`` or ``"Che, sí."`` can therefore create a robotic mid-turn gap on
    slower CPUs. This is a speech-only prosody transform; the displayed AI text
    remains unchanged.
    """
    if not text or max_lead_chars < 1:
        return text
    match = re.match(rf"^(.{{1,{max_lead_chars}}}?)\.\s+(.+)$", text)
    if not match:
        return text
    lead = match.group(1).strip()
    rest = match.group(2).strip()
    if not lead or not rest or any(ch in lead for ch in "?!¿¡"):
        return text
    first = rest[0].lower() + rest[1:] if rest else rest
    return f"{lead}, {first}"


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


def split_speech_for_streaming(
    text: str,
    min_chars: int = 28,
    max_chars: int = 64,
) -> list[str]:
    """Split spoken text into natural, bounded phrases for low-latency TTS.

    The chunker packs words up to a small latency budget, prefers punctuation
    boundaries, and avoids tiny lead/tail fragments. This lets a slow CPU
    synthesize the next phrase while the current one is playing.
    """
    clean = smooth_speech_pacing(normalize_text_for_speech(text))
    if not clean:
        return []
    min_chars = max(8, min(min_chars, max_chars))
    max_chars = max(min_chars, max_chars)

    words = clean.split()
    chunks: list[str] = []
    current: list[str] = []
    last_soft_boundary = -1

    def current_text(items: list[str] | None = None) -> str:
        return " ".join(current if items is None else items).strip()

    def flush(items: list[str]) -> None:
        text_chunk = current_text(items)
        if text_chunk:
            chunks.append(text_chunk)

    index = 0
    while index < len(words):
        word = words[index]
        candidate = current + [word]
        candidate_text = current_text(candidate)
        if not current or len(candidate_text) <= max_chars:
            current.append(word)
            if word[-1:] in ",;:":
                last_soft_boundary = len(current)
            if word[-1:] in ".!?" and len(current_text()) >= min_chars:
                flush(current)
                current = []
                last_soft_boundary = -1
            index += 1
            continue

        # If a useful comma/semicolon boundary exists, cut there and retain the
        # remainder so a short introduction is never emitted on its own.
        if last_soft_boundary > 0:
            left = current[:last_soft_boundary]
            right = current[last_soft_boundary:]
            if len(current_text(left)) >= min_chars:
                flush(left)
                current = right
                last_soft_boundary = -1
                for pos, item in enumerate(current, start=1):
                    if item[-1:] in ",;:":
                        last_soft_boundary = pos
                continue

        # Otherwise the current word-packed phrase is already large enough.
        if len(current_text()) >= min_chars:
            flush(current)
            current = []
            last_soft_boundary = -1
            continue

        # Rare long-word/short-lead case: accept one oversized phrase rather
        # than generating a tiny robotic chunk.
        current.append(word)
        index += 1

    if current:
        flush(current)

    # Merge a short tail into the previous phrase when it remains reasonable.
    if len(chunks) >= 2 and len(chunks[-1]) < min_chars:
        tail = chunks.pop()
        chunks[-1] = f"{chunks[-1]} {tail}"
    return chunks

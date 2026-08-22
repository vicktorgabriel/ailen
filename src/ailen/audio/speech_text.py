"""Normalization of assistant text before local text-to-speech playback."""

import re

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_MARKDOWN_PREFIX_RE = re.compile(r"(?m)^\s*(?:#{1,6}|[-*+]\s+|>+\s*|\d+[.)]\s+)")
_DECORATION_RE = re.compile(r"[*_~#|]+")
_SYMBOL_RUN_RE = re.compile(r"([^\w\s.,;:!?¿¡áéíóúüñÁÉÍÓÚÜÑ()%-])\1+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text_for_speech(text: str) -> str:
    """Return a speech-friendly rendering without Markdown/control decoration.

    The original model response remains untouched for logs/UI. This function is
    only for TTS so URLs, code fences and decorative symbol runs are not read
    aloud as noise.
    """
    if not text:
        return ""
    value = _FENCED_CODE_RE.sub(" código omitido ", text)
    value = _LINK_RE.sub(r"\1", value)
    value = _URL_RE.sub(" enlace ", value)
    value = _INLINE_CODE_RE.sub(r"\1", value)
    value = _MARKDOWN_PREFIX_RE.sub("", value)
    value = _DECORATION_RE.sub("", value)
    value = _SYMBOL_RUN_RE.sub(r"\1", value)
    return _WHITESPACE_RE.sub(" ", value).strip()

"""Helpers for isolating user-facing Harmony response channels."""

CHANNEL_MARKER = "<|channel|>"
MESSAGE_MARKER = "<|message|>"
CONSTRAIN_MARKER = "<|constrain|>"
END_MARKERS = ("<|end|>", "<|return|>")


class HarmonyStreamFilter:
    """Incrementally expose plain text or the ``final`` Harmony channel only.

    Harmony headers/body boundaries may be split across transport chunks. The
    filter retains marker-sized tails and never emits content while the active
    channel is ``analysis`` or ``commentary``.
    """

    _MAX_MARKER_LENGTH = max(map(len, (CHANNEL_MARKER, MESSAGE_MARKER, *END_MARKERS)))

    def __init__(self) -> None:
        self._buffer = ""
        self._channel: str | None = None
        self._awaiting_header = False

    def feed(self, chunk: str) -> str:
        """Return only currently safe text from one stream chunk."""
        if not isinstance(chunk, str) or not chunk:
            return ""
        self._buffer += chunk
        return self._drain(final=False)

    def finish(self) -> str:
        """Flush a final-channel/plain-text tail; incomplete headers are dropped."""
        return self._drain(final=True)

    def _drain(self, *, final: bool) -> str:
        output: list[str] = []
        while self._buffer:
            if self._awaiting_header:
                message_at = self._buffer.find(MESSAGE_MARKER)
                next_channel = self._buffer.find(CHANNEL_MARKER)
                if message_at < 0 or (next_channel >= 0 and next_channel < message_at):
                    if final:
                        self._buffer = ""
                        self._awaiting_header = False
                    break
                header = self._buffer[:message_at]
                constrain_at = header.find(CONSTRAIN_MARKER)
                if constrain_at >= 0:
                    header = header[:constrain_at]
                normalized = header.strip().split(maxsplit=1)
                self._channel = normalized[0] if normalized else ""
                self._buffer = self._buffer[message_at + len(MESSAGE_MARKER):]
                self._awaiting_header = False
                continue

            markers = [(self._buffer.find(CHANNEL_MARKER), CHANNEL_MARKER)]
            markers.extend((self._buffer.find(marker), marker) for marker in END_MARKERS)
            positions = [(position, marker) for position, marker in markers if position >= 0]
            if positions:
                marker_at, marker = min(positions, key=lambda item: item[0])
                prefix = self._buffer[:marker_at]
                if self._channel in (None, "final"):
                    output.append(prefix)
                self._buffer = self._buffer[marker_at + len(marker):]
                if marker == CHANNEL_MARKER:
                    self._awaiting_header = True
                else:
                    self._channel = ""
                continue

            if final:
                if self._channel in (None, "final") and not self._awaiting_header:
                    output.append(self._buffer)
                self._buffer = ""
                break

            safe_length = len(self._buffer) - self._pending_marker_suffix_length()
            if safe_length:
                if self._channel in (None, "final"):
                    output.append(self._buffer[:safe_length])
                self._buffer = self._buffer[safe_length:]
            break
        return "".join(output)

    def _pending_marker_suffix_length(self) -> int:
        markers = (CHANNEL_MARKER, MESSAGE_MARKER, *END_MARKERS)
        return max(
            (
                size
                for marker in markers
                for size in range(1, min(len(marker), len(self._buffer) + 1))
                if self._buffer.endswith(marker[:size])
            ),
            default=0,
        )


def strip_harmony_channels(text: str) -> str:
    """Return only the last Harmony ``final`` channel, if channel markers exist.

    Plain text from existing OpenAI-compatible providers is returned unchanged.
    When Harmony channel metadata is present, non-final channels are discarded
    so reasoning/commentary cannot reach conversation output or speech.
    """
    if CHANNEL_MARKER not in text:
        return text

    final_contents: list[str] = []
    cursor = 0
    while True:
        channel_start = text.find(CHANNEL_MARKER, cursor)
        if channel_start < 0:
            break
        header_start = channel_start + len(CHANNEL_MARKER)
        message_start = text.find(MESSAGE_MARKER, header_start)
        next_channel = text.find(CHANNEL_MARKER, header_start)
        if message_start < 0 or (next_channel >= 0 and next_channel < message_start):
            cursor = next_channel if next_channel >= 0 else len(text)
            if cursor >= len(text):
                break
            continue

        header = text[header_start:message_start]
        constrain_at = header.find(CONSTRAIN_MARKER)
        if constrain_at >= 0:
            header = header[:constrain_at]
        channel = header.strip().split(maxsplit=1)[0] if header.strip() else ""

        content_start = message_start + len(MESSAGE_MARKER)
        end_positions = [
            position
            for marker in (*END_MARKERS, CHANNEL_MARKER)
            if (position := text.find(marker, content_start)) >= 0
        ]
        content_end = min(end_positions) if end_positions else len(text)
        if channel == "final":
            final_contents.append(text[content_start:content_end].strip())

        cursor = max(content_end, content_start)

    return final_contents[-1] if final_contents else ""

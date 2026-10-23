"""Minimal RFC 6455 WebSocket client and RealtimeSession adapter using Python stdlib.

No external websocket dependencies are used (pyproject.toml declares none).
Supports client frame masking, inbound/outbound fragmentation, ping/pong
control frames, frame and message size limits, socket timeouts, and secret
resolution at connect time via SecretResolver.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import socket
import ssl
import struct
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

from ailen.ai.realtime.contracts import (
    RealtimeEvent,
    RealtimeEventType,
    RealtimeProviderConfig,
)
from ailen.ai.secrets import SecretResolver
from ailen.domain.enums import ErrorCode

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

CONTROL_OPCODES = frozenset({OPCODE_CLOSE, OPCODE_PING, OPCODE_PONG})
DATA_OPCODES = frozenset({OPCODE_TEXT, OPCODE_BINARY})
RESERVED_CLOSE_CODES = frozenset({1004, 1005, 1006, 1015})
MAX_HANDSHAKE_HEADER_BYTES = 16_384
DEFAULT_MAX_FRAGMENTS_PER_MESSAGE = 128
DEFAULT_MAX_NO_PROGRESS_FRAMES = 8


class WebSocketError(RuntimeError):
    """Base error for stdlib WebSocket client."""


class WebSocketHandshakeError(WebSocketError):
    """Raised when RFC 6455 HTTP Upgrade handshake fails."""


class WebSocketProtocolError(WebSocketError):
    """Raised on RFC 6455 framing or control frame violations."""


class WebSocketFrameTooLargeError(WebSocketProtocolError):
    """Raised when a frame or reassembled message exceeds configured byte limits."""


class WebSocketClosedError(WebSocketError):
    """Raised when the WebSocket connection has been closed."""

    def __init__(self, code: int = 1000, reason: str = "") -> None:
        super().__init__(f"WebSocket closed (code={code}, reason={reason!r})")
        self.code = code
        self.reason = reason


def compute_accept_key(sec_websocket_key: str) -> str:
    """Compute RFC 6455 Sec-WebSocket-Accept value for a given client key."""
    digest = hashlib.sha1(
        (sec_websocket_key.strip() + WS_GUID).encode("ascii"),
        usedforsecurity=False,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def apply_mask(payload: bytes, mask_key: bytes) -> bytes:
    """XOR-mask or unmask a WebSocket frame payload with a 4-byte key."""
    if len(mask_key) != 4:
        raise ValueError("WebSocket mask_key must be exactly 4 bytes")
    if not payload:
        return b""
    key_repeated = (mask_key * ((len(payload) // 4) + 1))[: len(payload)]
    payload_int = int.from_bytes(payload, byteorder="big")
    mask_int = int.from_bytes(key_repeated, byteorder="big")
    return (payload_int ^ mask_int).to_bytes(len(payload), byteorder="big")


def truncate_utf8_reason(reason: str, max_bytes: int = 123) -> bytes:
    """Encode and truncate a close reason on a valid UTF-8 character boundary."""
    if max_bytes <= 0 or not reason:
        return b""
    raw = reason.encode("utf-8")[:max_bytes]
    return raw.decode("utf-8", errors="ignore").encode("utf-8")


def normalize_close_code(code: int) -> int:
    """Normalize outbound close code so reserved codes (1005/1006/1015) are never sent."""
    if code in RESERVED_CLOSE_CODES:
        return 1000
    if 1000 <= code <= 1014 or 3000 <= code <= 4999:
        return code
    return 1000


def _validate_ssl_context(ctx: ssl.SSLContext) -> None:
    """Ensure injected SSLContext enforces certificate and hostname verification."""
    if not isinstance(ctx, ssl.SSLContext):
        raise TypeError("ssl_context must be an ssl.SSLContext instance")
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
        raise ValueError(
            "Insecure ssl_context rejected: verify_mode must be ssl.CERT_REQUIRED "
            "and check_hostname must be True"
        )


def encode_client_frame(
    opcode: int,
    payload: bytes = b"",
    *,
    fin: bool = True,
    mask_key: bytes | None = None,
) -> bytes:
    """Encode a client-to-server RFC 6455 frame (always masked per §5.3)."""
    if opcode not in (DATA_OPCODES | CONTROL_OPCODES | {OPCODE_CONTINUATION}):
        raise WebSocketProtocolError(f"Unsupported WebSocket opcode: {opcode:#x}")
    if opcode in CONTROL_OPCODES:
        if not fin:
            raise WebSocketProtocolError("Control frames must not be fragmented (FIN=0)")
        if len(payload) > 125:
            raise WebSocketProtocolError("Control frame payload must not exceed 125 bytes")

    first_byte = (0x80 if fin else 0x00) | (opcode & 0x0F)
    length = len(payload)
    mask_bit = 0x80  # Client frames MUST set MASK=1

    header = bytearray([first_byte])
    if length < 126:
        header.append(mask_bit | length)
    elif length <= 0xFFFF:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))

    key = mask_key if mask_key is not None else os.urandom(4)
    if len(key) != 4:
        raise ValueError("mask_key must be 4 bytes")
    header.extend(key)
    masked_payload = apply_mask(payload, key)
    return bytes(header) + masked_payload


class StdlibWebSocketClient:
    """Minimal synchronous RFC 6455 WebSocket client built on socket/ssl."""

    def __init__(
        self,
        url: str,
        *,
        connect_timeout_s: float = 10.0,
        read_timeout_s: float = 30.0,
        max_frame_bytes: int = 262_144,
        max_message_bytes: int = 1_048_576,
        max_fragments_per_message: int = DEFAULT_MAX_FRAGMENTS_PER_MESSAGE,
        max_no_progress_frames: int = DEFAULT_MAX_NO_PROGRESS_FRAMES,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if connect_timeout_s <= 0 or read_timeout_s <= 0:
            raise ValueError("Timeouts must be positive")
        if max_frame_bytes <= 0 or max_message_bytes < max_frame_bytes:
            raise ValueError("Invalid frame/message byte limits")
        if max_fragments_per_message <= 0 or max_no_progress_frames <= 0:
            raise ValueError("Fragment and no-progress limits must be positive")
        if ssl_context is not None:
            _validate_ssl_context(ssl_context)
        self.url = url
        self.connect_timeout_s = connect_timeout_s
        self.read_timeout_s = read_timeout_s
        self.max_frame_bytes = max_frame_bytes
        self.max_message_bytes = max_message_bytes
        self.max_fragments_per_message = max_fragments_per_message
        self.max_no_progress_frames = max_no_progress_frames
        self._ssl_context = ssl_context
        self._sock: socket.socket | None = None
        self._rx_buffer = bytearray()
        self.connected: bool = False
        self.closed: bool = False
        self.pongs_sent: int = 0
        self.pongs_received: int = 0
        self.last_ping_payload: bytes = b""
        self.last_pong_payload: bytes = b""

    def connect(self, extra_headers: dict[str, str] | None = None) -> None:
        """Perform TCP/TLS connection and RFC 6455 HTTP Upgrade handshake."""
        parsed = urlsplit(self.url)
        scheme = parsed.scheme.lower()
        if scheme not in {"ws", "wss"}:
            raise ValueError(f"Unsupported WebSocket scheme: {scheme!r}")
        host = parsed.hostname
        if not host:
            raise ValueError("WebSocket URL is missing hostname")
        port = parsed.port or (443 if scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        raw_sock = socket.create_connection((host, port), timeout=self.connect_timeout_s)
        try:
            if scheme == "wss":
                ctx = self._ssl_context or ssl.create_default_context()
                _validate_ssl_context(ctx)
                sock: socket.socket = ctx.wrap_socket(raw_sock, server_hostname=host)
            else:
                sock = raw_sock

            sec_key = base64.b64encode(os.urandom(16)).decode("ascii")
            host_header = f"{host}:{port}" if parsed.port else host
            request_lines = [
                f"GET {path} HTTP/1.1",
                f"Host: {host_header}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {sec_key}",
                "Sec-WebSocket-Version: 13",
            ]
            if extra_headers:
                for k, v in extra_headers.items():
                    if "\r" in k or "\n" in k or "\r" in v or "\n" in v:
                        raise ValueError("Invalid CR/LF in header")
                    request_lines.append(f"{k}: {v}")
            request_lines.append("")
            request_lines.append("")
            sock.sendall("\r\n".join(request_lines).encode("ascii"))

            self._sock = sock
            self._rx_buffer.clear()
            status_line, headers = self._read_http_response()
            parts = status_line.split(" ", 2)
            if len(parts) < 2 or parts[1] != "101":
                raise WebSocketHandshakeError(
                    f"Expected HTTP 101 Switching Protocols, got: {status_line!r}"
                )
            if headers.get("upgrade", "").lower() != "websocket":
                raise WebSocketHandshakeError("Missing or invalid Upgrade: websocket header")
            if "upgrade" not in headers.get("connection", "").lower():
                raise WebSocketHandshakeError("Missing or invalid Connection: Upgrade header")
            expected_accept = compute_accept_key(sec_key)
            actual_accept = headers.get("sec-websocket-accept", "")
            if actual_accept != expected_accept:
                raise WebSocketHandshakeError("Invalid Sec-WebSocket-Accept header")

            sock.settimeout(self.read_timeout_s)
            self.connected = True
            self.closed = False
        except Exception:
            self._force_close_socket()
            raise

    def _read_http_response(self) -> tuple[str, dict[str, str]]:
        assert self._sock is not None
        while b"\r\n\r\n" not in self._rx_buffer:
            if len(self._rx_buffer) >= MAX_HANDSHAKE_HEADER_BYTES:
                raise WebSocketHandshakeError("HTTP handshake response header too large")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketHandshakeError("Connection closed during WebSocket handshake")
            self._rx_buffer.extend(chunk)

        header_end = self._rx_buffer.index(b"\r\n\r\n")
        raw_headers = bytes(self._rx_buffer[:header_end]).decode("iso-8859-1")
        del self._rx_buffer[: header_end + 4]

        lines = raw_headers.split("\r\n")
        status_line = lines[0]
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, val = line.split(":", 1)
                headers[name.strip().lower()] = val.strip()
        return status_line, headers

    def _read_exact(self, num_bytes: int) -> bytes:
        if self._sock is None:
            raise WebSocketClosedError(1006, "Socket not connected")
        while len(self._rx_buffer) < num_bytes:
            chunk = self._sock.recv(max(4096, num_bytes - len(self._rx_buffer)))
            if not chunk:
                self._force_close_socket()
                raise WebSocketClosedError(1006, "Unexpected EOF while reading frame")
            self._rx_buffer.extend(chunk)
        out = bytes(self._rx_buffer[:num_bytes])
        del self._rx_buffer[:num_bytes]
        return out

    def send_frame(self, opcode: int, payload: bytes = b"", *, fin: bool = True) -> None:
        """Send a single masked client frame."""
        if not self.connected or self.closed or self._sock is None:
            raise WebSocketClosedError(1006, "WebSocket is not connected")
        if len(payload) > self.max_frame_bytes:
            raise WebSocketFrameTooLargeError(
                f"Outbound frame ({len(payload)} B) exceeds max_frame_bytes ({self.max_frame_bytes} B)"
            )
        raw = encode_client_frame(opcode, payload, fin=fin)
        self._sock.sendall(raw)

    def send_fragmented(self, opcode: int, payload: bytes, fragment_size: int) -> None:
        """Send a data message split across multiple RFC 6455 frames."""
        if opcode not in DATA_OPCODES:
            raise WebSocketProtocolError("Only TEXT or BINARY messages can be fragmented")
        if fragment_size <= 0:
            raise ValueError("fragment_size must be positive")
        if len(payload) > self.max_message_bytes:
            raise WebSocketFrameTooLargeError(
                f"Outbound message ({len(payload)} B) exceeds max_message_bytes"
            )
        if not payload:
            self.send_frame(opcode, b"", fin=True)
            return

        chunks = [
            payload[i : i + fragment_size] for i in range(0, len(payload), fragment_size)
        ]
        if len(chunks) == 1:
            self.send_frame(opcode, chunks[0], fin=True)
            return

        self.send_frame(opcode, chunks[0], fin=False)
        for middle in chunks[1:-1]:
            self.send_frame(OPCODE_CONTINUATION, middle, fin=False)
        self.send_frame(OPCODE_CONTINUATION, chunks[-1], fin=True)

    def send_text(self, text: str, *, fragment_size: int | None = None) -> None:
        """Send a UTF-8 text message, optionally fragmented."""
        data = text.encode("utf-8")
        if fragment_size is not None:
            self.send_fragmented(OPCODE_TEXT, data, fragment_size)
        else:
            self.send_frame(OPCODE_TEXT, data, fin=True)

    def send_binary(self, data: bytes, *, fragment_size: int | None = None) -> None:
        """Send a binary message, optionally fragmented."""
        if fragment_size is not None:
            self.send_fragmented(OPCODE_BINARY, data, fragment_size)
        else:
            self.send_frame(OPCODE_BINARY, data, fin=True)

    def ping(self, payload: bytes = b"") -> None:
        """Send a PING control frame."""
        self.send_frame(OPCODE_PING, payload, fin=True)

    def pong(self, payload: bytes = b"") -> None:
        """Send a PONG control frame."""
        self.send_frame(OPCODE_PONG, payload, fin=True)
        self.pongs_sent += 1

    def read_frame(self) -> tuple[bool, int, bytes]:
        """Read a single WebSocket frame, enforcing RFC 6455 server framing rules."""
        first_two = self._read_exact(2)
        b1, b2 = first_two[0], first_two[1]
        fin = bool(b1 & 0x80)
        rsv = b1 & 0x70
        if rsv != 0:
            self.close(1002, "Non-zero RSV bits")
            raise WebSocketProtocolError(f"Non-zero RSV bits received: {rsv:#x}")
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F

        if masked:
            self.close(1002, "Server frame must not be masked")
            raise WebSocketProtocolError("Received masked frame from server (RFC 6455 §5.1)")

        if opcode in CONTROL_OPCODES:
            if not fin:
                self.close(1002, "Fragmented control frame")
                raise WebSocketProtocolError("Received fragmented control frame")
            if length > 125:
                self.close(1002, "Control frame too large")
                raise WebSocketProtocolError("Control frame payload exceeds 125 bytes")

        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]

        if length > self.max_frame_bytes:
            self.close(1009, "Frame exceeds max_frame_bytes", wait_for_peer_s=0.0)
            raise WebSocketFrameTooLargeError(
                f"Inbound frame ({length} B) exceeds max_frame_bytes ({self.max_frame_bytes} B)"
            )

        payload = self._read_exact(length) if length > 0 else b""
        return fin, opcode, payload

    def recv_message(self) -> tuple[int, bytes]:
        """Receive a complete message, reassembling fragments and handling ping/pong."""
        fragmented_opcode: int | None = None
        fragments = bytearray()
        fragment_count = 0
        no_progress_frames = 0

        while True:
            fin, opcode, payload = self.read_frame()

            if opcode == OPCODE_PING:
                no_progress_frames += 1
                if no_progress_frames > self.max_no_progress_frames:
                    self.close(1002, "Too many frames without progress")
                    raise WebSocketProtocolError("Exceeded maximum frames without progress")
                self.last_ping_payload = payload
                self.pong(payload)
                continue

            if opcode == OPCODE_PONG:
                no_progress_frames += 1
                if no_progress_frames > self.max_no_progress_frames:
                    self.close(1002, "Too many frames without progress")
                    raise WebSocketProtocolError("Exceeded maximum frames without progress")
                self.last_pong_payload = payload
                self.pongs_received += 1
                continue

            if opcode == OPCODE_CLOSE:
                code = 1000
                reason = ""
                if len(payload) == 1:
                    self.close(1002, "Invalid close payload length", wait_for_peer_s=0.0)
                    raise WebSocketProtocolError("CLOSE frame payload length cannot be 1 byte")
                if len(payload) >= 2:
                    code = struct.unpack("!H", payload[:2])[0]
                    reason = payload[2:].decode("utf-8", errors="replace")
                if not self.closed and self._sock is not None:
                    try:
                        reply_code = normalize_close_code(code)
                        close_payload = struct.pack("!H", reply_code)
                        self.send_frame(OPCODE_CLOSE, close_payload, fin=True)
                    except Exception:  # noqa: BLE001, S110
                        pass
                self._force_close_socket()
                raise WebSocketClosedError(code, reason)

            if opcode in DATA_OPCODES:
                if fragmented_opcode is not None:
                    self.close(1002, "Interleaved data frame")
                    raise WebSocketProtocolError(
                        "Received new data frame before fragmented message completed"
                    )
                if fin:
                    if len(payload) > self.max_message_bytes:
                        self.close(1009, "Message too large", wait_for_peer_s=0.0)
                        raise WebSocketFrameTooLargeError(
                            "Message exceeds max_message_bytes"
                        )
                    return opcode, payload
                fragmented_opcode = opcode
                fragment_count = 1
                if fragment_count > self.max_fragments_per_message:
                    self.close(1002, "Too many message fragments")
                    raise WebSocketProtocolError("Exceeded max_fragments_per_message")
                if not payload:
                    no_progress_frames += 1
                    if no_progress_frames > self.max_no_progress_frames:
                        self.close(1002, "Too many empty fragments")
                        raise WebSocketProtocolError("Exceeded maximum frames without progress")
                else:
                    no_progress_frames = 0
                fragments.extend(payload)
                if len(fragments) > self.max_message_bytes:
                    self.close(1009, "Fragmented message too large", wait_for_peer_s=0.0)
                    raise WebSocketFrameTooLargeError(
                        f"Fragmented message exceeds max_message_bytes ({self.max_message_bytes} B)"
                    )
                continue

            if opcode == OPCODE_CONTINUATION:
                if fragmented_opcode is None:
                    self.close(1002, "Unexpected continuation frame")
                    raise WebSocketProtocolError(
                        "Received continuation frame with no fragmented message in progress"
                    )
                fragment_count += 1
                if fragment_count > self.max_fragments_per_message:
                    self.close(1002, "Too many message fragments")
                    raise WebSocketProtocolError(
                        f"Fragment count ({fragment_count}) exceeds max_fragments_per_message"
                    )
                if not payload and not fin:
                    no_progress_frames += 1
                    if no_progress_frames > self.max_no_progress_frames:
                        self.close(1002, "Too many empty continuation frames")
                        raise WebSocketProtocolError(
                            "Exceeded maximum empty continuation frames without progress"
                        )
                elif payload:
                    no_progress_frames = 0
                fragments.extend(payload)
                if len(fragments) > self.max_message_bytes:
                    self.close(1009, "Fragmented message too large", wait_for_peer_s=0.0)
                    raise WebSocketFrameTooLargeError(
                        f"Fragmented message exceeds max_message_bytes ({self.max_message_bytes} B)"
                    )
                if fin:
                    completed_opcode = fragmented_opcode
                    data = bytes(fragments)
                    return completed_opcode, data
                continue

            self.close(1002, "Unknown opcode")
            raise WebSocketProtocolError(f"Unknown WebSocket opcode: {opcode:#x}")

    def close(
        self,
        code: int = 1000,
        reason: str = "",
        *,
        wait_for_peer_s: float = 0.05,
    ) -> None:
        """Send a CLOSE control frame, wait briefly for peer CLOSE, and close socket."""
        if self.closed:
            return
        sock = self._sock
        if self.connected and sock is not None:
            safe_code = normalize_close_code(code)
            reason_bytes = truncate_utf8_reason(reason, 123)
            try:
                payload = struct.pack("!H", safe_code) + reason_bytes
                self.send_frame(OPCODE_CLOSE, payload, fin=True)
            except Exception:  # noqa: BLE001
                self._force_close_socket()
                return

            if wait_for_peer_s > 0:
                try:
                    sock.settimeout(min(wait_for_peer_s, self.read_timeout_s))
                    for _ in range(4):
                        first_two = self._read_exact(2)
                        b1, b2 = first_two[0], first_two[1]
                        opcode = b1 & 0x0F
                        masked = bool(b2 & 0x80)
                        length = b2 & 0x7F
                        if length == 126:
                            length = struct.unpack("!H", self._read_exact(2))[0]
                        elif length == 127:
                            length = struct.unpack("!Q", self._read_exact(8))[0]
                        if masked:
                            self._read_exact(4)
                        if length > 0 and length <= self.max_frame_bytes:
                            self._read_exact(length)
                        if opcode == OPCODE_CLOSE:
                            break
                except Exception:  # noqa: BLE001, S110
                    pass
        self._force_close_socket()

    def _force_close_socket(self) -> None:
        self.closed = True
        self.connected = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:  # noqa: BLE001, S110
                pass
            self._sock = None


class WebSocketRealtimeSession:
    """RealtimeSession adapter backed by StdlibWebSocketClient."""

    def __init__(
        self,
        config: RealtimeProviderConfig,
        secret_resolver: SecretResolver,
        *,
        require_secret: bool = True,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.config = config
        self._secret_resolver = secret_resolver
        self._require_secret = require_secret
        self.cancelled: bool = False
        self.cancel_count: int = 0
        self._dropping_cancelled_audio: bool = False
        self._ws = StdlibWebSocketClient(
            config.endpoint,
            connect_timeout_s=config.connect_timeout_s,
            read_timeout_s=config.read_timeout_s,
            max_frame_bytes=config.max_frame_bytes,
            max_message_bytes=config.max_message_bytes,
            ssl_context=ssl_context,
        )

    @property
    def ws(self) -> StdlibWebSocketClient:
        """Underlying WebSocket client."""
        return self._ws

    def connect(self) -> None:
        """Resolve secret via SecretResolver and open the WebSocket session."""
        secret = self.config.resolve_secret(self._secret_resolver)
        if self._require_secret and not secret:
            raise PermissionError(
                f"API key not available for realtime provider '{self.config.provider_id}'"
            )
        headers: dict[str, str] = {
            "X-AILEN-Realtime-Model": self.config.model,
        }
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        self._ws.connect(extra_headers=headers)

    def send_audio(self, pcm16le_16k_mono: bytes) -> None:
        """Send PCM16LE 16 kHz mono audio frame to the realtime endpoint."""
        if len(pcm16le_16k_mono) % 2 != 0:
            raise ValueError("PCM16LE audio chunk byte length must be even")
        encoded = base64.b64encode(pcm16le_16k_mono).decode("ascii")
        msg = json.dumps({"type": "audio_in", "audio": encoded})
        self._ws.send_text(msg)

    def send_tool_result(self, call_id: str, result: dict[str, Any]) -> None:
        """Send structured tool execution result back over the WebSocket."""
        msg = json.dumps(
            {
                "type": "tool_result",
                "call_id": call_id,
                "result": result,
            },
            ensure_ascii=False,
        )
        self._ws.send_text(msg)

    def cancel(self) -> None:
        """Send barge-in cancellation and purge outbound audio until a new response starts."""
        if self._ws.connected and not self._ws.closed:
            self.cancelled = True
            self.cancel_count += 1
            self._dropping_cancelled_audio = True
            self._ws.send_text(json.dumps({"type": "cancel"}))

    def close(self) -> None:
        """Close the WebSocket session."""
        self._ws.close()

    def events(self) -> Iterator[RealtimeEvent]:
        """Yield normalized RealtimeEvent items from the WebSocket stream."""
        while not self._ws.closed:
            try:
                opcode, payload = self._ws.recv_message()
            except WebSocketClosedError as exc:
                yield RealtimeEvent.closed(exc.reason or f"code:{exc.code}")
                return
            except TimeoutError:
                yield RealtimeEvent.error_event(
                    "Realtime WebSocket read timed out",
                    error_code=ErrorCode.AI_TIMEOUT,
                )
                self.close()
                yield RealtimeEvent.closed("timeout")
                return
            except WebSocketError as exc:
                yield RealtimeEvent.error_event(
                    str(exc),
                    error_code=ErrorCode.CLOUD_OFFLINE,
                )
                self.close()
                yield RealtimeEvent.closed("ws_error")
                return

            if opcode == OPCODE_BINARY:
                if not payload or len(payload) % 2 != 0:
                    yield RealtimeEvent.error_event(
                        "Invalid binary audio_out frame: empty or odd byte length"
                    )
                    continue
                if self._dropping_cancelled_audio:
                    continue
                yield RealtimeEvent.audio_out(payload)
                continue

            try:
                text = payload.decode("utf-8")
                data = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._ws.close(1007, "Invalid UTF-8 or JSON payload")
                yield RealtimeEvent.error_event(f"Invalid realtime JSON payload: {exc}")
                return

            try:
                event = self._parse_json_event(data)
            except Exception as exc:  # noqa: BLE001
                event = RealtimeEvent.error_event(f"Malformed realtime event: {exc}")

            if self._dropping_cancelled_audio:
                if event.type == RealtimeEventType.AUDIO_OUT:
                    continue
                if event.type in {
                    RealtimeEventType.TRANSCRIPT_PARTIAL,
                    RealtimeEventType.TRANSCRIPT_FINAL,
                    RealtimeEventType.TOOL_CALL,
                }:
                    self._dropping_cancelled_audio = False

            yield event
            if event.type == RealtimeEventType.CLOSED:
                self.close()
                return

    @staticmethod
    def _parse_json_event(data: Any) -> RealtimeEvent:
        if not isinstance(data, dict):
            return RealtimeEvent.error_event(
                "Invalid realtime event payload: expected JSON object"
            )
        raw_type_val = data.get("type", "")
        raw_type = str(raw_type_val) if raw_type_val is not None else ""
        if raw_type == RealtimeEventType.AUDIO_OUT.value:
            raw_b64 = data.get("audio")
            if not isinstance(raw_b64, str) or not raw_b64.strip():
                return RealtimeEvent.error_event(
                    "Invalid audio_out payload: missing or non-string base64 audio"
                )
            try:
                pcm = base64.b64decode(raw_b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                return RealtimeEvent.error_event(
                    f"Invalid base64 audio_out payload: {exc}"
                )
            if not pcm or len(pcm) % 2 != 0:
                return RealtimeEvent.error_event(
                    "Invalid audio_out payload: decoded PCM must be non-empty with even byte length"
                )
            return RealtimeEvent.audio_out(pcm)
        if raw_type == RealtimeEventType.TRANSCRIPT_PARTIAL.value:
            return RealtimeEvent.transcript_partial(str(data.get("text", "")))
        if raw_type == RealtimeEventType.TRANSCRIPT_FINAL.value:
            return RealtimeEvent.transcript_final(str(data.get("text", "")))
        if raw_type == RealtimeEventType.TOOL_CALL.value:
            args = data.get("args")
            return RealtimeEvent.tool_call(
                name=str(data.get("name", "")),
                args=args if isinstance(args, dict) else {},
                call_id=str(data.get("call_id", "")),
            )
        if raw_type == RealtimeEventType.CLOSED.value:
            return RealtimeEvent.closed(str(data.get("reason", "")))
        if raw_type == RealtimeEventType.ERROR.value:
            return RealtimeEvent.error_event(str(data.get("error", "provider_error")))
        return RealtimeEvent.error_event(f"Unsupported realtime event type: {raw_type}")

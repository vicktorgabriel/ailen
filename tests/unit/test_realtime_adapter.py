"""Unit tests for ADR-015 realtime voice provider base adapter, bridge, and WS client."""

from __future__ import annotations

import base64
import json
import socket
import ssl
import struct
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from ailen.ai.realtime import (
    MAX_OUTBOUND_TOOL_TEXT_CHARS,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_CONTINUATION,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    PRIVATE_RESULT_TEXT,
    BudgetGuard,
    FakeRealtimeSession,
    RealtimeBudgetExceededError,
    RealtimeEvent,
    RealtimeEventType,
    RealtimePrivacyError,
    RealtimeProviderConfig,
    RealtimeSession,
    RealtimeToolBridge,
    StdlibWebSocketClient,
    WebSocketFrameTooLargeError,
    WebSocketHandshakeError,
    WebSocketProtocolError,
    WebSocketRealtimeSession,
    apply_mask,
    compute_accept_key,
    normalize_close_code,
    truncate_utf8_reason,
)
from ailen.ai.secrets import SecretResolver
from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ALL_SOCIAL_MODES, AutonomyLevel, ToolContext, ToolResult
from ailen.tools.executor import ToolExecutor
from ailen.tools.registry import ToolRegistry


def _encode_server_frame(
    opcode: int,
    payload: bytes = b"",
    *,
    fin: bool = True,
    masked: bool = False,
) -> bytes:
    """Encode a server-to-client RFC 6455 frame for local test server."""
    b1 = (0x80 if fin else 0x00) | (opcode & 0x0F)
    mask_bit = 0x80 if masked else 0x00
    length = len(payload)
    header = bytearray([b1])
    if length < 126:
        header.append(mask_bit | length)
    elif length <= 0xFFFF:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))
    if masked:
        key = b"\x12\x34\x56\x78"
        header.extend(key)
        return bytes(header) + apply_mask(payload, key)
    return bytes(header) + payload


def _read_client_frame(conn: socket.socket) -> tuple[bool, int, bool, bytes]:
    """Read a single client-to-server frame on the local test server."""

    def recv_exact(n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise EOFError("Client socket closed")
            buf.extend(chunk)
        return bytes(buf)

    b1, b2 = recv_exact(2)
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(8))[0]
    mask_key = recv_exact(4) if masked else b""
    payload = recv_exact(length) if length > 0 else b""
    if masked and payload:
        payload = apply_mask(payload, mask_key)
    return fin, opcode, masked, payload


def _complete_server_handshake(conn: socket.socket) -> dict[str, str]:
    """Read HTTP Upgrade request and reply with 101 Switching Protocols."""
    raw = bytearray()
    while b"\r\n\r\n" not in raw:
        chunk = conn.recv(4096)
        if not chunk:
            raise EOFError("Handshake aborted")
        raw.extend(chunk)
    header_text = bytes(raw).decode("iso-8859-1")
    headers: dict[str, str] = {}
    for line in header_text.split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    client_key = headers["sec-websocket-key"]
    accept = compute_accept_key(client_key)
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    conn.sendall(response.encode("ascii"))
    return headers


@contextmanager
def _run_local_ws_server(
    handler: Callable[[socket.socket], None],
    *,
    accept_count: int = 1,
) -> Iterator[int]:
    """Run a local TCP WebSocket server thread and re-raise any worker exceptions in main thread."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(accept_count)
    server_sock.settimeout(3.0)
    port = int(server_sock.getsockname()[1])
    worker_errors: list[BaseException] = []

    def server_worker() -> None:
        try:
            for _ in range(accept_count):
                conn, _ = server_sock.accept()
                with conn:
                    conn.settimeout(3.0)
                    handler(conn)
        except BaseException as exc:  # noqa: BLE001
            worker_errors.append(exc)

    thread = threading.Thread(target=server_worker, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        thread.join(timeout=3.0)
        server_sock.close()
        if worker_errors:
            raise worker_errors[0]


class _DummyEchoTool:
    name = "echo_note"
    description = "Echoes text safely"
    privacy_level = PrivacyLevel.PUBLIC
    requires_network = False
    destructive = False
    timeout_seconds = 2.0
    autonomy_level = AutonomyLevel.N1

    def __init__(self) -> None:
        self.schema: dict[str, Any] = {
            "properties": {
                "text": {"type": "str", "required": True, "min_len": 1, "max_len": 100},
            }
        }
        self.permissions: list[str] = []
        self.allowed_modes: set[SocialMode] = set(ALL_SOCIAL_MODES)
        self.calls: list[dict[str, Any]] = []
        self.seen_contexts: list[ToolContext] = []

    def is_side_effecting(self, arguments: dict[str, Any]) -> bool:
        return False

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls.append(dict(validated_args))
        self.seen_contexts.append(context)
        return ToolResult(
            success=True,
            tool_name=self.name,
            message=f"Echo: {validated_args['text']}",
            data={"echo": validated_args["text"], "mode": context.mode.value},
        )


class _DummyPrivateTool(_DummyEchoTool):
    name = "private_vault_lookup"
    privacy_level = PrivacyLevel.PRIVATE

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls.append(dict(validated_args))
        self.seen_contexts.append(context)
        long_msg = "M" * (MAX_OUTBOUND_TOOL_TEXT_CHARS + 200)
        return ToolResult(
            success=True,
            tool_name=self.name,
            message=long_msg,
            summary=long_msg,
            data={"secret_note": "do-not-leak-to-remote-provider"},
        )


class _DummyN2FileTool(_DummyEchoTool):
    name = "scoped_file_write"
    autonomy_level = AutonomyLevel.N2


def test_config_is_secret_free_and_resolves_via_secret_resolver(tmp_path: Path) -> None:
    field_names = {f.name for f in fields(RealtimeProviderConfig)}
    assert "api_key" not in field_names
    assert "secret" not in field_names
    assert "token" not in field_names
    assert "sample_rate_hz" in field_names

    with pytest.raises(ValueError, match="wss://"):
        RealtimeProviderConfig(
            provider_id="openai_rt",
            endpoint="http://example.com/realtime",
            model="gpt-realtime-mini",
        )

    with pytest.raises(ValueError, match="not a raw key"):
        RealtimeProviderConfig(
            provider_id="openai_rt",
            endpoint="wss://example.invalid/v1/realtime",
            model="gpt-realtime-mini",
            secret_env_var="sk-live-1234567890",
        )

    with pytest.raises(ValueError, match="sample_rate_hz"):
        RealtimeProviderConfig(
            provider_id="openai_rt",
            endpoint="wss://example.invalid/v1/realtime",
            model="gpt-realtime-mini",
            sample_rate_hz=0,
        )

    resolver = SecretResolver(secrets_dir=tmp_path)
    resolver.save_secret("openai_rt.key", "test-credential-placeholder-value")
    cfg = RealtimeProviderConfig(
        provider_id="openai_rt",
        endpoint="wss://example.invalid/v1/realtime",
        model="gpt-realtime-mini",
        secret_file_name="openai_rt.key",
    )
    assert cfg.sample_rate_hz == 16_000
    assert cfg.bytes_per_second == 32_000
    assert cfg.route_id == "remote_realtime:openai_rt"
    assert cfg.resolve_secret(resolver) == "test-credential-placeholder-value"


def test_websocket_handshake_fragmented_frames_and_ping_pong() -> None:
    received_by_server: list[tuple[bool, int, bool, bytes]] = []

    def handler(conn: socket.socket) -> None:
        _complete_server_handshake(conn)
        for _ in range(3):
            received_by_server.append(_read_client_frame(conn))
        fin, opcode, masked, ping_data = _read_client_frame(conn)
        assert fin and opcode == OPCODE_PING and masked
        conn.sendall(_encode_server_frame(OPCODE_PONG, ping_data, fin=True))

        conn.sendall(_encode_server_frame(OPCODE_TEXT, b"Hola ", fin=False))
        conn.sendall(_encode_server_frame(OPCODE_PING, b"srv-hb", fin=True))
        conn.sendall(_encode_server_frame(OPCODE_CONTINUATION, b"mundo ", fin=False))
        conn.sendall(_encode_server_frame(OPCODE_CONTINUATION, b"rioplatense", fin=True))
        received_by_server.append(_read_client_frame(conn))

        # Read client's close frame and reply with server close frame
        close_fin, close_op, close_masked, close_payload = _read_client_frame(conn)
        assert close_fin and close_op == OPCODE_CLOSE and close_masked
        conn.sendall(_encode_server_frame(OPCODE_CLOSE, close_payload[:2], fin=True))

    with _run_local_ws_server(handler) as port:
        client = StdlibWebSocketClient(
            f"ws://127.0.0.1:{port}/realtime",
            connect_timeout_s=2.0,
            read_timeout_s=2.0,
        )
        client.connect()
        client.send_text("abcdefghi", fragment_size=3)
        client.ping(b"cli-hb")

        opcode, payload = client.recv_message()
        assert opcode == OPCODE_TEXT
        assert payload.decode("utf-8") == "Hola mundo rioplatense"
        assert client.pongs_received == 1
        assert client.last_pong_payload == b"cli-hb"
        assert client.pongs_sent == 1
        assert client.last_ping_payload == b"srv-hb"
        client.close()

    assert len(received_by_server) == 4
    assert received_by_server[0] == (False, OPCODE_TEXT, True, b"abc")
    assert received_by_server[1] == (False, OPCODE_CONTINUATION, True, b"def")
    assert received_by_server[2] == (True, OPCODE_CONTINUATION, True, b"ghi")
    assert received_by_server[3] == (True, OPCODE_PONG, True, b"srv-hb")


def test_server_masked_frame_rejected_with_protocol_error_and_close_1002() -> None:
    close_frames: list[tuple[int, str]] = []

    def handler(conn: socket.socket) -> None:
        _complete_server_handshake(conn)
        # Send an illegal masked frame from the server (RFC 6455 §5.1 violation)
        conn.sendall(_encode_server_frame(OPCODE_TEXT, b"{}", fin=True, masked=True))
        fin, opcode, masked, payload = _read_client_frame(conn)
        assert fin and opcode == OPCODE_CLOSE and masked
        code = struct.unpack("!H", payload[:2])[0]
        reason = payload[2:].decode("utf-8")
        close_frames.append((code, reason))
        conn.sendall(_encode_server_frame(OPCODE_CLOSE, struct.pack("!H", 1002), fin=True))

    with _run_local_ws_server(handler) as port:
        client = StdlibWebSocketClient(f"ws://127.0.0.1:{port}/rt")
        client.connect()
        with pytest.raises(WebSocketProtocolError, match="masked"):
            client.recv_message()

    assert len(close_frames) == 1
    assert close_frames[0][0] == 1002


def test_non_object_json_and_invalid_base64_emit_error_without_escaping(tmp_path: Path) -> None:
    # Direct unit checks on _parse_json_event
    for non_obj in (None, [1, 2, 3], 42, "plain_string", True):
        ev = WebSocketRealtimeSession._parse_json_event(non_obj)
        assert ev.type == RealtimeEventType.ERROR

    for bad_b64 in ("", "   ", "!!!not-base64!!!", "abc", base64.b64encode(b"\x01").decode()):
        ev = WebSocketRealtimeSession._parse_json_event({"type": "audio_out", "audio": bad_b64})
        assert ev.type == RealtimeEventType.ERROR
        assert ev.audio == b""

    resolver = SecretResolver(secrets_dir=tmp_path)

    def handler(conn: socket.socket) -> None:
        _complete_server_handshake(conn)
        conn.sendall(_encode_server_frame(OPCODE_TEXT, b"null"))
        conn.sendall(_encode_server_frame(OPCODE_TEXT, b"[1, 2]"))
        conn.sendall(_encode_server_frame(OPCODE_TEXT, b"12345"))
        conn.sendall(
            _encode_server_frame(
                OPCODE_TEXT,
                json.dumps({"type": "audio_out", "audio": "@@@invalid@@@"}).encode(),
            )
        )
        conn.sendall(
            _encode_server_frame(
                OPCODE_TEXT,
                json.dumps({"type": "closed", "reason": "done"}).encode(),
            )
        )

    with _run_local_ws_server(handler) as port:
        cfg = RealtimeProviderConfig(
            provider_id="local_mock",
            endpoint=f"ws://127.0.0.1:{port}/rt",
            model="mock",
            allow_insecure_ws_for_testing=True,
        )
        session = WebSocketRealtimeSession(cfg, resolver, require_secret=False)
        session.connect()
        events = list(session.events())

    assert [e.type for e in events] == [
        RealtimeEventType.ERROR,
        RealtimeEventType.ERROR,
        RealtimeEventType.ERROR,
        RealtimeEventType.ERROR,
        RealtimeEventType.CLOSED,
    ]


@pytest.mark.parametrize(
    "bad_payload",
    [
        b"\xff\xfe\xfd",  # invalid UTF-8
        b"{not-valid-json",  # broken JSON
    ],
)
def test_invalid_utf8_or_broken_json_closes_with_1007_and_terminates_stream(
    tmp_path: Path,
    bad_payload: bytes,
) -> None:
    resolver = SecretResolver(secrets_dir=tmp_path)
    received_close_codes: list[int] = []

    def handler(conn: socket.socket) -> None:
        _complete_server_handshake(conn)
        conn.sendall(_encode_server_frame(OPCODE_TEXT, bad_payload, fin=True))
        fin, opcode, masked, payload = _read_client_frame(conn)
        assert fin and opcode == OPCODE_CLOSE and masked
        code = struct.unpack("!H", payload[:2])[0]
        received_close_codes.append(code)
        conn.sendall(_encode_server_frame(OPCODE_CLOSE, struct.pack("!H", code), fin=True))

    with _run_local_ws_server(handler) as port:
        cfg = RealtimeProviderConfig(
            provider_id="local_mock",
            endpoint=f"ws://127.0.0.1:{port}/rt",
            model="mock",
            allow_insecure_ws_for_testing=True,
        )
        session = WebSocketRealtimeSession(cfg, resolver, require_secret=False)
        session.connect()
        events = list(session.events())

    assert len(events) == 1
    assert events[0].type == RealtimeEventType.ERROR
    assert received_close_codes == [1007]


def test_empty_continuation_frames_and_fragment_count_limits() -> None:
    close_codes: list[int] = []

    def handler_empty(conn: socket.socket) -> None:
        _complete_server_handshake(conn)
        conn.sendall(_encode_server_frame(OPCODE_TEXT, b"start", fin=False))
        for _ in range(5):
            conn.sendall(_encode_server_frame(OPCODE_CONTINUATION, b"", fin=False))
        _, op, _, payload = _read_client_frame(conn)
        assert op == OPCODE_CLOSE
        close_codes.append(struct.unpack("!H", payload[:2])[0])
        conn.sendall(_encode_server_frame(OPCODE_CLOSE, payload[:2], fin=True))

    with _run_local_ws_server(handler_empty) as port:
        client = StdlibWebSocketClient(
            f"ws://127.0.0.1:{port}/rt",
            max_no_progress_frames=3,
        )
        client.connect()
        with pytest.raises(WebSocketProtocolError, match="empty continuation"):
            client.recv_message()

    def handler_too_many_fragments(conn: socket.socket) -> None:
        _complete_server_handshake(conn)
        conn.sendall(_encode_server_frame(OPCODE_TEXT, b"a", fin=False))
        for _ in range(4):
            conn.sendall(_encode_server_frame(OPCODE_CONTINUATION, b"b", fin=False))
        _, op, _, payload = _read_client_frame(conn)
        assert op == OPCODE_CLOSE
        close_codes.append(struct.unpack("!H", payload[:2])[0])
        conn.sendall(_encode_server_frame(OPCODE_CLOSE, payload[:2], fin=True))

    with _run_local_ws_server(handler_too_many_fragments) as port:
        client = StdlibWebSocketClient(
            f"ws://127.0.0.1:{port}/rt",
            max_fragments_per_message=3,
        )
        client.connect()
        with pytest.raises(WebSocketProtocolError, match="max_fragments_per_message"):
            client.recv_message()

    assert close_codes == [1002, 1002]


def test_close_multibyte_utf8_truncation_reserved_codes_and_peer_handshake() -> None:
    # 1. Multibyte UTF-8 truncation at <= 123 bytes without splitting codepoints
    multibyte_reason = "a" + ("🙂" * 40)  # 1 + 160 = 161 bytes; 123rd byte is inside an emoji
    truncated = truncate_utf8_reason(multibyte_reason, 123)
    assert len(truncated) <= 123
    assert len(truncated) == 121  # 1 + 30*4 = 121 bytes
    decoded = truncated.decode("utf-8")  # Must not raise UnicodeDecodeError
    assert decoded == "a" + ("🙂" * 30)

    # 2. Reserved close codes normalized
    for reserved in (1004, 1005, 1006, 1015, 999, 5000):
        assert normalize_close_code(reserved) == 1000
    assert normalize_close_code(1000) == 1000
    assert normalize_close_code(1001) == 1001
    assert normalize_close_code(1007) == 1007

    # 3. Live close frame sends normalized code, valid UTF-8 reason, and waits for peer CLOSE
    observed_close: list[tuple[int, str]] = []

    def handler(conn: socket.socket) -> None:
        _complete_server_handshake(conn)
        fin, opcode, masked, payload = _read_client_frame(conn)
        assert fin and opcode == OPCODE_CLOSE and masked
        assert len(payload) <= 125
        code = struct.unpack("!H", payload[:2])[0]
        reason_str = payload[2:].decode("utf-8")
        observed_close.append((code, reason_str))
        conn.sendall(_encode_server_frame(OPCODE_CLOSE, struct.pack("!H", 1000), fin=True))

    with _run_local_ws_server(handler) as port:
        client = StdlibWebSocketClient(f"ws://127.0.0.1:{port}/rt")
        client.connect()
        client.close(code=1006, reason=multibyte_reason, wait_for_peer_s=0.2)

    assert len(observed_close) == 1
    assert observed_close[0][0] == 1000
    assert observed_close[0][1] == "a" + ("🙂" * 30)


def test_insecure_ssl_context_rejected(tmp_path: Path) -> None:
    unverified = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE

    with pytest.raises(ValueError, match="CERT_REQUIRED"):
        StdlibWebSocketClient("wss://example.invalid/rt", ssl_context=unverified)

    no_hostname_ctx = ssl.create_default_context()
    no_hostname_ctx.check_hostname = False
    with pytest.raises(ValueError, match="check_hostname"):
        StdlibWebSocketClient("wss://example.invalid/rt", ssl_context=no_hostname_ctx)

    cfg = RealtimeProviderConfig(
        provider_id="openai_rt",
        endpoint="wss://example.invalid/v1/realtime",
        model="gpt-realtime-mini",
    )
    with pytest.raises(ValueError, match="CERT_REQUIRED"):
        WebSocketRealtimeSession(
            cfg,
            SecretResolver(secrets_dir=tmp_path),
            require_secret=False,
            ssl_context=unverified,
        )


def test_websocket_frame_size_limit_and_bad_handshake() -> None:
    step = 0

    def handler(conn: socket.socket) -> None:
        nonlocal step
        step += 1
        if step == 1:
            conn.recv(4096)
            conn.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: invalidaccept==\r\n\r\n"
            )
        else:
            _complete_server_handshake(conn)
            conn.sendall(_encode_server_frame(OPCODE_BINARY, b"x" * 200, fin=True))

    with _run_local_ws_server(handler, accept_count=2) as port:
        bad_client = StdlibWebSocketClient(f"ws://127.0.0.1:{port}/rt")
        with pytest.raises(WebSocketHandshakeError):
            bad_client.connect()

        limited_client = StdlibWebSocketClient(
            f"ws://127.0.0.1:{port}/rt",
            max_frame_bytes=64,
            max_message_bytes=128,
        )
        limited_client.connect()
        with pytest.raises(WebSocketFrameTooLargeError):
            limited_client.recv_message()


def test_real_and_fake_cancel_purge_buffered_audio_until_new_response(tmp_path: Path) -> None:
    old_audio_1 = b"\x01\x00" * 80
    old_audio_2 = b"\x02\x00" * 80
    new_audio = b"\x03\x00" * 80

    # 1. FakeRealtimeSession behavior
    fake = FakeRealtimeSession(
        scripted_events=[
            RealtimeEvent.audio_out(old_audio_1),
            RealtimeEvent.audio_out(old_audio_2),
            RealtimeEvent.transcript_final("Nueva respuesta"),
            RealtimeEvent.audio_out(new_audio),
            RealtimeEvent.closed("done"),
        ]
    )
    fake.connect()
    fake.cancel()
    fake_events = list(fake.events())
    assert [e.type for e in fake_events] == [
        RealtimeEventType.TRANSCRIPT_FINAL,
        RealtimeEventType.AUDIO_OUT,
        RealtimeEventType.CLOSED,
    ]
    assert fake_events[1].audio == new_audio

    # 2. Real WebSocketRealtimeSession against local server
    resolver = SecretResolver(secrets_dir=tmp_path)
    resolver.save_secret("rt.key", "ephemeral-local-test-cred")
    captured_headers: dict[str, str] = {}
    client_messages: list[dict[str, Any]] = []

    def handler(conn: socket.socket) -> None:
        captured_headers.update(_complete_server_handshake(conn))
        # Read audio_in and cancel from client
        for _ in range(2):
            _, op, masked, data = _read_client_frame(conn)
            assert op == OPCODE_TEXT and masked
            client_messages.append(json.loads(data.decode("utf-8")))
        # Server sends stale AUDIO_OUT from cancelled turn (binary + JSON), then new turn
        conn.sendall(_encode_server_frame(OPCODE_BINARY, old_audio_1))
        conn.sendall(
            _encode_server_frame(
                OPCODE_TEXT,
                json.dumps(
                    {"type": "audio_out", "audio": base64.b64encode(old_audio_2).decode("ascii")}
                ).encode(),
            )
        )
        conn.sendall(
            _encode_server_frame(
                OPCODE_TEXT,
                json.dumps({"type": "transcript_final", "text": "Nueva respuesta"}).encode(),
            )
        )
        conn.sendall(_encode_server_frame(OPCODE_BINARY, new_audio))
        conn.sendall(
            _encode_server_frame(
                OPCODE_TEXT,
                json.dumps({"type": "closed", "reason": "done"}).encode(),
            )
        )

    with _run_local_ws_server(handler) as port:
        cfg = RealtimeProviderConfig(
            provider_id="local_mock",
            endpoint=f"ws://127.0.0.1:{port}/v1/realtime",
            model="mock-rt-v1",
            secret_file_name="rt.key",
            allow_insecure_ws_for_testing=True,
        )
        session = WebSocketRealtimeSession(cfg, resolver)
        assert isinstance(session, RealtimeSession)
        session.connect()
        session.send_audio(b"\x00\x01" * 160)
        session.cancel()
        real_events = list(session.events())
        session.close()

    assert captured_headers.get("authorization") == "Bearer ephemeral-local-test-cred"
    assert [m["type"] for m in client_messages] == ["audio_in", "cancel"]
    assert [e.type for e in real_events] == [e.type for e in fake_events]
    assert real_events[0].text == "Nueva respuesta"
    assert real_events[1].audio == new_audio


def test_bridge_tool_calls_sanitization_and_no_double_execution() -> None:
    echo_tool = _DummyEchoTool()
    private_tool = _DummyPrivateTool()
    n2_tool = _DummyN2FileTool()
    registry = ToolRegistry(tools=[echo_tool, private_tool, n2_tool])
    executor = ToolExecutor(registry=registry)

    fake_session = FakeRealtimeSession(
        scripted_events=[
            RealtimeEvent.transcript_partial("ejecutando..."),
            RealtimeEvent.tool_call("echo_note", {"text": "hola"}, call_id="call-1"),
            RealtimeEvent.tool_call("echo_note", {"text": "hola"}, call_id="call-1"),  # duplicate id
            RealtimeEvent.tool_call("private_vault_lookup", {"text": "clave"}, call_id="call-priv"),
            RealtimeEvent.tool_call("unregistered_shell_tool", {"cmd": "id"}, call_id="call-2"),
            RealtimeEvent.tool_call("echo_note", {"unknown_arg": 123}, call_id="call-3"),
            RealtimeEvent.tool_call("scoped_file_write", {"text": "doc"}, call_id="call-4"),
            RealtimeEvent.closed("finished"),
        ]
    )
    bridge = RealtimeToolBridge(
        session=fake_session,
        executor=executor,
        mode=SocialMode.HOME,
        max_autonomy=AutonomyLevel.N1,
    )
    bridge.connect()
    received = list(bridge.events())

    # TOOL_CALL events must NOT be re-emitted to consumer
    assert [e.type for e in received] == [
        RealtimeEventType.TRANSCRIPT_PARTIAL,
        RealtimeEventType.CLOSED,
    ]
    # Duplicate call-1 was ignored; echo_tool executed only once
    assert echo_tool.calls == [{"text": "hola"}]
    assert private_tool.calls == [{"text": "clave"}]
    assert len(fake_session.tool_results) == 5

    # Public tool includes 'data'
    call_1_id, res_1 = fake_session.tool_results[0]
    assert call_1_id == "call-1"
    assert res_1["success"] is True
    assert res_1["data"]["echo"] == "hola"

    # Private tool omits 'data' and truncates message/summary per OutboundPrivacyPolicy
    call_priv_id, res_priv = fake_session.tool_results[1]
    assert call_priv_id == "call-priv"
    assert res_priv["success"] is True
    assert "data" not in res_priv
    # Tool-authored text of a non-public tool never leaves the device.
    assert res_priv["message"] == PRIVATE_RESULT_TEXT
    assert res_priv["summary"] == PRIVATE_RESULT_TEXT
    assert "M" * 20 not in res_priv["message"]

    # Unknown tool omits 'data'
    call_2_id, res_2 = fake_session.tool_results[2]
    assert call_2_id == "call-2"
    assert res_2["success"] is False
    assert res_2["status_code"] == "UNKNOWN_TOOL"
    assert "data" not in res_2
    assert res_2["error_code"] == ErrorCode.TOOL_NOT_FOUND.value

    call_3_id, res_3 = fake_session.tool_results[3]
    assert call_3_id == "call-3"
    assert res_3["success"] is False
    assert res_3["status_code"] == "INVALID_ARGS"
    assert res_3["error_code"] == ErrorCode.TOOL_ARGS_INVALID.value

    call_4_id, res_4 = fake_session.tool_results[4]
    assert call_4_id == "call-4"
    assert res_4["success"] is False
    assert res_4["status_code"] == "AUTONOMY_DENIED"
    assert res_4["error_code"] == ErrorCode.TOOL_DENIED.value


def test_bridge_live_mode_transition_and_restrictive_context_combination() -> None:
    echo_tool = _DummyEchoTool()
    registry = ToolRegistry(tools=[echo_tool])
    executor = ToolExecutor(registry=registry)
    fake_session = FakeRealtimeSession()

    live_state: dict[str, Any] = {
        "mode": SocialMode.HOME,
        "autonomy": AutonomyLevel.N2,
    }
    base_ctx = ToolContext(
        mode=SocialMode.HOME,
        timeout_seconds=10.0,
        network_access_allowed=True,
        max_autonomy=AutonomyLevel.N2,
    )
    bridge = RealtimeToolBridge(
        session=fake_session,
        executor=executor,
        context=base_ctx,
        mode_provider=lambda: live_state["mode"],
        autonomy_provider=lambda: live_state["autonomy"],
        timeout_seconds=2.5,
        network_access_allowed=False,
    )

    # Private .session and read-only .budget
    with pytest.raises(AttributeError):
        _ = bridge.session  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        bridge.budget = BudgetGuard(max_audio_minutes=10.0)  # type: ignore[misc]
    with pytest.raises(AttributeError):
        bridge.budget.max_seconds = 9999.0  # type: ignore[misc]

    # Most restrictive combination of timeout_seconds and network_access_allowed
    resolved_ctx = bridge.context
    assert resolved_ctx.timeout_seconds == 2.5
    assert resolved_ctx.network_access_allowed is False
    assert resolved_ctx.mode == SocialMode.HOME

    bridge.connect()
    bridge.send_audio(b"\x00\x00" * 100)
    res = bridge.execute("echo_note", {"text": "ok"})
    assert res.success is True

    # Transition live mode to SHOP -> closes session and denies send_audio and execute
    live_state["mode"] = SocialMode.SHOP
    with pytest.raises(RealtimePrivacyError):
        bridge.send_audio(b"\x00\x00" * 100)
    assert fake_session.closed is True

    with pytest.raises(RealtimePrivacyError):
        bridge.execute("echo_note", {"text": "blocked"})


@pytest.mark.parametrize("forbidden_mode", [SocialMode.SHOP, SocialMode.PUBLIC])
def test_bridge_denies_shop_and_public_modes(forbidden_mode: SocialMode) -> None:
    registry = ToolRegistry(tools=[_DummyEchoTool()])
    executor = ToolExecutor(registry=registry)
    fake_session = FakeRealtimeSession()
    bridge = RealtimeToolBridge(
        session=fake_session,
        executor=executor,
        mode=forbidden_mode,
        max_autonomy=AutonomyLevel.N1,
    )
    with pytest.raises(RealtimePrivacyError):
        bridge.connect()
    assert fake_session.connected is False
    assert fake_session.closed is True


def test_budget_guard_sample_rate_and_monotonic_wall_clock() -> None:
    registry = ToolRegistry(tools=[_DummyEchoTool()])
    executor = ToolExecutor(registry=registry)

    # 1. Custom sample rate in RealtimeProviderConfig (24 kHz -> 48,000 B/s)
    cfg_24k = RealtimeProviderConfig(
        provider_id="rt_24k",
        endpoint="wss://example.invalid/v1/realtime",
        model="rt-24k",
        sample_rate_hz=24_000,
    )
    fake_24k = FakeRealtimeSession(config=cfg_24k)
    # 0.05 min = 3.0 seconds = 3 * 48,000 bytes
    bridge_24k = RealtimeToolBridge(
        session=fake_24k,
        executor=executor,
        mode=SocialMode.WORKSHOP,
        max_audio_minutes=0.05,
    )
    assert bridge_24k.budget.sample_rate_hz == 24_000
    assert bridge_24k.budget.bytes_per_second == 48_000
    bridge_24k.connect()

    one_sec_24k = b"\x00\x00" * 24_000  # 48,000 B = 1.0s at 24kHz (would be 1.5s at 16kHz)
    bridge_24k.send_audio(one_sec_24k)
    bridge_24k.send_audio(one_sec_24k)
    assert bridge_24k.budget.audio_seconds == pytest.approx(2.0)
    assert not bridge_24k.budget.exhausted

    with pytest.raises(RealtimeBudgetExceededError):
        bridge_24k.send_audio(one_sec_24k)
    assert bridge_24k.budget.exhausted is True
    assert fake_24k.closed is True

    # 2. Monotonic wall-clock session budget exhaustion even without audio bytes
    now = 100.0
    fake_clock_session = FakeRealtimeSession()
    clock_budget = BudgetGuard(
        max_audio_minutes=0.5,  # 30 seconds
        session=fake_clock_session,
        clock=lambda: now,
    )
    bridge_clock = RealtimeToolBridge(
        session=fake_clock_session,
        executor=executor,
        mode=SocialMode.HOME,
        budget=clock_budget,
    )
    bridge_clock.connect()
    now = 120.0
    bridge_clock.send_audio(b"\x00\x00" * 16)  # tiny audio, 20s elapsed < 30s
    assert not bridge_clock.budget.exhausted

    now = 131.0  # 31s elapsed >= 30s budget
    with pytest.raises(RealtimeBudgetExceededError):
        bridge_clock.send_audio(b"\x00\x00" * 16)
    assert bridge_clock.budget.exhausted is True
    assert fake_clock_session.closed is True

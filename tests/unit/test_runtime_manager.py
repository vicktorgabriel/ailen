"""Unit tests for LocalRuntimeManager detection and health checks."""

import http.server
import json
import socketserver
import threading

from ailen.runtime.contracts import RuntimeStatus
from ailen.runtime.manager import LocalRuntimeManager


def _start_mock_runtime_server(response_data: dict, status_code: int = 200) -> tuple[socketserver.TCPServer, str]:
    class MockHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}/v1"


def test_runtime_manager_healthy_server() -> None:
    server, endpoint = _start_mock_runtime_server({"data": [{"id": "qwen3.5-0.8b"}]})
    try:
        mgr = LocalRuntimeManager()
        health = mgr.check_health(endpoint)
        assert health.status == RuntimeStatus.HEALTHY
        assert health.is_running is True
        assert "1 models loaded" in health.details
    finally:
        server.shutdown()
        server.server_close()


def test_runtime_manager_404_is_degraded_not_healthy() -> None:
    server, endpoint = _start_mock_runtime_server({"error": "not found"}, status_code=404)
    try:
        mgr = LocalRuntimeManager()
        health = mgr.check_health(endpoint)
        # 404 is degraded/reachable but not a healthy OpenAI-compatible models endpoint
        assert health.status == RuntimeStatus.DEGRADED
        assert health.is_running is True
    finally:
        server.shutdown()
        server.server_close()


def test_runtime_manager_unreachable_endpoint() -> None:
    mgr = LocalRuntimeManager()
    health = mgr.check_health("http://127.0.0.1:59999/v1", timeout=0.2)
    assert health.status == RuntimeStatus.UNAVAILABLE
    assert health.is_running is False


def test_runtime_manager_detection_returns_descriptors() -> None:
    mgr = LocalRuntimeManager()
    descriptors = mgr.detect_available_runtimes()
    assert len(descriptors) == 2
    types = [d.runtime_type.value for d in descriptors]
    assert "llama.cpp server" in types
    assert "Ollama" in types

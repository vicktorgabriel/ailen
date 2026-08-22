"""Unit tests for ManagedLlamaRuntime subprocess lifecycle and ownership rules."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ailen.runtime.contracts import RuntimeHealth, RuntimeStatus
from ailen.runtime.managed import ManagedLlamaRuntime


def test_managed_runtime_startup_and_args(tmp_path: Path) -> None:
    fake_model = tmp_path / "model.gguf"
    fake_model.write_bytes(b"GGUF" + b"\x00" * 100)

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 4321

    runtime = ManagedLlamaRuntime()

    with patch.object(runtime, "_find_executable", return_value=("/usr/bin/llama-server", False)), \
         patch("subprocess.Popen", return_value=fake_proc) as mock_popen, \
         patch.object(runtime._runtime_mgr, "check_health", return_value=RuntimeHealth(status=RuntimeStatus.HEALTHY, endpoint="http://127.0.0.1:8080/v1", is_running=True)):

        started = runtime.start(model_path=fake_model, host="127.0.0.1", port=8080, context_size=2048, gpu_layers="all", timeout=1.0)
        assert started is True
        assert runtime.is_running is True
        assert runtime.owned_by_ailen is True
        assert runtime.pid == 4321

        # Verify command arguments
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "/usr/bin/llama-server"
        assert "-m" in cmd and str(fake_model) in cmd
        assert "--host" in cmd and "127.0.0.1" in cmd
        assert "--port" in cmd and "8080" in cmd
        assert "-ngl" in cmd and "all" in cmd


def test_managed_runtime_stop_only_when_owned() -> None:
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 4321

    runtime = ManagedLlamaRuntime()
    runtime._process = fake_proc
    runtime._owned_by_ailen = True

    runtime.stop(timeout=1.0)
    fake_proc.terminate.assert_called_once()
    assert runtime.is_running is False
    assert runtime.owned_by_ailen is False


def test_managed_runtime_does_not_stop_unowned() -> None:
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None

    runtime = ManagedLlamaRuntime()
    runtime._process = fake_proc
    runtime._owned_by_ailen = False  # External runtime

    runtime.stop(timeout=1.0)
    fake_proc.terminate.assert_not_called()


def test_managed_runtime_timeout_stops_owned_process(tmp_path: Path) -> None:
    fake_model = tmp_path / "model.gguf"
    fake_model.write_bytes(b"GGUF")
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 9876

    runtime = ManagedLlamaRuntime()
    unhealthy = RuntimeHealth(
        status=RuntimeStatus.DEGRADED,
        endpoint="http://127.0.0.1:8080/v1",
        is_running=True,
    )
    with patch.object(runtime, "_find_executable", return_value=("/usr/bin/llama-server", False)), \
         patch("subprocess.Popen", return_value=fake_proc), \
         patch.object(runtime._runtime_mgr, "check_health", return_value=unhealthy):
        started = runtime.start(model_path=fake_model, timeout=0.01, model_alias="test-model")

    assert started is False
    fake_proc.terminate.assert_called_once()
    assert runtime.owned_by_ailen is False


def test_managed_runtime_rejects_non_loopback_bind(tmp_path: Path) -> None:
    fake_model = tmp_path / "model.gguf"
    fake_model.write_bytes(b"GGUF")
    runtime = ManagedLlamaRuntime()
    assert runtime.start(model_path=fake_model, host="0.0.0.0") is False

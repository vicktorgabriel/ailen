"""Managed in-process subprocess lifecycle for AILEN-owned llama.cpp runtime."""

import logging
import shutil
import subprocess
import time
from pathlib import Path

from ailen.runtime.contracts import RuntimeStatus
from ailen.runtime.manager import LocalRuntimeManager

logger = logging.getLogger(__name__)


class ManagedLlamaRuntime:
    """Manages an AILEN-owned local llama.cpp server subprocess in Lab Mode."""

    def __init__(self, runtime_manager: LocalRuntimeManager | None = None) -> None:
        self._runtime_mgr = runtime_manager or LocalRuntimeManager()
        self._process: subprocess.Popen[bytes] | None = None
        self._owned_by_ailen = False
        self._endpoint: str | None = None

    @property
    def is_running(self) -> bool:
        """Return True if managed subprocess is actively running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def owned_by_ailen(self) -> bool:
        """Return True if this runtime process was started and is owned by AILEN."""
        return self._owned_by_ailen

    @property
    def pid(self) -> int | None:
        """Return process ID of running runtime, or None."""
        return self._process.pid if self.is_running and self._process else None

    @property
    def endpoint(self) -> str | None:
        """Return HTTP endpoint of active runtime."""
        return self._endpoint

    def _find_executable(self) -> tuple[str, bool] | None:
        """Find llama-server or llama binary. Returns (exe_path, is_subcommand_serve)."""
        exe = shutil.which("llama-server") or shutil.which("llama.cpp")
        if exe:
            return exe, False

        llama_cli = shutil.which("llama")
        if llama_cli:
            return llama_cli, True

        return None

    def start(
        self,
        model_path: str | Path,
        host: str = "127.0.0.1",
        port: int = 8080,
        context_size: int = 2048,
        gpu_layers: int | str = 0,
        model_alias: str | None = None,
        timeout: float = 10.0,
    ) -> bool:
        """Start managed llama.cpp server process and wait for healthy endpoint."""
        if self.is_running:
            logger.info("Managed llama.cpp runtime is already running at PID %s", self.pid)
            return True
        if host not in {"127.0.0.1", "localhost", "::1"}:
            logger.error("Managed Lab runtime must bind to loopback, got %s", host)
            return False
        if not (1 <= port <= 65535) or context_size <= 0 or timeout <= 0:
            logger.error("Invalid managed runtime parameters")
            return False

        model_file = Path(model_path).resolve()
        if not model_file.is_file():
            logger.error("Cannot start llama.cpp runtime: model file not found at %s", model_file)
            return False

        exe_info = self._find_executable()
        if not exe_info:
            logger.error("Cannot start llama.cpp runtime: neither llama-server nor llama binary found")
            return False

        exe_path, is_subcommand = exe_info
        cmd = [exe_path]
        if is_subcommand:
            cmd.append("serve")

        # Arguments: strict loopback binding, port, context, gpu layers
        ngl_val = "all" if str(gpu_layers).lower() == "all" else str(gpu_layers)
        cmd.extend([
            "-m", str(model_file),
            "--host", host,
            "--port", str(port),
            "-c", str(context_size),
            "-ngl", ngl_val,
        ])
        if model_alias:
            cmd.extend(["--alias", model_alias])

        endpoint = f"http://{host}:{port}/v1"
        logger.info("Starting managed llama.cpp runtime: %s", " ".join(cmd))

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            self._owned_by_ailen = True
            self._endpoint = endpoint

            # Wait for health endpoint to become responsive
            start_time = time.time()
            while time.time() - start_time < timeout:
                if not self.is_running:
                    logger.error("Managed llama.cpp server process exited prematurely with code %s", self._process.poll())
                    self._owned_by_ailen = False
                    return False

                health = self._runtime_mgr.check_health(endpoint, timeout=0.5)
                if health.status == RuntimeStatus.HEALTHY:
                    logger.info("Managed llama.cpp runtime ready at %s (PID %s)", endpoint, self.pid)
                    return True

                time.sleep(0.2)

            logger.warning("Managed llama.cpp server did not become healthy within %s s; stopping owned process", timeout)
            self.stop()
            return False

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to spawn managed llama.cpp runtime: %s", exc)
            self._owned_by_ailen = False
            return False

    def stop(self, timeout: float = 3.0) -> None:
        """Gracefully stop managed runtime process if owned by AILEN."""
        if not self._owned_by_ailen or self._process is None:
            return

        if not self.is_running:
            self._process = None
            self._owned_by_ailen = False
            return

        pid = self._process.pid
        logger.info("Stopping AILEN-owned llama.cpp runtime (PID %s)...", pid)

        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning("Runtime PID %s did not terminate in %s s; sending SIGKILL", pid, timeout)
                self._process.kill()
                self._process.wait(timeout=1.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error stopping managed runtime PID %s: %s", pid, exc)
        finally:
            self._process = None
            self._owned_by_ailen = False
            self._endpoint = None

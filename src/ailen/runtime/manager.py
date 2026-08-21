"""Local runtime manager detecting running and available inference engines."""

import json
import shutil
import urllib.error
import urllib.request

from ailen.runtime.contracts import (
    ExternalRuntimeDescriptor,
    RuntimeHealth,
    RuntimeStatus,
    RuntimeType,
)


class LocalRuntimeManager:
    """Detects available decoupled local inference engines (llama.cpp server, Ollama)."""

    def __init__(self) -> None:
        pass

    def check_health(self, endpoint: str, timeout: float = 1.0) -> RuntimeHealth:
        """Check if an OpenAI-compatible HTTP endpoint is responsive and healthy."""
        clean_endpoint = endpoint.rstrip("/")
        test_url = f"{clean_endpoint}/models"

        try:
            req = urllib.request.Request(test_url, headers={"User-Agent": "AILEN-RuntimeManager/0.1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    body = resp.read().decode("utf-8")
                    data = json.loads(body)
                    models = data.get("data", [])
                    model_count = len(models) if isinstance(models, list) else 0
                    return RuntimeHealth(
                        status=RuntimeStatus.HEALTHY,
                        endpoint=clean_endpoint,
                        is_running=True,
                        details=f"Endpoint responsive ({model_count} models loaded)",
                    )
                return RuntimeHealth(
                    status=RuntimeStatus.DEGRADED,
                    endpoint=clean_endpoint,
                    is_running=True,
                    details=f"HTTP {resp.status}",
                )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # 404 means a webserver exists but is not an OpenAI-compatible model runtime endpoint
                return RuntimeHealth(
                    status=RuntimeStatus.DEGRADED,
                    endpoint=clean_endpoint,
                    is_running=True,
                    details="Server reachable but /models returned 404 Not Found",
                )
            return RuntimeHealth(
                status=RuntimeStatus.DEGRADED,
                endpoint=clean_endpoint,
                is_running=False,
                details=f"HTTP {e.code}: {e.reason}",
            )
        except Exception as e:  # noqa: BLE001
            return RuntimeHealth(
                status=RuntimeStatus.UNAVAILABLE,
                endpoint=clean_endpoint,
                is_running=False,
                details=f"Unreachable: {e}",
            )

    def detect_available_runtimes(self) -> list[ExternalRuntimeDescriptor]:
        """Inspect system for common runtime executables and default running endpoints."""
        descriptors: list[ExternalRuntimeDescriptor] = []

        # 1. Probe llama.cpp server binaries: llama-server, llama (llama serve), llama.cpp
        llama_exe = (
            shutil.which("llama-server")
            or shutil.which("llama")
            or shutil.which("llama.cpp")
        )
        llama_health = self.check_health("http://127.0.0.1:8080/v1", timeout=0.5)

        llama_status = RuntimeStatus.UNAVAILABLE
        if llama_health.status == RuntimeStatus.HEALTHY:
            llama_status = RuntimeStatus.HEALTHY
        elif llama_health.is_running:
            llama_status = RuntimeStatus.RUNNING
        elif llama_exe:
            llama_status = RuntimeStatus.INSTALLED

        descriptors.append(
            ExternalRuntimeDescriptor(
                runtime_type=RuntimeType.LLAMA_SERVER,
                executable_path=llama_exe,
                endpoint="http://127.0.0.1:8080/v1",
                is_detected=bool(llama_exe or llama_health.is_running),
                status=llama_status,
                health=llama_health,
            )
        )

        # 2. Probe Ollama
        ollama_exe = shutil.which("ollama")
        ollama_health = self.check_health("http://127.0.0.1:11434/v1", timeout=0.5)

        ollama_status = RuntimeStatus.UNAVAILABLE
        if ollama_health.status == RuntimeStatus.HEALTHY:
            ollama_status = RuntimeStatus.HEALTHY
        elif ollama_health.is_running:
            ollama_status = RuntimeStatus.RUNNING
        elif ollama_exe:
            ollama_status = RuntimeStatus.INSTALLED

        descriptors.append(
            ExternalRuntimeDescriptor(
                runtime_type=RuntimeType.OLLAMA,
                executable_path=ollama_exe,
                endpoint="http://127.0.0.1:11434/v1",
                is_detected=bool(ollama_exe or ollama_health.is_running),
                status=ollama_status,
                health=ollama_health,
            )
        )

        return descriptors

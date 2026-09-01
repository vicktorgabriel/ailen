"""Administrative diagnostics for configured remote APIs and optional local runtimes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ailen.ai.providers import ProviderModelCatalog, ProviderTestResult
from ailen.ai.remote_backend import build_remote_backend
from ailen.ai.secrets import SecretResolver
from ailen.core.config import AILENConfig, RemoteProviderConfig


class RuntimeAuthStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


class RuntimeHealthStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    UNHEALTHY = "unhealthy"
    CLIENT_MISSING = "client_missing"
    DISABLED = "disabled"


@dataclass
class RuntimeDiagnostic:
    provider_id: str
    display_name: str
    installed: bool
    version: str | None = None
    auth_status: RuntimeAuthStatus = RuntimeAuthStatus.UNKNOWN
    health_status: RuntimeHealthStatus = RuntimeHealthStatus.DISABLED
    detail: str = ""
    models: list[str] = field(default_factory=list)
    last_checked: float = field(default_factory=time.time)
    last_test_latency_ms: float | None = None
    last_test_ok: bool | None = None
    last_test_error: str | None = None
    last_test_model: str | None = None
    last_test_time: float | None = None
    ttft_ms: float | None = None


@runtime_checkable
class ExternalProviderRuntime(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    def detect(self) -> bool: ...

    def version(self) -> str | None: ...

    def auth_status(self) -> RuntimeAuthStatus: ...

    def diagnostic(self) -> RuntimeDiagnostic: ...

    def list_models(self) -> list[str]: ...

    def test_connection(self, prompt: str = "Respondé solamente: OK") -> ProviderTestResult: ...


class RemoteApiRuntime:
    """Truthful administrative view of one named remote API configuration."""

    def __init__(
        self,
        provider_id: str,
        config: RemoteProviderConfig,
        *,
        secrets_resolver: SecretResolver | None = None,
    ) -> None:
        self._provider_id = provider_id
        self.config = config
        self.secrets_resolver = secrets_resolver or SecretResolver()

    @property
    def provider_id(self) -> str:
        return f"remote:{self._provider_id}"

    @property
    def display_name(self) -> str:
        return self.config.preset.replace("_", " ").title()

    def detect(self) -> bool:
        return bool(self.config.enabled and self.config.endpoint and self.config.model)

    def version(self) -> str | None:
        return self.config.protocol

    def auth_status(self) -> RuntimeAuthStatus:
        if self.config.auth_mode == "none":
            return RuntimeAuthStatus.NOT_REQUIRED
        if self.secrets_resolver.has_secret(
            env_var=self.config.api_key_env or None,
            file_name=self.config.api_key_file or None,
        ):
            return RuntimeAuthStatus.AUTHENTICATED
        return RuntimeAuthStatus.UNAUTHENTICATED

    def _backend(self):
        key = self.secrets_resolver.resolve(
            env_var=self.config.api_key_env or None,
            file_name=self.config.api_key_file or None,
        )
        return build_remote_backend(self._provider_id, self.config, api_key=key)

    def test_connection(self, prompt: str = "Respondé solamente: OK") -> ProviderTestResult:
        """Run an explicit inference probe; configuration alone is never health."""
        return self._backend().test_connection(prompt=prompt)

    def list_models(self) -> list[str]:
        if self.config.catalog_mode != "live":
            return [self.config.model] if self.config.model else []
        return self._backend().list_models()

    def model_catalog(self) -> ProviderModelCatalog:
        return self._backend().model_catalog()

    def diagnostic(self) -> RuntimeDiagnostic:
        auth = self.auth_status()
        configured = self.detect()
        if not self.config.enabled:
            status = RuntimeHealthStatus.DISABLED
            detail = "Provider disabled by configuration."
        elif self.config.qualification_status == "rejected":
            status = RuntimeHealthStatus.UNHEALTHY
            detail = "Provider is rejected by qualification evidence."
        elif not configured:
            status = RuntimeHealthStatus.DISABLED
            detail = "Endpoint and explicit model are required."
        elif auth is RuntimeAuthStatus.UNAUTHENTICATED:
            status = RuntimeHealthStatus.AUTH_REQUIRED
            detail = "Provider-specific API key is missing."
        else:
            status = RuntimeHealthStatus.DEGRADED
            detail = (
                "Configured but not tested in this process; configuration is not health."
            )
        return RuntimeDiagnostic(
            provider_id=self.provider_id,
            display_name=self.display_name,
            installed=configured,
            version=self.version(),
            auth_status=auth,
            health_status=status,
            detail=detail,
            models=[self.config.model] if self.config.model else [],
        )


class LocalOllamaRuntime:
    """Optional local administrative view; never constructed when local is disabled."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434",
        model: str = "",
    ) -> None:
        self.endpoint = endpoint
        self.model = model

    @property
    def provider_id(self) -> str:
        return "local"

    @property
    def display_name(self) -> str:
        return "Ollama Local"

    def detect(self) -> bool:
        from shutil import which

        return which("ollama") is not None

    def version(self) -> str | None:
        import subprocess
        from shutil import which

        binary = which("ollama")
        if not binary:
            return None
        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return (result.stdout or result.stderr).strip() if result.returncode == 0 else None

    def auth_status(self) -> RuntimeAuthStatus:
        return RuntimeAuthStatus.NOT_REQUIRED

    def list_models(self) -> list[str]:
        from ailen.runtime.inventory import RuntimeModelInventory

        try:
            return RuntimeModelInventory(timeout=3.0).list_models(self.endpoint)
        except Exception:  # noqa: BLE001
            return []

    def test_connection(self, prompt: str = "Respondé solamente: OK") -> ProviderTestResult:
        """Probe the explicitly enabled local runtime without creating hidden fallback."""
        from ailen.ai.contracts import AiRequest, ChatMessage
        from ailen.ai.ollama_backend import OllamaNativeBackend

        started = time.monotonic()
        models = self.list_models()
        model = self.model or (models[0] if models else "")
        if not model:
            return ProviderTestResult(
                ok=False,
                latency_ms=(time.monotonic() - started) * 1000.0,
                error="No installed local model is available.",
            )
        backend = OllamaNativeBackend(
            endpoint=self.endpoint,
            model=model,
            timeout_seconds=10.0,
        )
        response = backend.generate(
            AiRequest(
                request_id="admin-test-local",
                messages=[ChatMessage(role="user", content=prompt)],
                max_output_tokens=32,
                temperature=0.0,
                timeout_seconds=10.0,
            )
        )
        return ProviderTestResult(
            ok=bool(response.text) and response.error_kind is None,
            latency_ms=response.latency_ms,
            response_text=response.text,
            first_token_ms=response.first_text_ms,
            model=response.model,
            error="" if response.error_kind is None else response.error_kind.value,
            error_kind=response.error_kind,
        )

    def diagnostic(self) -> RuntimeDiagnostic:
        installed = self.detect()
        models = self.list_models()
        if models:
            status = RuntimeHealthStatus.READY
            detail = f"Ollama available with {len(models)} installed model(s)."
        elif installed:
            status = RuntimeHealthStatus.DEGRADED
            detail = "Ollama is installed but no usable model was observed."
        else:
            status = RuntimeHealthStatus.CLIENT_MISSING
            detail = "Ollama is not installed for this explicit local profile."
        return RuntimeDiagnostic(
            provider_id=self.provider_id,
            display_name=self.display_name,
            installed=installed,
            version=self.version(),
            auth_status=RuntimeAuthStatus.NOT_REQUIRED,
            health_status=status,
            detail=detail,
            models=models,
        )


class ExternalRuntimeManager:
    """Registry for administrative diagnostics; it does not own conversation routing."""

    def __init__(self) -> None:
        self._runtimes: dict[str, ExternalProviderRuntime] = {}
        self._test_history: dict[str, ProviderTestResult] = {}
        self._test_timestamps: dict[str, float] = {}
        self._diag_cache: dict[str, tuple[float, RuntimeDiagnostic]] = {}
        self._diag_ttl_s = 120.0

    def register(self, runtime: ExternalProviderRuntime) -> None:
        self._runtimes[runtime.provider_id.lower().strip()] = runtime

    def get_runtime(self, provider_id: str) -> ExternalProviderRuntime | None:
        return self._runtimes.get(provider_id.lower().strip())

    def get_diagnostic(self, provider_id: str, refresh: bool = False) -> RuntimeDiagnostic:
        provider_id = provider_id.lower().strip()
        now = time.time()
        cached = self._diag_cache.get(provider_id)
        if not refresh and cached and now - cached[0] < self._diag_ttl_s:
            return cached[1]
        runtime = self.get_runtime(provider_id)
        if runtime is None:
            return RuntimeDiagnostic(
                provider_id=provider_id,
                display_name=provider_id,
                installed=False,
                health_status=RuntimeHealthStatus.DISABLED,
                detail="Provider is not registered.",
            )
        diagnostic = runtime.diagnostic()
        last_test = self._test_history.get(provider_id)
        if last_test is not None:
            diagnostic.last_test_latency_ms = last_test.latency_ms
            diagnostic.last_test_ok = last_test.ok
            diagnostic.last_test_error = last_test.error
            diagnostic.last_test_model = last_test.model
            diagnostic.last_test_time = self._test_timestamps.get(provider_id)
            diagnostic.ttft_ms = last_test.first_token_ms
            if last_test.ok:
                diagnostic.health_status = RuntimeHealthStatus.READY
                diagnostic.detail = "Inference verified in this process."
            elif last_test.error_kind and last_test.error_kind.value == "rate_limit":
                diagnostic.health_status = RuntimeHealthStatus.RATE_LIMITED
                diagnostic.detail = "Rate limited during the latest explicit test."
            elif last_test.error_kind and last_test.error_kind.value == "authentication":
                diagnostic.health_status = RuntimeHealthStatus.AUTH_REQUIRED
                diagnostic.detail = "Authentication failed during the latest explicit test."
            else:
                diagnostic.health_status = RuntimeHealthStatus.UNHEALTHY
                diagnostic.detail = "Latest explicit inference test failed."
        self._diag_cache[provider_id] = (now, diagnostic)
        return diagnostic

    def get_all_diagnostics(self, refresh: bool = False) -> dict[str, RuntimeDiagnostic]:
        return {
            provider_id: self.get_diagnostic(provider_id, refresh=refresh)
            for provider_id in self._runtimes
        }

    def list_models(self, provider_id: str) -> list[str]:
        runtime = self.get_runtime(provider_id)
        return runtime.list_models() if runtime is not None else []

    def test_connection(
        self,
        provider_id: str,
        *,
        prompt: str = "Respondé solamente: OK",
    ) -> ProviderTestResult:
        runtime = self.get_runtime(provider_id)
        if runtime is None:
            return ProviderTestResult(
                ok=False,
                latency_ms=0.0,
                error="Provider is not registered.",
            )
        result = runtime.test_connection(prompt=prompt)
        self.record_test_result(provider_id, result)
        return result

    def record_test_result(self, provider_id: str, result: ProviderTestResult) -> None:
        provider_id = provider_id.lower().strip()
        self._test_history[provider_id] = result
        self._test_timestamps[provider_id] = time.time()
        self._diag_cache.pop(provider_id, None)

    def get_last_test_result(self, provider_id: str) -> ProviderTestResult | None:
        return self._test_history.get(provider_id.lower().strip())

    @classmethod
    def create_default(cls, cfg: AILENConfig | None = None) -> ExternalRuntimeManager:
        manager = cls()
        if cfg is None:
            return manager
        secrets = SecretResolver()
        for provider_id, provider in cfg.ai.remote.providers.items():
            manager.register(
                RemoteApiRuntime(provider_id, provider, secrets_resolver=secrets)
            )
        if cfg.ai.local.enabled:
            manager.register(
                LocalOllamaRuntime(
                    endpoint=cfg.ai.local.endpoint,
                    model=cfg.ai.local.model,
                )
            )
        return manager

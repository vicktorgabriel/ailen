"""Administrative Provider Manager tests without real provider requests."""

from ailen.ai.contracts import AiErrorKind
from ailen.ai.providers import ProviderTestResult
from ailen.ai.runtime_manager import (
    ExternalRuntimeManager,
    RemoteApiRuntime,
    RuntimeAuthStatus,
    RuntimeHealthStatus,
)
from ailen.ai.secrets import SecretResolver
from ailen.core.config import AILENConfig, RemoteProviderConfig


def _remote(enabled: bool = True) -> RemoteProviderConfig:
    return RemoteProviderConfig(
        enabled=enabled,
        preset="openai",
        protocol="openai_responses",
        endpoint="https://api.example.invalid/v1",
        model="operator-model",
        api_key_env="AILEN_TEST_REMOTE_KEY",
        api_key_file="remote_test_key",
    )


def test_remote_runtime_does_not_claim_health_from_configuration() -> None:
    runtime = RemoteApiRuntime(
        "primary",
        _remote(),
        secrets_resolver=SecretResolver("/definitely/missing"),
    )
    diagnostic = runtime.diagnostic()
    assert diagnostic.provider_id == "remote:primary"
    assert diagnostic.auth_status is RuntimeAuthStatus.UNAUTHENTICATED
    assert diagnostic.health_status is RuntimeHealthStatus.AUTH_REQUIRED
    assert not hasattr(diagnostic, "can_install")
    assert not hasattr(diagnostic, "can_login")


def test_manager_registers_named_remotes_and_never_retired_clients() -> None:
    config = AILENConfig()
    config.ai.remote.providers = {
        "openai": _remote(),
        "disabled": _remote(enabled=False),
    }
    config.ai.local.enabled = False
    manager = ExternalRuntimeManager.create_default(config)
    diagnostics = manager.get_all_diagnostics()
    assert set(diagnostics) == {"remote:openai", "remote:disabled"}
    assert manager.get_runtime("local") is None
    assert manager.get_runtime("antigravity") is None
    assert manager.get_runtime("opencode") is None


def test_local_runtime_exists_only_when_explicitly_enabled() -> None:
    config = AILENConfig()
    config.ai.local.enabled = True
    manager = ExternalRuntimeManager.create_default(config)
    assert manager.get_runtime("local") is not None


def test_explicit_test_result_controls_observed_health() -> None:
    manager = ExternalRuntimeManager()
    manager.register(
        RemoteApiRuntime(
            "primary",
            _remote(),
            secrets_resolver=SecretResolver("/definitely/missing"),
        )
    )
    manager.record_test_result(
        "remote:primary",
        ProviderTestResult(
            ok=False,
            latency_ms=12.0,
            model="operator-model",
            error="rate_limit",
            error_kind=AiErrorKind.RATE_LIMIT,
        ),
    )
    diagnostic = manager.get_diagnostic("remote:primary")
    assert diagnostic.health_status is RuntimeHealthStatus.RATE_LIMITED
    assert diagnostic.last_test_latency_ms == 12.0

"""Unit tests for SecretResolver."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from ailen.ai.secrets import SecretResolver


def test_secret_resolver_direct_value() -> None:
    resolver = SecretResolver()
    assert resolver.resolve(direct_value="my-secret-key") == "my-secret-key"


def test_secret_resolver_env_var(monkeypatch) -> None:
    monkeypatch.setenv("AILEN_TEST_KEY", "env-secret-123")
    resolver = SecretResolver()
    assert resolver.resolve(env_var="AILEN_TEST_KEY") == "env-secret-123"


def test_secret_resolver_file() -> None:
    with TemporaryDirectory() as tmpdir:
        secret_file = Path(tmpdir) / "cloud_token"
        secret_file.write_text("file-secret-456\n", encoding="utf-8")
        secret_file.chmod(0o600)

        resolver = SecretResolver(secrets_dir=tmpdir)
        assert resolver.resolve(file_name="cloud_token") == "file-secret-456"


def test_secret_resolver_priority(monkeypatch) -> None:
    with TemporaryDirectory() as tmpdir:
        secret_file = Path(tmpdir) / "cloud_token"
        secret_file.write_text("from-file", encoding="utf-8")
        secret_file.chmod(0o600)

        monkeypatch.setenv("AILEN_TEST_KEY", "from-env")
        resolver = SecretResolver(secrets_dir=tmpdir)

        # Direct overrides env and file
        assert resolver.resolve(
            env_var="AILEN_TEST_KEY",
            file_name="cloud_token",
            direct_value="from-direct",
        ) == "from-direct"

        # Env overrides file
        assert resolver.resolve(
            env_var="AILEN_TEST_KEY",
            file_name="cloud_token",
        ) == "from-env"


def test_secret_resolver_rejects_group_or_world_readable_file_on_posix() -> None:
    if os.name != "posix":
        return
    with TemporaryDirectory() as tmpdir:
        secret_file = Path(tmpdir) / "cloud_token"
        secret_file.write_text("too-open", encoding="utf-8")
        secret_file.chmod(0o644)
        resolver = SecretResolver(secrets_dir=tmpdir)
        assert resolver.resolve(file_name="cloud_token") is None


def test_secret_resolver_masking() -> None:
    resolver = SecretResolver("/var/lib/ailen/secrets")
    assert str(resolver) == "SecretResolver(***)"
    assert "SecretResolver" in repr(resolver)

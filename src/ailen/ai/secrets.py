"""Secret resolver for AI providers and external credentials.

Keeps API keys and sensitive tokens out of configuration files, SQLite, logs,
and event payloads. Supports environment variables and owner-only secret files.
"""

import os
from pathlib import Path


def get_default_secrets_dir() -> Path:
    """Resolve standard directory for secure secret files."""
    if "AILEN_SECRETS_DIR" in os.environ:
        return Path(os.environ["AILEN_SECRETS_DIR"])
    system_dir = Path("/var/lib/ailen/secrets")
    if system_dir.is_dir():
        return system_dir
    # Local data directory for dev / laboratory mode
    local_data = Path("data/secrets")
    if local_data.parent.is_dir() or Path("data").is_dir():
        return local_data
    return Path.home() / ".local" / "share" / "ailen" / "secrets"


class SecretResolver:
    """Safely resolves and stores secrets from environment variables or file paths."""

    def __init__(self, secrets_dir: str | Path | None = None) -> None:
        if secrets_dir is not None:
            self.secrets_dir = Path(secrets_dir)
        else:
            self.secrets_dir = get_default_secrets_dir()

    def resolve(
        self,
        env_var: str | None = None,
        file_name: str | None = None,
        direct_value: str | None = None,
    ) -> str | None:
        """Resolve a secret with priority: direct -> env -> file."""
        # 1. Direct explicit value (if passed programmatically)
        if direct_value and direct_value.strip():
            return direct_value.strip()

        # 2. Environment variable
        if env_var:
            val = os.environ.get(env_var)
            if val and val.strip():
                return val.strip()

        # 3. Secret file
        if file_name:
            secret_file = self.secrets_dir / file_name
            if secret_file.is_file():
                try:
                    if os.name == "posix" and (secret_file.stat().st_mode & 0o077):
                        return None
                    content = secret_file.read_text(encoding="utf-8").strip()
                    if content:
                        return content
                except Exception:  # noqa: BLE001, S110
                    pass

        return None

    def save_secret(self, file_name: str, value: str) -> Path:
        """Save a secret to the secrets directory with strict 0600 permissions."""
        if not file_name or "/" in file_name or "\\" in file_name or file_name.startswith("."):
            raise ValueError(f"Invalid secret file name: {file_name!r}")

        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            try:
                self.secrets_dir.chmod(0o700)
            except Exception:  # noqa: BLE001, S110
                pass

        target_file = self.secrets_dir / file_name
        tmp_file = self.secrets_dir / f".{file_name}.tmp"

        # Write to tmp file with 0600 permissions
        content = value.strip()
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(tmp_file, flags, mode)
        try:
            with open(fd, "w", encoding="utf-8", closefd=True) as f:
                f.write(content)
        except Exception:
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001, S110
                pass
            raise

        if os.name == "posix":
            os.chmod(tmp_file, 0o600)
        os.replace(tmp_file, target_file)
        if os.name == "posix":
            os.chmod(target_file, 0o600)
        return target_file

    def delete_secret(self, file_name: str) -> bool:
        """Delete a secret file if it exists."""
        if not file_name or "/" in file_name or "\\" in file_name:
            return False
        target = self.secrets_dir / file_name
        if target.is_file():
            target.unlink(missing_ok=True)
            return True
        return False

    def has_secret(
        self,
        env_var: str | None = None,
        file_name: str | None = None,
    ) -> bool:
        """Check if a secret is available without exposing its value."""
        return self.resolve(env_var=env_var, file_name=file_name) is not None

    @staticmethod
    def mask(value: str | None) -> str:
        """Mask a secret for display purposes in logs or UI."""
        if not value or not value.strip():
            return ""
        val = value.strip()
        if len(val) <= 8:
            return "••••••••"
        if val.startswith("sk-") and len(val) > 10:
            return f"sk-...{val[-4:]}"
        return f"••••••••{val[-4:]}"

    def __repr__(self) -> str:
        return f"SecretResolver(secrets_dir='{self.secrets_dir}')"

    def __str__(self) -> str:
        return "SecretResolver(***)"

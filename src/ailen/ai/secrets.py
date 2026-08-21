"""Secret resolver for AI providers and external credentials.

Keeps API keys and sensitive tokens out of configuration files, SQLite, logs,
and event payloads. Supports environment variables and owner-only secret files.
"""

import os
from pathlib import Path


class SecretResolver:
    """Safely resolves secrets from environment variables or file paths."""

    def __init__(self, secrets_dir: str | Path = "/var/lib/ailen/secrets") -> None:
        self.secrets_dir = Path(secrets_dir)

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

    def __repr__(self) -> str:
        return f"SecretResolver(secrets_dir='{self.secrets_dir}')"

    def __str__(self) -> str:
        return "SecretResolver(***)"

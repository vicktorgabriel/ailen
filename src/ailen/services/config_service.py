"""Configuration service for AILEN."""

from pathlib import Path

from ailen.core.config import AILENConfig, load_config, save_config, validate_config


class ConfigService:
    """Application service for reading, validating, and saving configuration."""

    def __init__(self, config_path: Path | str | None = None):
        self.config_path = config_path
        self._config: AILENConfig = load_config(config_path)

    @property
    def current_config(self) -> AILENConfig:
        """Return the currently loaded configuration."""
        return self._config

    def reload(self) -> AILENConfig:
        """Reload configuration from disk."""
        self._config = load_config(self.config_path)
        return self._config

    def validate(self) -> list[str]:
        """Validate current configuration."""
        return validate_config(self._config)

    def save(self, target_path: Path | str | None = None) -> None:
        """Save configuration to specified path or original path."""
        self.save_config(self._config, target_path)

    def save_config(self, config: AILENConfig, target_path: Path | str | None = None) -> None:
        """Validate and persist the given configuration, then adopt it in memory.

        La escritura en disco es atómica (ver ``core.config.save_config``).
        """
        errors = validate_config(config)
        if errors:
            raise ValueError(f"Cannot save invalid configuration: {'; '.join(errors)}")
        path = target_path or self.config_path or Path("config/ailen.toml")
        save_config(config, path)
        self._config = config

"""Configuration management for AILEN."""

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ailen.domain.enums import DeviceProfile, SocialMode


@dataclass
class NodeConfig:
    """Node identity configuration."""
    node_id: str = "ailen-node-01"
    name: str = "AILEN Unit"
    profile: DeviceProfile = DeviceProfile.HYBRID
    data_dir: str = "data"


@dataclass
class IdentityConfig:
    """Character identity shown to users. Separate from the AILEN brand.

    ``display_name`` es el nombre visible del personaje de esta instalación.
    Nunca debe asumirse que el personaje se llama "Ailén": es configurable.
    """
    display_name: str = "Asistente"


@dataclass
class DisplayConfig:
    """Face and display output configuration."""
    enabled: bool = True
    backend: str = "auto"  # "auto", "sdl2", "drm", "x11", "headless"
    width: int = 1280
    height: int = 720
    fullscreen: bool = True
    fps_limit: int = 30


@dataclass
class AudioConfig:
    """Audio input/output configuration."""
    input_device: str = "default"
    output_device: str = "default"
    input_volume: int = 80
    output_volume: int = 80
    music_volume: int = 60


@dataclass
class VisionConfig:
    """Camera and presence detection configuration."""
    enabled: bool = True
    camera_device: str = "/dev/video0"
    fps: int = 5
    presence_debounce_seconds: float = 2.0
    min_confidence: float = 0.5


@dataclass
class SpeechConfig:
    """STT and TTS engine configuration."""
    stt_engine: str = "mock"  # "mock", "whisper_cpp", "vosk", "cloud"
    stt_language: str = "es"
    tts_engine: str = "mock"  # "mock", "piper", "coqui", "cloud"
    tts_voice: str = "es_ES-standard"
    vad_sensitivity: int = 2


@dataclass
class AiConfig:
    """AI Router and LLM provider configuration."""
    provider: str = "mock"  # "mock", "local", "lan_brain", "cloud"
    model: str = "default"
    max_tokens: int = 512
    timeout_seconds: float = 10.0
    daily_budget_usd: float = 1.0
    allow_cloud: bool = True


@dataclass
class MemoryConfig:
    """SQLite and memory retention configuration."""
    sqlite_path: str = "data/ailen.db"
    fts_enabled: bool = True
    retention_days: int = 90
    auto_vacuum: bool = True


@dataclass
class PersonalityConfig:
    """Personality simulation parameters."""
    seed: str = "ailen-seed-01"
    evolution_enabled: bool = True
    evolution_rate: float = 1.0
    base_curiosity: float = 0.7
    base_sociability: float = 0.6
    base_formality: float = 0.5
    base_humor: float = 0.5


@dataclass
class SocialConfig:
    """Social Engine rules and greeting behavior."""
    default_mode: SocialMode = SocialMode.WORKSHOP
    greeting_cooldown_seconds: float = 300.0  # 5 minutes
    auto_greeting_enabled: bool = True
    public_memory_filter: bool = True


@dataclass
class WebConfig:
    """Local administration web panel configuration."""
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    session_expiry_hours: int = 24
    rate_limit_rpm: int = 60


@dataclass
class UpdatesConfig:
    """System updates configuration."""
    channel: str = "beta"  # "nightly", "beta", "stable"
    auto_check: bool = False
    check_interval_hours: int = 24


@dataclass
class LoggingConfig:
    """Logging and telemetry configuration."""
    level: str = "INFO"  # "DEBUG", "INFO", "WARNING", "ERROR"
    json_format: bool = False
    log_file: str | None = None
    redact_secrets: bool = True


@dataclass
class AILENConfig:
    """Root configuration for AILEN."""
    schema_version: int = 1
    node: NodeConfig = field(default_factory=NodeConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    social: SocialConfig = field(default_factory=SocialConfig)
    web: WebConfig = field(default_factory=WebConfig)
    updates: UpdatesConfig = field(default_factory=UpdatesConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        d = asdict(self)
        d["node"]["profile"] = self.node.profile.value
        d["social"]["default_mode"] = self.social.default_mode.value
        return d


def _dump_toml_section(name: str, data: dict[str, Any]) -> str:
    """Format a single TOML section."""
    lines = [f"[{name}]"]
    for k, v in data.items():
        if isinstance(v, bool):
            val_str = "true" if v else "false"
        elif isinstance(v, (int, float)):
            val_str = str(v)
        elif v is None:
            continue
        else:
            val_str = f'"{v}"'
        lines.append(f"{k} = {val_str}")
    lines.append("")
    return "\n".join(lines)


def dump_config_toml(config: AILENConfig) -> str:
    """Serialize AILENConfig to TOML formatted string."""
    lines = [
        "# AILEN Configuration File",
        f"schema_version = {config.schema_version}",
        "",
    ]
    raw = config.to_dict()
    for section_name, section_data in raw.items():
        if section_name == "schema_version":
            continue
        if isinstance(section_data, dict):
            lines.append(_dump_toml_section(section_name, section_data))
    return "\n".join(lines)


def load_config_from_dict(raw: dict[str, Any]) -> AILENConfig:
    """Construct AILENConfig from parsed dictionary."""
    cfg = AILENConfig()
    cfg.schema_version = raw.get("schema_version", 1)

    if "node" in raw and isinstance(raw["node"], dict):
        node_raw = raw["node"]
        cfg.node.node_id = node_raw.get("node_id", cfg.node.node_id)
        cfg.node.name = node_raw.get("name", cfg.node.name)
        if "profile" in node_raw:
            try:
                cfg.node.profile = DeviceProfile(node_raw["profile"])
            except ValueError:
                pass
        cfg.node.data_dir = node_raw.get("data_dir", cfg.node.data_dir)

    if "identity" in raw and isinstance(raw["identity"], dict):
        for k, v in raw["identity"].items():
            if hasattr(cfg.identity, k):
                setattr(cfg.identity, k, v)

    if "display" in raw and isinstance(raw["display"], dict):
        for k, v in raw["display"].items():
            if hasattr(cfg.display, k):
                setattr(cfg.display, k, v)

    if "audio" in raw and isinstance(raw["audio"], dict):
        for k, v in raw["audio"].items():
            if hasattr(cfg.audio, k):
                setattr(cfg.audio, k, v)

    if "vision" in raw and isinstance(raw["vision"], dict):
        for k, v in raw["vision"].items():
            if hasattr(cfg.vision, k):
                setattr(cfg.vision, k, v)

    if "speech" in raw and isinstance(raw["speech"], dict):
        for k, v in raw["speech"].items():
            if hasattr(cfg.speech, k):
                setattr(cfg.speech, k, v)

    if "ai" in raw and isinstance(raw["ai"], dict):
        for k, v in raw["ai"].items():
            if hasattr(cfg.ai, k):
                setattr(cfg.ai, k, v)

    if "memory" in raw and isinstance(raw["memory"], dict):
        for k, v in raw["memory"].items():
            if hasattr(cfg.memory, k):
                setattr(cfg.memory, k, v)

    if "personality" in raw and isinstance(raw["personality"], dict):
        for k, v in raw["personality"].items():
            if hasattr(cfg.personality, k):
                setattr(cfg.personality, k, v)

    if "social" in raw and isinstance(raw["social"], dict):
        soc_raw = raw["social"]
        for k, v in soc_raw.items():
            if k == "default_mode":
                try:
                    cfg.social.default_mode = SocialMode(v)
                except ValueError:
                    pass
            elif hasattr(cfg.social, k):
                setattr(cfg.social, k, v)

    if "web" in raw and isinstance(raw["web"], dict):
        for k, v in raw["web"].items():
            if hasattr(cfg.web, k):
                setattr(cfg.web, k, v)

    if "updates" in raw and isinstance(raw["updates"], dict):
        for k, v in raw["updates"].items():
            if hasattr(cfg.updates, k):
                setattr(cfg.updates, k, v)

    if "logging" in raw and isinstance(raw["logging"], dict):
        for k, v in raw["logging"].items():
            if hasattr(cfg.logging, k):
                setattr(cfg.logging, k, v)

    return cfg


def find_config_path(explicit_path: str | Path | None = None) -> Path | None:
    """Find the configuration file path in standard locations."""
    if explicit_path:
        p = Path(explicit_path)
        if not p.is_file():
            raise FileNotFoundError(f"Configuration file not found: {p}")
        return p

    # Check AILEN_CONFIG environment variable
    env_path = os.environ.get("AILEN_CONFIG")
    if env_path:
        p = Path(env_path)
        if not p.is_file():
            raise FileNotFoundError(f"AILEN_CONFIG points to a missing file: {p}")
        return p

    candidates = [
        Path("/etc/ailen/ailen.toml"),
        Path("config/ailen.toml"),
        Path("ailen.toml"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_config(path: str | Path | None = None) -> AILENConfig:
    """Load configuration from file or return default configuration."""
    cfg_file = find_config_path(path)
    if not cfg_file:
        return AILENConfig()

    try:
        with open(cfg_file, "rb") as f:
            raw = tomllib.load(f)
        return load_config_from_dict(raw)
    except Exception as e:
        raise ValueError(f"Failed to load config from {cfg_file}: {e}") from e


def save_config(config: AILENConfig, target_path: str | Path) -> None:
    """Save configuration atomically: temp file in same dir + os.replace.

    Evita dejar un TOML corrupto/truncado si el proceso muere a mitad de
    escritura. El archivo original sólo se reemplaza por uno completo.
    """
    p = Path(target_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    toml_text = dump_config_toml(config)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(toml_text, encoding="utf-8")
    os.replace(tmp, p)


def validate_config(config: AILENConfig) -> list[str]:
    """Validate configuration and return list of validation error messages."""
    errors = []
    if config.schema_version < 1:
        errors.append("schema_version must be >= 1")
    if not config.node.node_id.strip():
        errors.append("node.node_id cannot be empty")
    if not config.identity.display_name.strip():
        errors.append("identity.display_name cannot be empty")
    if config.display.width <= 0 or config.display.height <= 0:
        errors.append("display width and height must be positive integers")
    if config.display.fps_limit < 1 or config.display.fps_limit > 120:
        errors.append("display.fps_limit must be between 1 and 120")
    if not (0 <= config.audio.output_volume <= 100):
        errors.append("audio.output_volume must be between 0 and 100")
    if not (0 <= config.audio.input_volume <= 100):
        errors.append("audio.input_volume must be between 0 and 100")
    if config.ai.timeout_seconds <= 0:
        errors.append("ai.timeout_seconds must be positive")
    if config.web.port < 1 or config.web.port > 65535:
        errors.append("web.port must be between 1 and 65535")
    if config.logging.level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append(f"Invalid logging level: {config.logging.level}")
    return errors

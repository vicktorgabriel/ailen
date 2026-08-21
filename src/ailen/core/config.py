"""Configuration management for AILEN."""

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: float = 20.0


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
    stt_model_path: str = ""
    tts_engine: str = "mock"  # "mock", "piper", "coqui", "cloud"
    tts_voice: str = "es_ES-standard"
    tts_model_path: str = ""
    tts_config_path: str = ""
    vad_engine: str = "energy"  # "energy", "mock"
    vad_threshold: float = 0.02
    silence_timeout_ms: int = 700
    min_speech_ms: int = 250
    max_utterance_seconds: float = 15.0
    half_duplex: bool = True
    vad_sensitivity: int = 2


@dataclass
class AiLocalConfig:
    """Local LLM server configuration (e.g. llama.cpp server, Ollama)."""
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:8080/v1"
    model: str = "local-model"
    timeout_seconds: float = 20.0


@dataclass
class AiLanConfig:
    """LAN Brain server configuration."""
    enabled: bool = False
    endpoint: str = "http://192.168.1.100:8080/v1"
    model: str = "lan-model"
    trusted: bool = False
    timeout_seconds: float = 15.0


@dataclass
class AiCloudConfig:
    """Cloud LLM provider configuration.

    Provider, model and pricing are intentionally unset by default because they
    change over time and must come from deployment configuration.
    """
    enabled: bool = False
    provider: str = "openai_compatible"
    endpoint: str = ""
    model: str = ""
    api_key_env: str = "AILEN_AI_CLOUD_API_KEY"
    api_key_file: str = "ai_cloud_key"
    daily_budget_usd: float = 1.0
    monthly_budget_usd: float = 20.0
    timeout_seconds: float = 10.0
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None


@dataclass
class AiConfig:
    """AI Router and LLM provider configuration."""
    provider: str = "mock"  # "mock", "local", "lan_brain", "cloud"
    model: str = "default"
    max_tokens: int = 512
    timeout_seconds: float = 10.0
    daily_budget_usd: float = 1.0
    allow_cloud: bool = True
    local: AiLocalConfig = field(default_factory=AiLocalConfig)
    lan: AiLanConfig = field(default_factory=AiLanConfig)
    cloud: AiCloudConfig = field(default_factory=AiCloudConfig)


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


def _format_toml_value(value: Any) -> str:
    """Format a scalar TOML value safely for AILEN's configuration schema."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _dump_toml_sections(prefix: str, data: dict[str, Any]) -> list[str]:
    """Serialize a mapping recursively using TOML dotted table headers."""
    scalar_items = {k: v for k, v in data.items() if not isinstance(v, dict) and v is not None}
    nested_items = {k: v for k, v in data.items() if isinstance(v, dict)}

    lines: list[str] = []
    if scalar_items:
        lines.append(f"[{prefix}]")
        for key, value in scalar_items.items():
            lines.append(f"{key} = {_format_toml_value(value)}")
        lines.append("")

    for key, nested in nested_items.items():
        lines.extend(_dump_toml_sections(f"{prefix}.{key}", nested))

    return lines


def dump_config_toml(config: AILENConfig) -> str:
    """Serialize AILENConfig to TOML formatted string, including nested AI sections."""
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
            lines.extend(_dump_toml_sections(section_name, section_data))
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
        ai_raw = raw["ai"]
        for k, v in ai_raw.items():
            if k == "local" and isinstance(v, dict):
                for lk, lv in v.items():
                    if hasattr(cfg.ai.local, lk):
                        setattr(cfg.ai.local, lk, lv)
            elif k == "lan" and isinstance(v, dict):
                for lk, lv in v.items():
                    if hasattr(cfg.ai.lan, lk):
                        setattr(cfg.ai.lan, lk, lv)
            elif k == "cloud" and isinstance(v, dict):
                for ck, cv in v.items():
                    if hasattr(cfg.ai.cloud, ck):
                        setattr(cfg.ai.cloud, ck, cv)
            elif hasattr(cfg.ai, k):
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
    if config.audio.sample_rate not in {8000, 16000, 22050, 44100, 48000}:
        errors.append("audio.sample_rate must be a standard rate (8000, 16000, 22050, 44100, 48000)")
    if config.audio.channels not in {1, 2}:
        errors.append("audio.channels must be 1 (mono) or 2 (stereo)")
    if config.audio.frame_ms <= 0:
        errors.append("audio.frame_ms must be positive")
    if not (0.0 <= config.speech.vad_threshold <= 1.0):
        errors.append("speech.vad_threshold must be between 0.0 and 1.0")
    if config.speech.silence_timeout_ms <= 0:
        errors.append("speech.silence_timeout_ms must be positive")
    if config.speech.min_speech_ms <= 0:
        errors.append("speech.min_speech_ms must be positive")
    if config.speech.max_utterance_seconds <= 0:
        errors.append("speech.max_utterance_seconds must be positive")
    if config.vision.fps < 1:
        errors.append("vision.fps must be >= 1")
    if config.vision.presence_debounce_seconds < 0:
        errors.append("vision.presence_debounce_seconds must be >= 0")
    if not (0.0 <= config.vision.min_confidence <= 1.0):
        errors.append("vision.min_confidence must be between 0.0 and 1.0")
    if config.ai.timeout_seconds <= 0:
        errors.append("ai.timeout_seconds must be positive")
    if config.ai.daily_budget_usd < 0:
        errors.append("ai.daily_budget_usd must be >= 0")
    if config.ai.local.timeout_seconds <= 0:
        errors.append("ai.local.timeout_seconds must be positive")
    if config.ai.lan.timeout_seconds <= 0:
        errors.append("ai.lan.timeout_seconds must be positive")
    if config.ai.cloud.timeout_seconds <= 0:
        errors.append("ai.cloud.timeout_seconds must be positive")
    if config.ai.cloud.daily_budget_usd < 0:
        errors.append("ai.cloud.daily_budget_usd must be >= 0")
    if config.ai.cloud.monthly_budget_usd < 0:
        errors.append("ai.cloud.monthly_budget_usd must be >= 0")
    if config.ai.cloud.input_cost_per_million is not None and config.ai.cloud.input_cost_per_million < 0:
        errors.append("ai.cloud.input_cost_per_million must be >= 0")
    if config.ai.cloud.output_cost_per_million is not None and config.ai.cloud.output_cost_per_million < 0:
        errors.append("ai.cloud.output_cost_per_million must be >= 0")
    if config.ai.cloud.enabled and (
        config.ai.cloud.input_cost_per_million is None
        or config.ai.cloud.output_cost_per_million is None
    ):
        errors.append("ai.cloud token pricing must be configured when cloud is enabled")

    for section_name, enabled, endpoint, model in (
        ("ai.local", config.ai.local.enabled, config.ai.local.endpoint, config.ai.local.model),
        ("ai.lan", config.ai.lan.enabled, config.ai.lan.endpoint, config.ai.lan.model),
        ("ai.cloud", config.ai.cloud.enabled, config.ai.cloud.endpoint, config.ai.cloud.model),
    ):
        if not enabled:
            continue
        if not model.strip():
            errors.append(f"{section_name}.model cannot be empty when enabled")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{section_name}.endpoint must be a valid http(s) URL when enabled")
    if config.ai.cloud.enabled and not config.ai.cloud.provider.strip():
        errors.append("ai.cloud.provider cannot be empty when enabled")

    if config.web.port < 1 or config.web.port > 65535:
        errors.append("web.port must be between 1 and 65535")
    if config.logging.level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append(f"Invalid logging level: {config.logging.level}")
    return errors

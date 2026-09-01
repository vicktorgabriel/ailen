"""Configuration management for AILEN."""

import os
import re
import tomllib
import warnings
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ailen.domain.enums import DeviceProfile, SocialMode

CURRENT_CONFIG_SCHEMA_VERSION = 3
REMOTE_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
REMOTE_PROTOCOLS = frozenset(
    {"openai_responses", "openai_chat", "anthropic_messages"}
)
REMOTE_QUALIFICATION_STATES = frozenset(
    {"configured", "tested", "qualified", "rejected"}
)


class ConfigMigrationWarning(UserWarning):
    """A legacy configuration was loaded through a safe one-way migration."""


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
    face_style: str = "facepack"  # "facepack", "portrait", "vector" or "pixel"
    face_engine_library: str = ""
    facepack_path: str = "runtime/facepacks/ailen_default.facepack"
    facepack_root: str = "runtime/facepacks"
    width: int = 1280
    height: int = 720
    fullscreen: bool = True
    fps_limit: int = 30


@dataclass
class AudioConfig:
    """Audio input/output configuration."""
    input_device: str = "default"
    output_device: str = "default"
    input_processing_mode: str = "auto"  # auto, raw, easyeffects
    capture_gain_db: float = 0.0
    auto_gain_enabled: bool = False
    auto_gain_target_rms: float = 0.12
    max_auto_gain_db: float = 18.0
    auto_gain_attack_ms: float = 120.0
    auto_gain_release_ms: float = 600.0
    auto_gain_noise_gate_rms: float = 0.008
    auto_gain_gate_hold_ms: float = 300.0
    capture_limiter_peak: float = 0.98
    output_volume: int = 80
    music_volume: int = 60
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: float = 20.0


@dataclass
class VisionConfig:
    """Camera and face/presence detection configuration."""
    enabled: bool = True
    # Source selection is explicit so the same image can run on recycled USB
    # webcams, authenticated RTSP cameras, or automatically choose what exists.
    # Supported values: "auto", "usb", "rtsp".
    camera_source: str = "auto"
    camera_device: str = "/dev/video0"
    # Optional authenticated RTSP source. Password is resolved at runtime from
    # network_camera_password_env and is never persisted in TOML.
    network_camera_enabled: bool = False
    network_camera_host: str = ""
    network_camera_port: int = 554
    network_camera_path: str = "/h264_hd.sdp"
    network_camera_username: str = ""
    network_camera_password_env: str = "AILEN_CAMERA_PASSWORD"
    camera_control_driver: str = "none"
    network_camera_http_port: int = 80
    camera_control_timeout_seconds: float = 3.0
    camera_startup_daynight_mode: str = "auto"
    rtsp_transport: str = "tcp"
    rtsp_open_timeout_ms: int = 3000
    rtsp_read_timeout_ms: int = 2500
    rtsp_reconnect_after_failures: int = 3
    fps: int = 5
    detector: str = "haar"
    detector_model_path: str = ""
    detector_score_threshold: float = 0.8
    presence_confirm_seconds: float = 0.8
    absence_confirm_seconds: float = 2.0
    dropout_grace_seconds: float = 0.6
    min_confidence: float = 0.5


@dataclass
class SpeechConfig:
    """STT and TTS engine configuration."""
    stt_engine: str = "mock"  # "mock", "whisper_cpp", "vosk", "cloud"
    stt_language: str = "es"
    stt_model_path: str = ""
    stt_fallback_engine: str = "none"  # "none", "whisper_cpp"
    stt_fallback_model_path: str = ""
    stt_fallback_confidence_threshold: float = 0.72
    stt_noise_confidence_max: float = 0.20
    stt_conversation_min_confidence: float = 0.45
    voice_action_min_confidence: float = 0.72
    tts_engine: str = "mock"  # "mock", "piper", "coqui", "cloud"
    tts_voice: str = "es_ES-standard"
    tts_model_path: str = ""
    tts_config_path: str = ""
    tts_rate: float = 1.0
    tts_threads: int = 0
    tts_fallback_engine: str = "none"  # "none", "piper"
    chatterbox_endpoint: str = "http://127.0.0.1:8765"
    chatterbox_timeout_seconds: float = 6.0
    chatterbox_pitch_semitones: float = 0.0
    chatterbox_rate_scale: float = 1.0
    noise_suppression_engine: str = "none"  # "none", "webrtc"
    noise_suppression_level: int = 2
    vad_engine: str = "energy"  # "energy", "webrtc", "mock"
    vad_threshold: float = 0.02
    vad_webrtc_mode: int = 2
    vad_hangover_ms: int = 120
    pre_roll_ms: int = 250
    silence_timeout_ms: int = 550
    min_speech_ms: int = 180
    max_utterance_seconds: float = 15.0
    interruption_enabled: bool = True
    interruption_threshold_rms: float = 0.02
    interruption_min_ms: int = 120
    interruption_calibration_ms: int = 160
    interruption_leak_multiplier: float = 1.25


@dataclass
class AiLocalConfig:
    """Local LLM server configuration (e.g. llama.cpp server, Ollama)."""
    enabled: bool = False
    # Provisioning persists an exact runtime after target-hardware
    # qualification. ``auto`` is retained for an explicit laboratory model
    # override, never as permission to cross runtime evidence.
    runtime: str = "auto"  # auto, ollama, llama_cpp
    endpoint: str = "http://127.0.0.1:8080/v1"
    # Empty means "use the exact selection activated by provisioning".  A
    # non-empty value remains an explicit laboratory/operator override.
    model: str = ""
    timeout_seconds: float = 20.0
    context_tokens: int = 2048
    # Empty uses hardware/profile policy. Dedicated always-on nodes may keep the
    # primary model resident (for example "24h") to avoid conversational cold starts.
    keep_alive: str = ""
    # Optional small local model dedicated to bounded tool-intent parsing.
    # Empty means reuse the main local conversational backend.
    intent_model: str = ""
    intent_timeout_seconds: float = 5.0
    priority: int = 50


@dataclass
class AiLanConfig:
    """LAN Brain server configuration (laboratory/distributed deployments)."""
    enabled: bool = False
    provider: str = "openai_compatible"  # "openai_compatible", "ollama_native"
    endpoint: str = "http://192.168.1.100:8080/v1"
    model: str = "lan-model"
    trusted: bool = False
    timeout_seconds: float = 15.0
    priority: int = 40


@dataclass
class RemoteProviderConfig:
    """One named remote provider; models remain operator/live-catalog data."""

    enabled: bool = False
    preset: str = "openai_compatible"
    protocol: str = "openai_chat"
    endpoint: str = ""
    model: str = ""
    api_key_env: str = ""
    api_key_file: str = ""
    auth_mode: str = "api_key"  # "api_key" or explicit "none"
    priority: int = 30
    timeout_seconds: float = 10.0
    daily_budget_usd: float = 1.0
    monthly_budget_usd: float = 20.0
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    streaming_enabled: bool = True
    voice_realtime_eligible: bool = False
    qualification_status: str = "configured"
    catalog_mode: str = "manual"  # "manual" or "live"
    anthropic_version: str = "2023-06-01"


@dataclass
class AiRemoteConfig:
    """Collection of independently configured remote providers."""

    enabled: bool = True
    providers: dict[str, RemoteProviderConfig] = field(
        default_factory=lambda: remote_provider_presets()
    )


_REMOTE_PRESET_VALUES: dict[str, dict[str, str]] = {
    "openai": {
        "protocol": "openai_responses",
        "endpoint": "https://api.openai.com/v1",
        "api_key_env": "AILEN_OPENAI_API_KEY",
        "api_key_file": "remote_openai_key",
        "auth_mode": "api_key",
        "catalog_mode": "live",
    },
    "anthropic": {
        "protocol": "anthropic_messages",
        "endpoint": "https://api.anthropic.com/v1",
        "api_key_env": "AILEN_ANTHROPIC_API_KEY",
        "api_key_file": "remote_anthropic_key",
        "auth_mode": "api_key",
        "catalog_mode": "manual",
    },
    "deepseek": {
        "protocol": "openai_chat",
        "endpoint": "https://api.deepseek.com",
        "api_key_env": "AILEN_DEEPSEEK_API_KEY",
        "api_key_file": "remote_deepseek_key",
        "auth_mode": "api_key",
        "catalog_mode": "manual",
    },
    "kimi": {
        "protocol": "openai_chat",
        "endpoint": "https://api.moonshot.ai/v1",
        "api_key_env": "AILEN_KIMI_API_KEY",
        "api_key_file": "remote_kimi_key",
        "auth_mode": "api_key",
        "catalog_mode": "manual",
    },
    "minimax": {
        "protocol": "openai_chat",
        "endpoint": "https://api.minimax.io/v1",
        "api_key_env": "AILEN_MINIMAX_API_KEY",
        "api_key_file": "remote_minimax_key",
        "auth_mode": "api_key",
        "catalog_mode": "manual",
    },
    "openai_compatible": {
        "protocol": "openai_chat",
        "endpoint": "",
        "api_key_env": "",
        "api_key_file": "",
        "auth_mode": "api_key",
        "catalog_mode": "manual",
    },
    "anthropic_compatible": {
        "protocol": "anthropic_messages",
        "endpoint": "",
        "api_key_env": "",
        "api_key_file": "",
        "auth_mode": "api_key",
        "catalog_mode": "manual",
    },
}


def remote_provider_presets() -> dict[str, RemoteProviderConfig]:
    """Return fresh editable presets without asserting any current model ID."""

    return {
        name: RemoteProviderConfig(
            preset=name,
            protocol=values["protocol"],
            endpoint=values["endpoint"],
            api_key_env=values["api_key_env"],
            api_key_file=values["api_key_file"],
            auth_mode=values["auth_mode"],
            catalog_mode=values["catalog_mode"],
        )
        for name, values in _REMOTE_PRESET_VALUES.items()
    }


@dataclass
class AiConfig:
    """AI Router and LLM provider configuration."""
    provider: str = "mock"  # "auto", "mock", "local", "lan_brain", "remote:<id>"
    max_tokens: int = 512
    temperature: float = 0.6
    context_recent_messages: int = 4
    context_char_budget: int = 2400
    timeout_seconds: float = 10.0
    daily_budget_usd: float = 1.0
    allow_remote: bool = True
    # Allows the current user turn to use an external conversational provider
    # while keeping session history/retrieved memory on-device. PRIVATE memory
    # is never silently downgraded or attached to the outbound request.
    allow_sanitized_external_prompts: bool = False
    local: AiLocalConfig = field(default_factory=AiLocalConfig)
    lan: AiLanConfig = field(default_factory=AiLanConfig)
    remote: AiRemoteConfig = field(default_factory=AiRemoteConfig)



@dataclass
class MemoryConfig:
    """SQLite and memory retention configuration."""
    sqlite_path: str = "data/ailen.db"
    fts_enabled: bool = True
    retention_days: int = 90
    auto_vacuum: bool = True


@dataclass
class PersonalityConfig:
    """Safe stylistic personality parameters, never authority or permissions."""
    seed: str = "ailen-seed-01"
    description: str = ""
    evolution_enabled: bool = True
    evolution_rate: float = 1.0
    base_curiosity: float = 0.7
    base_sociability: float = 0.6
    base_formality: float = 0.5
    base_humor: float = 0.5
    base_verbosity: float = 0.4
    base_patience: float = 0.7
    base_expressiveness: float = 0.6


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
class NetworkConfig:
    """Outbound network policy and explicit web-search provider selection."""
    outbound_web_enabled: bool = False
    web_search_provider: str = "none"
    web_search_region: str = "ar-es"


@dataclass
class UpdatesConfig:
    """System updates configuration."""
    channel: str = "beta"  # "nightly", "beta", "stable"
    auto_check: bool = False
    check_interval_hours: int = 24
    manifest_url: str = ""
    manifest_signature_url: str = ""
    trust_public_key_path: str = ""
    auto_install: bool = False
    maintenance_window: str = "03:00"


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
    schema_version: int = CURRENT_CONFIG_SCHEMA_VERSION
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
    network: NetworkConfig = field(default_factory=NetworkConfig)
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


def _migration_warning(message: str) -> None:
    warnings.warn(message, ConfigMigrationWarning, stacklevel=3)


def _migrate_legacy_ai(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a detached current-schema document with fail-closed migrations."""

    migrated = deepcopy(raw)
    audio_raw = migrated.get("audio")
    if isinstance(audio_raw, dict) and "input_volume" in audio_raw:
        audio_raw.pop("input_volume", None)
        _migration_warning(
            "audio.input_volume was decorative and has been removed; "
            "capture_gain_db remains 0 dB until measured calibration is confirmed"
        )
    ai_raw = migrated.get("ai")
    if not isinstance(ai_raw, dict):
        migrated["schema_version"] = CURRENT_CONFIG_SCHEMA_VERSION
        return migrated

    preferred = str(ai_raw.get("provider", "mock")).strip().lower()
    retired_present = False
    for retired in ("antigravity", "opencode"):
        if retired in ai_raw:
            ai_raw.pop(retired, None)
            retired_present = True
            _migration_warning(
                f"ai.{retired} was retired from AILEN and was ignored; configure a supported "
                "remote provider instead"
            )
    if preferred in {"antigravity", "opencode"}:
        preferred = "auto"
        retired_present = True

    if "allow_cloud" in ai_raw and "allow_remote" not in ai_raw:
        ai_raw["allow_remote"] = bool(ai_raw.pop("allow_cloud"))
        _migration_warning("ai.allow_cloud migrated to ai.allow_remote")
    else:
        ai_raw.pop("allow_cloud", None)

    remote_raw = ai_raw.get("remote")
    if not isinstance(remote_raw, dict):
        remote_raw = {"enabled": True, "providers": {}}
        ai_raw["remote"] = remote_raw
    providers_raw = remote_raw.get("providers")
    if not isinstance(providers_raw, dict):
        providers_raw = {}
        remote_raw["providers"] = providers_raw

    legacy_cloud = ai_raw.pop("cloud", None)
    if isinstance(legacy_cloud, dict):
        migrated_provider = {
            "enabled": bool(legacy_cloud.get("enabled", False)),
            "preset": "openai_compatible",
            "protocol": "openai_chat",
            "endpoint": str(legacy_cloud.get("endpoint", "")),
            "model": str(legacy_cloud.get("model", "")),
            "api_key_env": str(legacy_cloud.get("api_key_env", "AILEN_AI_CLOUD_API_KEY")),
            "api_key_file": str(legacy_cloud.get("api_key_file", "ai_cloud_key")),
            "auth_mode": "api_key",
            "priority": int(legacy_cloud.get("priority", 30)),
            "timeout_seconds": float(legacy_cloud.get("timeout_seconds", 10.0)),
            "daily_budget_usd": float(legacy_cloud.get("daily_budget_usd", 1.0)),
            "monthly_budget_usd": float(legacy_cloud.get("monthly_budget_usd", 20.0)),
            "input_cost_per_million": legacy_cloud.get("input_cost_per_million"),
            "output_cost_per_million": legacy_cloud.get("output_cost_per_million"),
            "streaming_enabled": True,
            "voice_realtime_eligible": False,
            "qualification_status": "configured",
            "catalog_mode": "manual",
        }
        providers_raw.setdefault("legacy_cloud", migrated_provider)
        _migration_warning(
            "ai.cloud migrated to ai.remote.providers.legacy_cloud; review and save the new schema"
        )
        if preferred == "cloud":
            preferred = (
                "remote:legacy_cloud" if migrated_provider["enabled"] else "auto"
            )
    elif preferred == "cloud":
        preferred = "auto"
        _migration_warning("legacy ai.provider=cloud had no provider configuration and became auto")

    if "model" in ai_raw:
        ai_raw.pop("model", None)
        _migration_warning(
            "legacy ai.model was ignored; select the model in ai.local, ai.lan, or a named remote provider"
        )
    if retired_present:
        _migration_warning(
            "retired preferred providers migrate to ai.provider=auto and are never invoked"
        )
    ai_raw["provider"] = preferred
    migrated["schema_version"] = CURRENT_CONFIG_SCHEMA_VERSION
    return migrated


def _load_dataclass_fields(target: object, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if hasattr(target, key):
            setattr(target, key, value)


def load_config_from_dict(raw: dict[str, Any]) -> AILENConfig:
    """Construct AILENConfig from parsed dictionary."""
    raw = _migrate_legacy_ai(raw)
    cfg = AILENConfig()
    cfg.schema_version = CURRENT_CONFIG_SCHEMA_VERSION

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
        vision_raw = raw["vision"]
        for k, v in vision_raw.items():
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
                _load_dataclass_fields(cfg.ai.local, v)
            elif k == "lan" and isinstance(v, dict):
                _load_dataclass_fields(cfg.ai.lan, v)
            elif k == "remote" and isinstance(v, dict):
                if "enabled" in v:
                    cfg.ai.remote.enabled = bool(v["enabled"])
                providers = v.get("providers")
                if isinstance(providers, dict):
                    cfg.ai.remote.providers = remote_provider_presets()
                    for provider_id, provider_raw in providers.items():
                        if not isinstance(provider_raw, dict):
                            continue
                        provider = RemoteProviderConfig()
                        _load_dataclass_fields(provider, provider_raw)
                        cfg.ai.remote.providers[str(provider_id)] = provider
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

    if "network" in raw and isinstance(raw["network"], dict):
        for k, v in raw["network"].items():
            if hasattr(cfg.network, k):
                setattr(cfg.network, k, v)

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
    if config.display.face_style not in {"facepack", "portrait", "vector", "pixel"}:
        errors.append("display.face_style must be one of: facepack, portrait, vector, pixel")
    if not (0 <= config.audio.output_volume <= 100):
        errors.append("audio.output_volume must be between 0 and 100")
    if config.audio.input_processing_mode not in {"auto", "raw", "easyeffects"}:
        errors.append(
            "audio.input_processing_mode must be one of: auto, raw, easyeffects"
        )
    if not (-24.0 <= config.audio.capture_gain_db <= 30.0):
        errors.append("audio.capture_gain_db must be between -24 and 30")
    if not (0.01 <= config.audio.auto_gain_target_rms <= 0.5):
        errors.append("audio.auto_gain_target_rms must be between 0.01 and 0.5")
    if not (0.0 <= config.audio.max_auto_gain_db <= 30.0):
        errors.append("audio.max_auto_gain_db must be between 0 and 30")
    if config.audio.auto_gain_attack_ms <= 0.0:
        errors.append("audio.auto_gain_attack_ms must be positive")
    if config.audio.auto_gain_release_ms <= 0.0:
        errors.append("audio.auto_gain_release_ms must be positive")
    if not (0.0 <= config.audio.auto_gain_noise_gate_rms <= 0.5):
        errors.append("audio.auto_gain_noise_gate_rms must be between 0 and 0.5")
    if not (0.0 <= config.audio.auto_gain_gate_hold_ms <= 5000.0):
        errors.append("audio.auto_gain_gate_hold_ms must be between 0 and 5000")
    if not (0.5 <= config.audio.capture_limiter_peak <= 1.0):
        errors.append("audio.capture_limiter_peak must be between 0.5 and 1.0")
    if config.audio.sample_rate not in {8000, 16000, 22050, 44100, 48000}:
        errors.append("audio.sample_rate must be a standard rate (8000, 16000, 22050, 44100, 48000)")
    if config.audio.channels not in {1, 2}:
        errors.append("audio.channels must be 1 (mono) or 2 (stereo)")
    if config.audio.frame_ms <= 0:
        errors.append("audio.frame_ms must be positive")
    if config.speech.stt_fallback_engine not in {"none", "whisper_cpp"}:
        errors.append("speech.stt_fallback_engine must be one of: none, whisper_cpp")
    if not (0.0 <= config.speech.stt_fallback_confidence_threshold <= 1.0):
        errors.append("speech.stt_fallback_confidence_threshold must be between 0.0 and 1.0")
    if not (0.0 <= config.speech.voice_action_min_confidence <= 1.0):
        errors.append("speech.voice_action_min_confidence must be between 0.0 and 1.0")
    if not (
        0.0 <= config.speech.stt_noise_confidence_max
        < config.speech.stt_conversation_min_confidence
        <= config.speech.voice_action_min_confidence
        <= 1.0
    ):
        errors.append(
            "STT confidence thresholds must satisfy 0 <= "
            "speech.stt_noise_confidence_max < "
            "speech.stt_conversation_min_confidence <= "
            "speech.voice_action_min_confidence <= 1"
        )
    if config.speech.noise_suppression_engine not in {"none", "webrtc"}:
        errors.append("speech.noise_suppression_engine must be one of: none, webrtc")
    if config.speech.noise_suppression_level not in {0, 1, 2, 3}:
        errors.append("speech.noise_suppression_level must be between 0 and 3")
    if not (0.5 <= config.speech.tts_rate <= 1.8):
        errors.append("speech.tts_rate must be between 0.5 and 1.8")
    if not (0 <= config.speech.tts_threads <= 32):
        errors.append("speech.tts_threads must be between 0 and 32")
    if config.speech.tts_fallback_engine not in {"none", "piper"}:
        errors.append("speech.tts_fallback_engine must be one of: none, piper")
    if not (0.5 <= config.speech.chatterbox_timeout_seconds <= 60.0):
        errors.append("speech.chatterbox_timeout_seconds must be between 0.5 and 60.0")
    if not (-2.0 <= config.speech.chatterbox_pitch_semitones <= 2.0):
        errors.append("speech.chatterbox_pitch_semitones must be between -2.0 and 2.0")
    if not (0.85 <= config.speech.chatterbox_rate_scale <= 1.15):
        errors.append("speech.chatterbox_rate_scale must be between 0.85 and 1.15")
    if config.speech.vad_engine not in {"energy", "webrtc", "mock"}:
        errors.append("speech.vad_engine must be one of: energy, webrtc, mock")
    if not (0.0 <= config.speech.vad_threshold <= 1.0):
        errors.append("speech.vad_threshold must be between 0.0 and 1.0")
    if config.speech.vad_webrtc_mode not in {0, 1, 2, 3}:
        errors.append("speech.vad_webrtc_mode must be between 0 and 3")
    if config.speech.vad_hangover_ms < 0:
        errors.append("speech.vad_hangover_ms must be >= 0")
    if config.speech.pre_roll_ms < 0:
        errors.append("speech.pre_roll_ms must be >= 0")
    if config.speech.silence_timeout_ms <= 0:
        errors.append("speech.silence_timeout_ms must be positive")
    if config.speech.min_speech_ms <= 0:
        errors.append("speech.min_speech_ms must be positive")
    if config.speech.max_utterance_seconds <= 0:
        errors.append("speech.max_utterance_seconds must be positive")
    if config.network.web_search_provider not in {"none", "ddgs"}:
        errors.append("network.web_search_provider must be one of: none, ddgs")
    if not config.network.web_search_region.strip():
        errors.append("network.web_search_region must not be empty")
    if config.vision.fps < 1:
        errors.append("vision.fps must be >= 1")
    source_mode = config.vision.camera_source.strip().lower()
    if source_mode not in {"auto", "usb", "rtsp"}:
        errors.append("vision.camera_source must be one of: auto, usb, rtsp")
    if source_mode == "rtsp" and not config.vision.network_camera_enabled:
        errors.append("vision.network_camera_enabled must be true when vision.camera_source=rtsp")
    if config.vision.network_camera_enabled:
        if not config.vision.network_camera_host.strip():
            errors.append("vision.network_camera_host is required when network camera is enabled")
        if not (1 <= config.vision.network_camera_port <= 65535):
            errors.append("vision.network_camera_port must be between 1 and 65535")
        if not config.vision.network_camera_path.strip():
            errors.append("vision.network_camera_path is required when network camera is enabled")
        if config.vision.network_camera_username.strip() and not config.vision.network_camera_password_env.strip():
            errors.append("vision.network_camera_password_env is required for authenticated network camera")
    if config.vision.camera_control_driver not in {"none", "tp_link_nc250"}:
        errors.append("vision.camera_control_driver must be one of: none, tp_link_nc250")
    if not (1 <= config.vision.network_camera_http_port <= 65535):
        errors.append("vision.network_camera_http_port must be between 1 and 65535")
    if config.vision.camera_control_timeout_seconds <= 0:
        errors.append("vision.camera_control_timeout_seconds must be positive")
    if config.vision.camera_startup_daynight_mode not in {"auto", "day", "night"}:
        errors.append("vision.camera_startup_daynight_mode must be one of: auto, day, night")
    if config.vision.rtsp_transport not in {"tcp", "udp"}:
        errors.append("vision.rtsp_transport must be one of: tcp, udp")
    if config.vision.rtsp_open_timeout_ms < 250:
        errors.append("vision.rtsp_open_timeout_ms must be >= 250")
    if config.vision.rtsp_read_timeout_ms < 250:
        errors.append("vision.rtsp_read_timeout_ms must be >= 250")
    if config.vision.rtsp_reconnect_after_failures < 1:
        errors.append("vision.rtsp_reconnect_after_failures must be >= 1")
    if config.speech.silence_timeout_ms < 100:
        errors.append("speech.silence_timeout_ms must be >= 100")
    if not (0.0 < config.speech.interruption_threshold_rms <= 1.0):
        errors.append("speech.interruption_threshold_rms must be between 0.0 and 1.0")
    if config.speech.interruption_min_ms < 40:
        errors.append("speech.interruption_min_ms must be >= 40")
    if config.speech.interruption_calibration_ms < 0:
        errors.append("speech.interruption_calibration_ms must be >= 0")
    if config.speech.interruption_leak_multiplier < 1.0:
        errors.append("speech.interruption_leak_multiplier must be >= 1.0")
    if config.vision.presence_confirm_seconds < 0:
        errors.append("vision.presence_confirm_seconds must be >= 0")
    if config.vision.absence_confirm_seconds < 0:
        errors.append("vision.absence_confirm_seconds must be >= 0")
    if config.vision.dropout_grace_seconds < 0:
        errors.append("vision.dropout_grace_seconds must be >= 0")
    if not (0.0 <= config.vision.min_confidence <= 1.0):
        errors.append("vision.min_confidence must be between 0.0 and 1.0")
    if config.vision.detector not in {"haar", "yunet"}:
        errors.append("vision.detector must be one of: haar, yunet")
    if not (0.0 <= config.vision.detector_score_threshold <= 1.0):
        errors.append("vision.detector_score_threshold must be between 0.0 and 1.0")
    if config.vision.detector == "yunet" and not config.vision.detector_model_path.strip():
        errors.append("vision.detector_model_path is required when vision.detector=yunet")
    if len(config.personality.description) > 1000:
        errors.append("personality.description must be at most 1000 characters")
    personality_values = {
        "evolution_rate": config.personality.evolution_rate,
        "base_curiosity": config.personality.base_curiosity,
        "base_sociability": config.personality.base_sociability,
        "base_formality": config.personality.base_formality,
        "base_humor": config.personality.base_humor,
        "base_verbosity": config.personality.base_verbosity,
        "base_patience": config.personality.base_patience,
        "base_expressiveness": config.personality.base_expressiveness,
    }
    for name, value in personality_values.items():
        if not (0.0 <= value <= 1.0):
            errors.append(f"personality.{name} must be between 0.0 and 1.0")
    if not (0.0 <= config.ai.temperature <= 2.0):
        errors.append("ai.temperature must be between 0.0 and 2.0")
    if not (1 <= config.ai.context_recent_messages <= 32):
        errors.append("ai.context_recent_messages must be between 1 and 32")
    if not (512 <= config.ai.context_char_budget <= 20000):
        errors.append("ai.context_char_budget must be between 512 and 20000")
    if config.ai.timeout_seconds <= 0:
        errors.append("ai.timeout_seconds must be positive")
    if config.ai.daily_budget_usd < 0:
        errors.append("ai.daily_budget_usd must be >= 0")
    if config.ai.local.timeout_seconds <= 0:
        errors.append("ai.local.timeout_seconds must be positive")
    if config.ai.local.runtime not in {"auto", "ollama", "llama_cpp"}:
        errors.append("ai.local.runtime must be one of: auto, ollama, llama_cpp")
    if not (512 <= config.ai.local.context_tokens <= 32768):
        errors.append("ai.local.context_tokens must be between 512 and 32768")
    allowed_providers = {"auto", "mock", "local", "lan_brain"}
    preferred_remote_id = ""
    if config.ai.provider.startswith("remote:"):
        preferred_remote_id = config.ai.provider.removeprefix("remote:")
        if REMOTE_PROVIDER_ID_RE.fullmatch(preferred_remote_id) is None:
            errors.append("ai.provider remote ID is invalid")
    elif config.ai.provider not in allowed_providers:
        errors.append(
            "ai.provider must be one of: auto, mock, local, lan_brain, remote:<id>"
        )
    if config.ai.lan.provider not in {"openai_compatible", "ollama_native"}:
        errors.append("ai.lan.provider must be one of: openai_compatible, ollama_native")
    if config.ai.lan.timeout_seconds <= 0:
        errors.append("ai.lan.timeout_seconds must be positive")
    for section_name, enabled, endpoint, model in (
        ("ai.local", config.ai.local.enabled, config.ai.local.endpoint, config.ai.local.model),
        ("ai.lan", config.ai.lan.enabled, config.ai.lan.endpoint, config.ai.lan.model),
    ):
        if not enabled:
            continue
        # Local may intentionally be empty: provisioning then supplies the
        # immutable, target-qualified model selection.  LAN still requires an
        # explicit remote model contract.
        if section_name == "ai.lan" and not model.strip():
            errors.append(f"{section_name}.model cannot be empty when enabled")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{section_name}.endpoint must be a valid http(s) URL when enabled")
    for provider_id, provider in config.ai.remote.providers.items():
        section_name = f"ai.remote.providers.{provider_id}"
        if REMOTE_PROVIDER_ID_RE.fullmatch(provider_id) is None:
            errors.append(f"{section_name} has an invalid provider ID")
        if not provider.preset.strip():
            errors.append(f"{section_name}.preset cannot be empty")
        if provider.protocol not in REMOTE_PROTOCOLS:
            errors.append(
                f"{section_name}.protocol must be one of: "
                f"{', '.join(sorted(REMOTE_PROTOCOLS))}"
            )
        if provider.timeout_seconds <= 0:
            errors.append(f"{section_name}.timeout_seconds must be positive")
        if not 0 <= provider.priority <= 1000:
            errors.append(f"{section_name}.priority must be between 0 and 1000")
        if provider.daily_budget_usd < 0 or provider.monthly_budget_usd < 0:
            errors.append(f"{section_name} budgets must be >= 0")
        if (
            provider.input_cost_per_million is not None
            and provider.input_cost_per_million < 0
        ):
            errors.append(f"{section_name}.input_cost_per_million must be >= 0")
        if (
            provider.output_cost_per_million is not None
            and provider.output_cost_per_million < 0
        ):
            errors.append(f"{section_name}.output_cost_per_million must be >= 0")
        if provider.qualification_status not in REMOTE_QUALIFICATION_STATES:
            errors.append(f"{section_name}.qualification_status is invalid")
        if provider.catalog_mode not in {"manual", "live"}:
            errors.append(f"{section_name}.catalog_mode must be manual or live")
        if provider.api_key_env and re.fullmatch(
            r"[A-Z][A-Z0-9_]{1,127}", provider.api_key_env
        ) is None:
            errors.append(f"{section_name}.api_key_env is invalid")
        if provider.api_key_file and (
            Path(provider.api_key_file).name != provider.api_key_file
            or provider.api_key_file in {".", ".."}
        ):
            errors.append(f"{section_name}.api_key_file must be a safe filename")
        if provider.auth_mode not in {"api_key", "none"}:
            errors.append(f"{section_name}.auth_mode must be api_key or none")
        if provider.enabled and provider.auth_mode == "api_key" and not (
            provider.api_key_env or provider.api_key_file
        ):
            errors.append(f"{section_name} requires a provider-specific key location")
        if provider.voice_realtime_eligible and (
            provider.qualification_status != "qualified"
            or not provider.streaming_enabled
        ):
            errors.append(
                f"{section_name}.voice_realtime_eligible requires qualified real streaming"
            )
        if not provider.enabled:
            continue
        if not provider.model.strip():
            errors.append(f"{section_name}.model cannot be empty when enabled")
        parsed_remote = urlparse(provider.endpoint)
        if (
            parsed_remote.scheme != "https"
            or not parsed_remote.netloc
            or parsed_remote.username is not None
            or parsed_remote.password is not None
            or parsed_remote.fragment
        ):
            errors.append(f"{section_name}.endpoint must be a valid HTTPS URL when enabled")
        if provider.qualification_status == "rejected":
            errors.append(f"{section_name} cannot be enabled while rejected")

    if preferred_remote_id:
        selected = config.ai.remote.providers.get(preferred_remote_id)
        if selected is None:
            errors.append(f"ai.provider references unknown remote provider {preferred_remote_id!r}")
        elif not selected.enabled:
            errors.append(f"ai.provider references disabled remote provider {preferred_remote_id!r}")

    if not isinstance(config.updates.channel, str) or config.updates.channel not in {
        "nightly",
        "beta",
        "stable",
    }:
        errors.append("updates.channel must be one of: nightly, beta, stable")
    if (
        type(config.updates.check_interval_hours) is not int
        or not 1 <= config.updates.check_interval_hours <= 168
    ):
        errors.append("updates.check_interval_hours must be between 1 and 168")
    if type(config.updates.auto_check) is not bool:
        errors.append("updates.auto_check must be a boolean")
    if type(config.updates.auto_install) is not bool:
        errors.append("updates.auto_install must be a boolean")
    if not isinstance(config.updates.maintenance_window, str) or re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]",
        config.updates.maintenance_window,
    ) is None:
        errors.append("updates.maintenance_window must use HH:MM (00:00..23:59)")

    update_source_values = (
        config.updates.manifest_url,
        config.updates.manifest_signature_url,
        config.updates.trust_public_key_path,
    )
    source_strings_valid = all(isinstance(value, str) for value in update_source_values)
    manifest_url = (
        config.updates.manifest_url.strip()
        if isinstance(config.updates.manifest_url, str)
        else ""
    )
    signature_url = (
        config.updates.manifest_signature_url.strip()
        if isinstance(config.updates.manifest_signature_url, str)
        else ""
    )
    trust_path = (
        config.updates.trust_public_key_path.strip()
        if isinstance(config.updates.trust_public_key_path, str)
        else ""
    )
    if not source_strings_valid:
        errors.append("updates source and trust fields must be strings")
    if bool(manifest_url) != bool(signature_url):
        errors.append("updates manifest and signature URLs must be configured together")
    if any((manifest_url, signature_url, trust_path)) and not all(
        (manifest_url, signature_url, trust_path)
    ):
        errors.append("updates source and trust must be configured together")
    for field_name, update_url in (
        ("manifest_url", manifest_url),
        ("manifest_signature_url", signature_url),
    ):
        if not update_url:
            continue
        parsed_update_url = urlparse(update_url)
        if (
            parsed_update_url.scheme != "https"
            or not parsed_update_url.netloc
            or parsed_update_url.username is not None
            or parsed_update_url.password is not None
            or bool(parsed_update_url.fragment)
        ):
            errors.append(f"updates.{field_name} must be a valid HTTPS URL")
    if config.updates.auto_install and not all((manifest_url, signature_url, trust_path)):
        errors.append("updates.auto_install requires a complete signed update source")

    if config.web.port < 1 or config.web.port > 65535:
        errors.append("web.port must be between 1 and 65535")
    if config.logging.level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append(f"Invalid logging level: {config.logging.level}")
    return errors

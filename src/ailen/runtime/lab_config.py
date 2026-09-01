"""Generate explicit, canonical lab topology profiles.

Lab files are disposable test profiles under ``runtime/lab``. They are not a
second product configuration source and none of the hardware tiers below is a
support claim until it has a target-device benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ailen.core.config import AILENConfig, dump_config_toml
from ailen.domain.enums import DeviceProfile
from ailen.speech.catalog import SpeechAssetCatalog
from ailen.speech.store import SpeechAssetStore


@dataclass(frozen=True)
class LabProfileDefinition:
    node_profile: DeviceProfile
    local_requested: bool
    local_endpoint: str
    lan_enabled: bool = False
    lan_model: str = "lan-model"
    lan_endpoint: str = "http://ailen-brain.local:8080/v1"


LAB_PROFILES: dict[str, LabProfileDefinition] = {
    "recycled-4gb-local-candidate": LabProfileDefinition(
        node_profile=DeviceProfile.HYBRID,
        local_requested=True,
        local_endpoint="http://127.0.0.1:8080/v1",
    ),
    "recycled-8gb-hybrid": LabProfileDefinition(
        node_profile=DeviceProfile.HYBRID,
        local_requested=True,
        local_endpoint="http://127.0.0.1:8080/v1",
    ),
    "lan-satellite": LabProfileDefinition(
        node_profile=DeviceProfile.SATELLITE,
        local_requested=False,
        local_endpoint="http://127.0.0.1:8080/v1",
        lan_enabled=True,
    ),
    "gpu-lan-brain": LabProfileDefinition(
        node_profile=DeviceProfile.LAN_BRAIN,
        local_requested=True,
        local_endpoint="http://127.0.0.1:8080/v1",
    ),
    "external-only": LabProfileDefinition(
        node_profile=DeviceProfile.CLOUD,
        local_requested=False,
        local_endpoint="http://127.0.0.1:8080/v1",
    ),
}
LAB_PROFILE_IDS: tuple[str, ...] = tuple(LAB_PROFILES)


def generate_lab_config_toml(
    *,
    profile_id: str,
    store: SpeechAssetStore | None = None,
    stt_engine: str = "vosk",
    tts_voice: str = "es_ES-davefx-medium",
    local_endpoint: str | None = None,
    local_model: str | None = None,
    lan_endpoint: str | None = None,
    lan_model: str | None = None,
    lan_trusted: bool = False,
) -> str:
    """Build one explicit topology using only fields consumed by AILENConfig."""
    try:
        profile = LAB_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown lab profile {profile_id!r}; choose one of: {', '.join(LAB_PROFILE_IDS)}"
        ) from exc

    asset_store = store or SpeechAssetStore()
    catalog = SpeechAssetCatalog()
    stt_desc = catalog.get(
        "vosk-model-small-es-0.42" if stt_engine == "vosk" else "whisper-ggml-tiny"
    )
    tts_desc = catalog.get(tts_voice)

    config = AILENConfig()
    config.node.profile = profile.node_profile
    config.identity.display_name = "Asistente"
    config.display.face_style = "facepack"
    config.display.width = 800
    config.display.height = 480
    config.display.fullscreen = False
    config.audio.input_device = "default"
    config.audio.output_device = "default"

    config.speech.stt_engine = stt_engine
    config.speech.stt_model_path = (
        str(asset_store.get_asset_path(stt_desc)) if stt_desc is not None else ""
    )
    config.speech.stt_noise_confidence_max = 0.20
    config.speech.stt_conversation_min_confidence = 0.45
    config.speech.voice_action_min_confidence = 0.72
    config.speech.tts_engine = "piper"
    config.speech.tts_voice = tts_voice
    config.speech.tts_model_path = (
        str(asset_store.get_asset_path(tts_desc)) if tts_desc is not None else ""
    )
    config.speech.tts_config_path = ""
    if tts_desc is not None and tts_desc.associated_config_id:
        tts_config_desc = catalog.get(tts_desc.associated_config_id)
        if tts_config_desc is not None:
            config.speech.tts_config_path = str(
                asset_store.get_asset_path(tts_config_desc)
            )
    config.speech.vad_engine = "webrtc"
    config.speech.vad_webrtc_mode = 2
    config.speech.silence_timeout_ms = 550
    config.speech.interruption_enabled = True

    config.ai.provider = "auto"
    config.ai.max_tokens = 96
    config.ai.timeout_seconds = 20.0
    config.ai.allow_remote = True
    config.ai.allow_sanitized_external_prompts = False
    # A topology requests local inference, but a fixed model is never inferred
    # from the profile name. Provisioning selects a target-qualified model from
    # measured hardware. An explicit model here is a laboratory override.
    config.ai.local.enabled = bool(profile.local_requested and local_model)
    config.ai.local.endpoint = local_endpoint or profile.local_endpoint
    config.ai.local.model = local_model or ""
    config.ai.local.context_tokens = 1024 if profile_id.startswith("recycled-4gb") else 2048
    config.ai.lan.enabled = profile.lan_enabled
    config.ai.lan.endpoint = lan_endpoint or profile.lan_endpoint
    config.ai.lan.model = lan_model or profile.lan_model
    config.ai.lan.trusted = bool(lan_trusted)
    # Named remotes remain disabled until the operator configures a model and
    # provider-specific secret. Local is never enabled implicitly.
    for remote in config.ai.remote.providers.values():
        remote.enabled = False

    config.memory.sqlite_path = "runtime/lab/ailen_lab.db"
    config.memory.retention_days = 30
    config.network.outbound_web_enabled = True
    config.network.web_search_provider = "ddgs"
    config.social.greeting_cooldown_seconds = 60.0

    header = (
        "# AILEN — isolated Lab profile (gitignored)\n"
        "# config/ailen.toml remains the canonical runtime configuration.\n"
        f"# topology_profile={profile_id}; candidate only, not hardware certification.\n"
        "# local model selection is pending `ailen models provision-plan` unless an explicit lab override was supplied.\n"
    )
    return header + dump_config_toml(config)


def init_lab_config(
    *,
    profile_id: str,
    target_path: Path | None = None,
    force: bool = False,
    stt_engine: str = "vosk",
    tts_voice: str = "es_ES-davefx-medium",
    local_endpoint: str | None = None,
    local_model: str | None = None,
    lan_endpoint: str | None = None,
    lan_model: str | None = None,
    lan_trusted: bool = False,
) -> tuple[Path, bool]:
    """Create one explicit isolated profile without touching product config."""
    out_path = target_path or Path("runtime/lab/ailen-lab.toml")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.is_file() and not force:
        return out_path, False
    out_path.write_text(
        generate_lab_config_toml(
            profile_id=profile_id,
            stt_engine=stt_engine,
            tts_voice=tts_voice,
            local_endpoint=local_endpoint,
            local_model=local_model,
            lan_endpoint=lan_endpoint,
            lan_model=lan_model,
            lan_trusted=lan_trusted,
        ),
        encoding="utf-8",
    )
    return out_path, True

"""Generates isolated lab configuration at runtime/lab/ailen-lab.toml without touching product config."""

from pathlib import Path

from ailen.speech.catalog import SpeechAssetCatalog
from ailen.speech.store import SpeechAssetStore


def generate_lab_config_toml(
    store: SpeechAssetStore | None = None,
    stt_engine: str = "vosk",
    tts_voice: str = "es_ES-davefx-medium",
    ai_endpoint: str = "http://127.0.0.1:11434/v1",
    ai_model: str = "qwen3.5:9b",
) -> str:
    """Generate TOML content customized for local lab environment."""
    s = store or SpeechAssetStore()
    cat = SpeechAssetCatalog()

    stt_desc = cat.get("vosk-model-small-es-0.42" if stt_engine == "vosk" else "whisper-ggml-tiny")
    stt_path = str(s.get_asset_path(stt_desc)) if stt_desc else ""

    tts_desc = cat.get(tts_voice)
    tts_model_path = str(s.get_asset_path(tts_desc)) if tts_desc else ""
    tts_config_path = ""
    if tts_desc and tts_desc.associated_config_id:
        cfg_desc = cat.get(tts_desc.associated_config_id)
        if cfg_desc:
            tts_config_path = str(s.get_asset_path(cfg_desc))

    return f"""# AILEN — Isolated Lab Mode Configuration
# Generated automatically for local physical testing in runtime/lab/
# This file is gitignored and does not modify config/ailen.toml

[identity]
display_name = "Asistente"

[display]
enabled = true
backend = "auto"
face_style = "pixel"
width = 800
height = 480
fullscreen = false
fps_limit = 30

[audio]
input_device = "default"
output_device = "default"
sample_rate = 16000
channels = 1
frame_ms = 20.0
voice_volume = 100
sound_volume = 80
music_volume = 60

[speech]
stt_engine = "{stt_engine}"
stt_language = "es"
stt_fallback_engine = "none"
stt_fallback_model_path = ""
stt_fallback_confidence_threshold = 0.72
stt_model_path = "{stt_path}"
tts_engine = "piper"
tts_voice = "{tts_voice}"
tts_model_path = "{tts_model_path}"
tts_config_path = "{tts_config_path}"
tts_rate = 1.0
tts_threads = 0
tts_fallback_engine = "none"
chatterbox_endpoint = "http://127.0.0.1:8765"
chatterbox_timeout_seconds = 6.0
chatterbox_pitch_semitones = 0.0
chatterbox_rate_scale = 1.0
noise_suppression_engine = "none"
noise_suppression_level = 2
vad_engine = "webrtc"
vad_threshold = 0.02
vad_webrtc_mode = 2
vad_hangover_ms = 120
pre_roll_ms = 250
silence_timeout_ms = 550
min_speech_ms = 250
max_utterance_seconds = 15.0
interruption_enabled = true
interruption_threshold_rms = 0.08
interruption_min_ms = 120
interruption_calibration_ms = 160
interruption_leak_multiplier = 1.25

[vision]
enabled = true
camera_source = "auto"
camera_device = "/dev/video0"
fps = 5
detector = "haar"
detector_model_path = ""
detector_score_threshold = 0.8
presence_confirm_seconds = 0.8
absence_confirm_seconds = 2.0
dropout_grace_seconds = 0.6
min_confidence = 0.5

[network]
outbound_web_enabled = true
web_search_provider = "ddgs"
web_search_region = "ar-es"

[ai]
provider = "local"
model = "{ai_model}"
max_tokens = 96
timeout_seconds = 60.0
daily_budget_usd = 0.0
allow_cloud = false

[ai.local]
enabled = true
endpoint = "{ai_endpoint}"
model = "{ai_model}"
trusted = true
timeout_seconds = 60.0
context_tokens = 2048

[memory]
sqlite_path = "runtime/lab/ailen_lab.db"
fts_enabled = true
retention_days = 30
auto_vacuum = true

[personality]
description = ""
seed = "ailen-seed-01"
evolution_enabled = true
evolution_rate = 1.0
base_curiosity = 0.7
base_sociability = 0.6
base_formality = 0.4
base_humor = 0.5
base_verbosity = 0.4
base_patience = 0.7
base_expressiveness = 0.6

[social]
default_mode = "workshop"
greeting_cooldown_seconds = 60.0
auto_greeting_enabled = true
public_memory_filter = true
"""


def init_lab_config(
    target_path: Path | None = None,
    force: bool = False,
    stt_engine: str = "vosk",
    tts_voice: str = "es_ES-davefx-medium",
    ai_endpoint: str = "http://127.0.0.1:11434/v1",
    ai_model: str = "qwen3.5:9b",
) -> tuple[Path, bool]:
    """Create isolated runtime/lab/ailen-lab.toml."""
    out_path = target_path or Path("runtime/lab/ailen-lab.toml")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.is_file() and not force:
        return out_path, False

    toml_content = generate_lab_config_toml(
        stt_engine=stt_engine,
        tts_voice=tts_voice,
        ai_endpoint=ai_endpoint,
        ai_model=ai_model,
    )
    out_path.write_text(toml_content, encoding="utf-8")
    return out_path, True

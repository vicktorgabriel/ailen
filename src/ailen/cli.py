"""Command Line Interface (CLI) for AILEN."""

import argparse
import getpass
import json
import logging
import sys
from pathlib import Path
from typing import Any

from ailen.core.config import dump_config_toml, load_config, validate_config
from ailen.core.diagnostics import HardwareDiagnostics, format_hardware_report
from ailen.core.health import HealthService
from ailen.core.logging import setup_logging
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState
from ailen.hardware.detector import HardwareDetector
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.models.catalog import ModelCatalog
from ailen.models.downloader import ModelDownloader, ModelDownloadError
from ailen.models.planner import ModelPlanner
from ailen.models.store import ModelStore
from ailen.runtime.manager import LocalRuntimeManager
from ailen.services.config_service import ConfigService
from ailen.services.settings_service import SettingsService
from ailen.services.status_service import StatusService
from ailen.updates.activation import AppliancePaths
from ailen.updates.factory import build_update_service
from ailen.version import __version__
from ailen.web.app import AILENWebApp
from ailen.web.auth_store import AdminCredentialStore
from ailen.web.persistent_auth import PersistentAuthService
from ailen.web.server import serve as serve_web

MIN_PASSWORD_LENGTH = 8


def create_parser() -> argparse.ArgumentParser:
    """Create top-level CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="ailen",
        description="AILEN - Asistente físico modular para hardware reciclado",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"ailen {__version__}",
    )
    parser.add_argument(
        "-c", "--config",
        dest="config_path",
        help="Path to custom ailen.toml configuration file",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: diagnose
    diag_parser = subparsers.add_parser("diagnose", help="Hardware and audio diagnostics")
    diag_sub = diag_parser.add_subparsers(dest="diag_target", help="Diagnostics target")
    hw_parser = diag_sub.add_parser("hardware", help="Inspect system hardware and recommend profile")
    hw_parser.add_argument("--json", action="store_true", help="Output report as JSON")
    audio_diag_parser = diag_sub.add_parser("audio", help="Inspect audio I/O devices, ALSA status, and STT/TTS health")
    audio_diag_parser.add_argument("--json", action="store_true", help="Output report as JSON")
    ai_diag_parser = diag_sub.add_parser("ai", help="Inspect AI Router, Local, LAN, and Cloud backends")
    ai_diag_parser.add_argument("--json", action="store_true", help="Output report as JSON")

    # Command: config
    cfg_parser = subparsers.add_parser("config", help="Inspect and validate configuration")
    cfg_sub = cfg_parser.add_subparsers(dest="config_action", help="Config action")
    cfg_sub.add_parser("show", help="Display current effective configuration in TOML")
    cfg_sub.add_parser("validate", help="Validate current configuration")
    init_parser = cfg_sub.add_parser("init", help="Initialize a default configuration file")
    init_parser.add_argument(
        "-o", "--output",
        default="config/ailen.toml",
        help="Destination path for the new configuration file",
    )

    # Command: db
    db_parser = subparsers.add_parser("db", help="Database migration management")
    db_sub = db_parser.add_subparsers(dest="db_action", help="Database action")
    db_sub.add_parser("migrate", help="Run all pending SQLite migrations")
    db_sub.add_parser("status", help="Show database migration version")

    # Command: status
    status_parser = subparsers.add_parser("status", help="Display runtime health status")
    status_parser.add_argument("--json", action="store_true", help="Output status as JSON")

    # Command: admin
    admin_parser = subparsers.add_parser("admin", help="Local administration tasks")
    admin_sub = admin_parser.add_subparsers(dest="admin_action", help="Admin action")
    setpw_parser = admin_sub.add_parser(
        "set-password", help="Create or replace the panel admin password (prompted, never an argv flag)"
    )
    setpw_parser.add_argument(
        "--username",
        default="admin",
        help="Admin username (default: admin)",
    )

    # Command: serve
    serve_parser = subparsers.add_parser("serve", help="Run AILEN Core and services")
    serve_parser.add_argument("--host", help="Override web host")
    serve_parser.add_argument("--port", type=int, help="Override web port")

    # Command: demo
    demo_parser = subparsers.add_parser("demo", help="Physical presence, face, and audio diagnostics")
    demo_sub = demo_parser.add_subparsers(dest="demo_target", help="Demo target component")

    # Subcommand: demo face
    demo_face = demo_sub.add_parser("face", help="Run the configured face renderer or automatic FacePack QA")
    demo_face.add_argument("--headless", action="store_true", help="Run headless in terminal without opening GUI window")
    demo_face.add_argument("--gui", action="store_true", help="Force opening GUI window (Tkinter)")
    demo_face.add_argument("--duration", type=float, default=None, help="Run demo for N seconds and exit")
    demo_face.add_argument(
        "--fps",
        type=int,
        default=None,
        help="Target FPS override; defaults to display.fps_limit from config",
    )
    demo_face.add_argument(
        "--style",
        choices=("facepack", "portrait", "pixel", "vector"),
        default=None,
        help="Renderer override; defaults to display.face_style from config (normally facepack)",
    )
    demo_face.add_argument(
        "--showcase",
        action="store_true",
        help="Run automatic FacePack visual QA without AI, audio, or camera",
    )
    demo_face.add_argument(
        "--showcase-filter",
        help="Limit showcase to one category or exact FacePack sequence/state id",
    )
    demo_face.add_argument(
        "--showcase-once",
        action="store_true",
        help="Run one automatic pass, then remain idle until the window is closed",
    )

    # Subcommand: demo vision
    demo_vis = demo_sub.add_parser("vision", help="Camera presence detection and debounce demo")
    demo_vis.add_argument("--camera", default="/dev/video0", help="Camera device path or index (default: /dev/video0)")
    demo_vis.add_argument("--detector", choices=("haar", "yunet"), default="haar", help="Face detector (default: haar)")
    demo_vis.add_argument("--model", default="", help="YuNet ONNX model path when --detector=yunet")
    demo_vis.add_argument("--score", type=float, default=0.8, help="YuNet score threshold 0..1 (default: 0.8)")
    demo_vis.add_argument("--presence-confirm", type=float, default=0.8, help="Seconds to confirm presence")
    demo_vis.add_argument("--absence-confirm", type=float, default=2.0, help="Seconds to confirm absence")
    demo_vis.add_argument("--dropout-grace", type=float, default=0.6, help="Seconds to tolerate detector dropouts")
    demo_vis.add_argument("--duration", type=float, default=10.0, help="Run duration in seconds (default: 10.0)")

    # Subcommand: demo vad
    demo_vad = demo_sub.add_parser("vad", help="Real-time Voice Activity Detection (VAD) demo")
    demo_vad.add_argument("--device", default="default", help="Input device (default: default)")
    demo_vad.add_argument("--threshold", type=float, default=0.02, help="VAD RMS threshold (default: 0.02)")
    demo_vad.add_argument("--duration", type=float, default=5.0, help="Run duration in seconds (default: 5.0)")
    demo_vad.add_argument("--simulate", action="store_true", help="Use synthetic PCM instead of physical microphone")

    # Subcommand: demo stt
    demo_stt = demo_sub.add_parser("stt", help="Speech-to-Text transcription demo")
    demo_stt.add_argument("--device", default="default", help="Input device (default: default)")
    demo_stt.add_argument("--engine", default="mock", help="STT engine (mock, vosk, whisper_cpp)")
    demo_stt.add_argument("--model", default="", help="STT model path")
    demo_stt.add_argument("--duration", type=float, default=6.0, help="Listen duration in seconds (default: 6.0)")
    demo_stt.add_argument("--simulate", action="store_true", help="Use synthetic test input; never enabled implicitly")

    # Subcommand: demo tts
    demo_tts = demo_sub.add_parser("tts", help="Text-to-Speech synthesis demo")
    demo_tts.add_argument("text", help="Text string to synthesize and speak")
    demo_tts.add_argument("--engine", default="mock", help="TTS engine (mock, piper)")
    demo_tts.add_argument("--voice", default="es_ES-standard", help="Voice ID")
    demo_tts.add_argument("--model", default="", help="TTS model path (.onnx)")
    demo_tts.add_argument("--rate", type=float, default=1.0, help="Speech rate (default: 1.0)")

    # Subcommand: demo ai
    demo_ai = demo_sub.add_parser("ai", help="Interactive AI Router and LLM inference demo")
    demo_ai.add_argument("prompt", help="User message / text prompt")
    demo_ai.add_argument("--dry-run", action="store_true", default=False, help="Show routing decision without network calls")
    demo_ai.add_argument("--mode", default="WORKSHOP", help="Social operating mode (HOME, WORKSHOP, SHOP, PUBLIC, PRIVATE, SLEEP)")
    demo_ai.add_argument("--privacy", default="PRIVATE", help="Privacy level (PUBLIC, RESTRICTED, PRIVATE)")
    demo_ai.add_argument("--profile", default=None, help="Override device profile (SATELLITE, CLOUD, HYBRID, LOCAL, LAN_BRAIN)")
    demo_ai.add_argument("--intent", default="chat", help="Request intent (chat, volume, timer, etc.)")

    # Command: lab
    lab_parser = subparsers.add_parser("lab", help="Lab Mode inspection, execution and benchmarks")
    lab_sub = lab_parser.add_subparsers(dest="lab_action", help="Lab action")
    lab_inspect = lab_sub.add_parser("inspect", help="Inspect hardware capabilities, profile and recommended model plan")
    lab_inspect.add_argument("--json", action="store_true", help="Output as JSON")
    lab_start = lab_sub.add_parser("start", help="Boot AILEN in Lab Mode with detected capabilities")
    lab_start.add_argument("--dry-run", action="store_true", default=False, help="Initialize components without entering interactive loop")
    lab_start.add_argument("--headless", action="store_true", default=False, help="Run without graphical face display")
    lab_start.add_argument("--no-camera", action="store_true", default=False, help="Disable vision and camera capture")
    lab_start.add_argument("--no-audio", action="store_true", default=False, help="Disable audio I/O and speech")
    lab_start.add_argument("--no-ai", action="store_true", default=False, help="Disable local AI inference")
    lab_start.add_argument("--simulate", action="store_true", default=False, help="Use synthetic test backends for offline lab simulation")
    lab_start.add_argument("--fullscreen", action="store_true", default=False, help="Display face window in fullscreen mode")
    lab_start.add_argument("--duration", type=float, default=None, help="Run for N seconds and terminate cleanly")
    lab_doctor = lab_sub.add_parser("doctor", help="Run non-invasive system readiness diagnostic")
    lab_doctor.add_argument("--json", action="store_true", help="Output diagnostic report as JSON")
    lab_preflight = lab_sub.add_parser("preflight", help="Run comprehensive preflight check for physical live lab test")
    lab_preflight.add_argument("--json", action="store_true", help="Output preflight report as JSON")
    lab_preflight.add_argument("--headless", action="store_true", default=False, help="Check with headless assumption")
    lab_preflight.add_argument("--no-camera", action="store_true", default=False, help="Check with no-camera assumption")
    lab_preflight.add_argument("--no-audio", action="store_true", default=False, help="Check with no-audio assumption")
    lab_preflight.add_argument("--no-ai", action="store_true", default=False, help="Check with no-ai assumption")
    lab_prepare_ai = lab_sub.add_parser("prepare-ai", help="Inspect and prepare local model and runtime for Lab Mode")
    lab_prepare_ai.add_argument("-y", "--yes", action="store_true", help="Automatically accept downloading missing model artifact")
    lab_prepare_ai.add_argument("--start-runtime", action="store_true", help="Temporarily start/health-check an AILEN-managed llama.cpp runtime, then stop it")
    lab_prepare_ai.add_argument(
        "--activate-selection",
        action="store_true",
        help=(
            "After exact artifact verification, atomically activate this "
            "target-qualified model/runtime for subsequent sessions"
        ),
    )
    lab_prepare_ai.add_argument(
        "--qualification-dir",
        default="runtime/lab/model_qualification/hardware",
        help="Versioned evidence records for this hardware class",
    )
    lab_prep_speech = lab_sub.add_parser("prepare-speech", help="Inspect and prepare STT/TTS models and voice assets for Lab Mode")
    lab_prep_speech.add_argument("-y", "--yes", action="store_true", help="Automatically download approved speech assets")
    lab_prep_speech.add_argument("--stt", choices=["vosk", "whisper_cpp"], default="vosk", help="Target STT engine (default: vosk)")
    lab_prep_speech.add_argument("--voice", default="es_ES-davefx-medium", help="Target Piper voice key")
    lab_cfg_init = lab_sub.add_parser("config", help="Manage isolated lab configuration")
    lab_cfg_sub = lab_cfg_init.add_subparsers(dest="lab_config_action", help="Lab config action")
    lab_cfg_init_p = lab_cfg_sub.add_parser("init", help="Initialize runtime/lab/ailen-lab.toml without touching product config")
    lab_cfg_init_p.add_argument("-f", "--force", action="store_true", help="Overwrite existing lab configuration")
    lab_cfg_init_p.add_argument(
        "--profile",
        required=True,
        choices=(
            "recycled-4gb-local-candidate",
            "recycled-8gb-hybrid",
            "lan-satellite",
            "gpu-lan-brain",
            "external-only",
        ),
        help="Explicit candidate topology; it is not a hardware certification",
    )
    lab_cfg_init_p.add_argument("--stt", choices=["vosk", "whisper_cpp"], default="vosk", help="Target STT engine")
    lab_cfg_init_p.add_argument("--voice", default="es_ES-davefx-medium", help="Target TTS voice key")
    lab_cfg_init_p.add_argument("--local-endpoint", default="", help="Override local Ollama/llama.cpp endpoint")
    lab_cfg_init_p.add_argument("--local-model", default="", help="Override explicit local model ID")
    lab_cfg_init_p.add_argument("--lan-endpoint", default="", help="Override LAN Brain endpoint")
    lab_cfg_init_p.add_argument("--lan-model", default="", help="Override LAN Brain model ID")
    lab_cfg_init_p.add_argument("--lan-trusted", action="store_true", help="Explicitly trust the configured LAN Brain")
    lab_audio = lab_sub.add_parser("audio-devices", help="List audio capture and playback devices with ALSA IDs")
    lab_audio.add_argument("--json", action="store_true", help="Output as JSON")
    lab_cams = lab_sub.add_parser("cameras", help="List detected camera devices and paths")
    lab_cams.add_argument("--json", action="store_true", help="Output as JSON")
    lab_bench = lab_sub.add_parser("benchmark", help="Run reproducible lab benchmark harness")
    lab_bench.add_argument("--output", default="runtime/lab/benchmarks", help="Destination directory for benchmark artifact")
    lab_bench_ai = lab_sub.add_parser("benchmark-ai", help="Benchmark candidate models in local Ollama runtime without downloading")
    lab_bench_ai.add_argument("--models", default="qwen3.5:9b,qwen2.5-coder:3b,llama3.2:3b,gemma3:4b,qwen3.5:4b", help="Comma-separated candidate models to benchmark")
    lab_bench_ai.add_argument("--endpoint", default="http://127.0.0.1:11434/v1", help="Ollama / local server endpoint")
    lab_bench_ai.add_argument("--warmup", type=int, default=1, help="Warmup turns per model (default: 1)")
    lab_bench_ai.add_argument("--turns", type=int, default=None, help="Number of benchmark prompts to evaluate")
    lab_bench_ai.add_argument("--json", action="store_true", help="Output benchmark report as JSON")
    lab_bench_vis = lab_sub.add_parser("benchmark-vision", help="Benchmark face detector latency/detections on real camera (CPU-first, no GUI)")
    lab_bench_vis.add_argument("--camera", default="", help="Camera device path (default from lab config)")
    lab_bench_vis.add_argument("--detector", choices=("haar", "yunet"), default="", help="Face detector (default from lab config)")
    lab_bench_vis.add_argument("--model", default="", help="YuNet ONNX model path when --detector=yunet")
    lab_bench_vis.add_argument("--score", type=float, default=0.0, help="YuNet score threshold 0..1 (0 keeps config default)")
    lab_bench_vis.add_argument("--fps", type=int, default=5, help="Requested capture FPS (default: 5)")
    lab_bench_vis.add_argument("--frames", type=int, default=150, help="Number of frames to sample (default: 150)")
    lab_bench_vis.add_argument("--phase", choices=("uncontrolled", "empty", "face", "movement"), default="uncontrolled", help="Scene phase label; use uncontrolled when ground truth is unknown")
    lab_bench_vis.add_argument("--timeout", type=float, default=120.0, help="Max seconds to wait for frames (default: 120)")
    lab_bench_vis.add_argument("--output", default="runtime/lab/vision_benchmarks", help="Directory for JSON report artifact")
    lab_bench_vis.add_argument("--json", action="store_true", help="Print report as JSON instead of table")
    lab_bench_stt = lab_sub.add_parser("benchmark-stt", help="Benchmark STT engines (Vosk vs whisper.cpp) over WAV files; never downloads models")
    lab_bench_stt.add_argument("--wav", action="append", default=[], help="Path to a 16 kHz mono PCM16 WAV file (repeatable)")
    lab_bench_stt.add_argument("--engines", default="vosk,whisper_cpp", help="Comma-separated engines to compare (default: vosk,whisper_cpp)")
    lab_bench_stt.add_argument("--reference", default="", help="Expected transcript text for WER computation")
    lab_bench_stt.add_argument("--record", type=float, default=0.0, help="Record N seconds from mic into --out WAV before benchmarking (explicit operator consent)")
    lab_bench_stt.add_argument("--out", default="", help="WAV output path for --record (required with --record)")
    lab_bench_stt.add_argument("--audio-device", default="default", help="ALSA capture device for --record (default: default)")
    lab_bench_stt.add_argument("--vosk-model", default="", help="Vosk model directory (default from lab config)")
    lab_bench_stt.add_argument("--whisper-binary", default="whisper-cli", help="whisper.cpp binary name/path")
    lab_bench_stt.add_argument("--whisper-model", default="", help="whisper.cpp ggml model file path")
    lab_bench_stt.add_argument("--json", action="store_true", help="Print results as JSON")
    lab_calibrate_voice = lab_sub.add_parser(
        "calibrate-voice",
        help="Guided RAM-only WebRTC VAD + Vosk physical calibration",
    )
    lab_calibrate_voice.add_argument(
        "--device",
        action="append",
        default=[],
        help=(
            "Exact capture endpoint override (repeatable); without it, discover a "
            "bounded set of default/physical/Easy Effects sources"
        ),
    )
    lab_calibrate_voice.add_argument(
        "--capture-gains",
        default="",
        help="Comma-separated bounded digital gains in dB (default: active config only)",
    )
    lab_calibrate_voice.add_argument(
        "--auto-gain-modes",
        default="",
        help="Comma-separated off,on modes (default: active config only)",
    )
    lab_calibrate_voice.add_argument(
        "--distances-cm",
        default="30,75,100",
        help="Comma-separated operator distances (default: 30,75,100 cm)",
    )
    lab_calibrate_voice.add_argument(
        "--processing-profiles",
        default="raw,noise_only,full",
        help="Comma-separated raw,noise_only,full capture profiles",
    )
    lab_calibrate_voice.add_argument(
        "--silence-seconds",
        type=float,
        default=2.5,
        help="RAM-only noise phase before each phrase (default: 2.5 s)",
    )
    lab_calibrate_voice.add_argument("--vad-modes", default="2,3", help="Comma-separated WebRTC modes")
    lab_calibrate_voice.add_argument(
        "--silence-timeouts",
        default="380,500,600",
        help="Comma-separated utterance close times in milliseconds",
    )
    lab_calibrate_voice.add_argument("--limit", type=int, default=0, help="Use only the first N public cases")
    lab_calibrate_voice.add_argument("--max-wait", type=float, default=18.0, help="Bounded seconds per sample")
    lab_calibrate_voice.add_argument(
        "--barge-in-only",
        action="store_true",
        help="Run only the guided early/middle/late physical interruption trials",
    )
    lab_calibrate_voice.add_argument(
        "--barge-in-timeout",
        type=float,
        default=15.0,
        help="Bounded seconds to wait for the preserved interruption transcript",
    )
    lab_calibrate_voice.add_argument(
        "--output",
        default="runtime/lab/voice_validation",
        help="Metrics destination; PCM is never written here",
    )
    lab_calibrate_voice.add_argument("--list-cases", action="store_true", help="Print matrix without opening audio")
    lab_calibrate_voice.add_argument("--json", action="store_true", help="JSON output for --list-cases")

    # Command: speech
    speech_parser = subparsers.add_parser("speech", help="Manage offline speech assets (Vosk, Whisper, Piper voices)")
    speech_sub = speech_parser.add_subparsers(dest="speech_action", help="Speech action")
    speech_list = speech_sub.add_parser("list", help="List all catalog speech assets (STT models, TTS voices)")
    speech_list.add_argument("--json", action="store_true", help="Output as JSON")
    speech_list.add_argument("--engine", help="Filter by engine (vosk, whisper_cpp, piper)")
    speech_plan = speech_sub.add_parser("plan", help="Show recommended STT and TTS models for speech pipeline")
    speech_plan.add_argument("--stt", default="vosk", help="Target STT engine (vosk, whisper_cpp)")
    speech_plan.add_argument("--voice", default="es_ES-davefx-medium", help="Target TTS voice key")
    speech_plan.add_argument("--json", action="store_true", help="Output as JSON")
    speech_fetch = speech_sub.add_parser("fetch", help="Download and verify a speech asset into SpeechAssetStore")
    speech_fetch.add_argument("asset_id", help="Speech asset ID (e.g. vosk-model-small-es-0.42, es_ES-davefx-medium)")
    speech_fetch.add_argument("-y", "--yes", action="store_true", help="Accept download confirmation")
    speech_verify = speech_sub.add_parser("verify", help="Verify SHA-256 checksum of an installed speech asset")
    speech_verify.add_argument("asset_id", help="Speech asset ID to verify")

    # Command: models
    models_parser = subparsers.add_parser("models", help="Manage local GGUF model catalog and storage")
    models_sub = models_parser.add_subparsers(dest="models_action", help="Models action")
    models_list = models_sub.add_parser("list", help="List all catalog models and installation status")
    models_list.add_argument("--json", action="store_true", help="Output as JSON")
    models_plan = models_sub.add_parser("plan", help="Evaluate hardware capabilities and output recommended model plan")
    models_plan.add_argument("--json", action="store_true", help="Output as JSON")
    models_plan.add_argument("--purpose", choices=["SANITY", "BALANCED", "QUALITY"], default="BALANCED", help="Model execution purpose")
    models_plan.add_argument("--all", action="store_true", help="Include non-downloadable metadata candidates")
    models_provision = models_sub.add_parser(
        "provision-plan",
        help="Build a consent-gated install plan from detected hardware and qualification evidence",
    )
    models_provision.add_argument(
        "--topology",
        choices=("hybrid", "local", "lan-satellite", "gpu-lan-brain", "external-only"),
        default="hybrid",
    )
    models_provision.add_argument(
        "--qualification-dir",
        default="runtime/lab/model_qualification/hardware",
        help="Directory containing versioned target-hardware qualification records",
    )
    models_provision.add_argument(
        "--model-override",
        default="",
        help="Explicit lab candidate override; never promotes it to qualified",
    )
    models_provision.add_argument("--json", action="store_true", help="Output as JSON")
    models_fetch = models_sub.add_parser("fetch", help="Download and verify a model from catalog")
    models_fetch.add_argument("model_id", help="Model ID from catalog (e.g. qwen3.5-0.8b-q4_0)")
    models_fetch.add_argument("-y", "--yes", action="store_true", help="Bypass interactive confirmation prompt")
    models_verify = models_sub.add_parser("verify", help="Verify SHA-256 integrity of an installed model")
    models_verify.add_argument("model_id", help="Model ID to verify in local store")
    models_qualification = models_sub.add_parser(
        "qualification-template",
        help="Create an evidence manifest; never download model weights",
    )
    models_qualification.add_argument("model_id", help="Candidate model ID from the catalog")
    models_qualification.add_argument(
        "--output",
        default="",
        help="Output JSON (default: runtime/lab/model_qualification/<model>.json)",
    )
    models_qualification.add_argument("--force", action="store_true", help="Replace an existing manifest")
    models_qualification_validate = models_sub.add_parser(
        "qualification-validate",
        help="Validate evidence and report candidate/qualified status",
    )
    models_qualification_validate.add_argument("manifest", help="Qualification JSON path")

    return parser


def cmd_diagnose_hardware(args: argparse.Namespace) -> int:
    """Execute hardware diagnostics."""
    diagnostics = HardwareDiagnostics()
    report = diagnostics.run()
    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_hardware_report(report))
    return 0


def cmd_config(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute config subcommand."""
    action = args.config_action
    if action == "show":
        cfg = load_config(config_path)
        print(dump_config_toml(cfg))
        return 0
    elif action == "validate":
        cfg = load_config(config_path)
        errors = validate_config(cfg)
        if errors:
            print("Configuration validation FAILED:")
            for err in errors:
                print(f"  - {err}")
            return 1
        print("Configuration is VALID.")
        return 0
    elif action == "init":
        out_path = Path(args.output)
        if out_path.exists():
            print(f"Error: Target file {out_path} already exists. Remove it or specify a different output path.")
            return 1
        cfg = load_config(None)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(dump_config_toml(cfg), encoding="utf-8")
        print(f"Initialized configuration at: {out_path}")
        return 0
    else:
        print("Use: ailen config [show|validate|init]")
        return 1


def cmd_db(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute db subcommand."""
    action = args.db_action
    cfg = load_config(config_path)
    db_mgr = SQLiteManager(cfg.memory.sqlite_path)
    runner = MigrationRunner(db_mgr)

    if action == "migrate":
        applied = runner.run_migrations()
        print(f"Applied {applied} migration(s). Current database version: {runner.get_current_version()}")
        return 0
    elif action == "status":
        curr_ver = runner.get_current_version()
        available = runner.get_available_migrations()
        print(f"Database path: {cfg.memory.sqlite_path}")
        print(f"Current schema version: {curr_ver}")
        print(f"Available migrations: {len(available)}")
        return 0
    else:
        print("Use: ailen db [migrate|status]")
        return 1


def cmd_status(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute status subcommand."""
    cfg = load_config(config_path)
    health = HealthService(node_id=cfg.node.node_id, profile=cfg.node.profile)
    health.set_assistant_state(AssistantState.IDLE)
    state = health.get_runtime_state()

    if getattr(args, "json", False):
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
    else:
        print("==================================================================")
        print(f" AILEN Runtime Status — Node: {state.node_id}")
        print("==================================================================")
        print(f" Version         : {state.version}")
        print(f" Profile         : {state.profile.value}")
        print(f" State           : {state.assistant_state.value}")
        print(f" Uptime          : {state.uptime_seconds}s")
        print(f" Memory DB       : {state.memory_status.value}")
        print(f" Audio           : {state.microphone_status.value}")
        print(f" Vision          : {state.camera_status.value}")
        print(f" AI Router       : {state.cloud_status.value}")
        print("==================================================================")
    return 0


def cmd_admin_set_password(args: argparse.Namespace, config_path: str | None) -> int:
    """Create/replace the persistent admin credential.

    El password se lee por getpass (stdin seguro): nunca como argumento CLI,
    porque argv es visible para otros procesos vía `ps`.
    """
    username = getattr(args, "username", "admin") or "admin"
    print(f"Configurando credencial administrativa del panel (usuario: {username}).")
    password = getpass.getpass("Nueva contraseña: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Error: la contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
        return 1
    confirm = getpass.getpass("Repetir contraseña: ")
    if password != confirm:
        print("Error: las contraseñas no coinciden.")
        return 1

    cfg = load_config(config_path)
    db_mgr = SQLiteManager(cfg.memory.sqlite_path)
    runner = MigrationRunner(db_mgr)
    runner.run_migrations()  # asegura tabla admin_credentials (migración 0002)
    auth = PersistentAuthService(AdminCredentialStore(db_mgr))
    auth.set_password(password, username=username)
    print(f"Credencial actualizada en {cfg.memory.sqlite_path}. El panel ya acepta login.")
    return 0


def cmd_serve(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute serve command to start AILEN Foundation runtime."""
    cfg = load_config(config_path)
    setup_logging(cfg.logging)
    logger = logging.getLogger("ailen.runtime")

    logger.info("Starting AILEN Foundation v%s...", __version__)
    logger.info("Node ID: %s | Profile: %s", cfg.node.node_id, cfg.node.profile.value)

    # 1. Initialize SQLite and run migrations
    db_mgr = SQLiteManager(cfg.memory.sqlite_path)
    migration_runner = MigrationRunner(db_mgr)
    applied = migration_runner.run_migrations()
    logger.info("Database initialized at %s (schema v%d, %d applied)", cfg.memory.sqlite_path, migration_runner.get_current_version(), applied)

    # 2. Initialize State and Health Services
    state_mgr = StateManager(AssistantState.BOOTING)
    health = HealthService(node_id=cfg.node.node_id, profile=cfg.node.profile)

    state_mgr.transition_to(AssistantState.IDLE, reason="Bootstrap completed")
    health.set_assistant_state(AssistantState.IDLE)

    logger.info("AILEN Foundation Core is READY in state IDLE.")

    # 3. Run the local responsive admin panel using real Foundation status,
    # persistent admin auth (SQLite) and the settings contract. Sin credencial
    # configurada el panel queda fail-closed: sólo muestra instrucciones.
    if not cfg.web.enabled:
        logger.warning("Web panel disabled by configuration; no long-running transport is active yet.")
        print(f"AILEN Foundation v{__version__} initialized with web disabled.")
        return 0

    host = args.host or cfg.web.host
    port = args.port or cfg.web.port
    db_mgr = SQLiteManager(cfg.memory.sqlite_path)
    auth = PersistentAuthService(
        AdminCredentialStore(db_mgr),
        session_ttl_seconds=float(cfg.web.session_expiry_hours) * 3600.0,
    )
    if not auth.configured:
        logger.warning("Sin credencial administrativa; el panel queda en modo cerrado.")
        print(
            "AILEN: no hay contraseña de administración configurada.\n"
            "Ejecutá `ailen admin set-password` y volvé a levantar el panel."
        )
    # serve owns the admin process, not the separate Lab audio/vision/AI runtime.
    from ailen.domain.enums import ServiceStatus
    from ailen.memory.repository import MemoryRepository
    from ailen.services.diagnostics_admin_service import DiagnosticsAdminService
    from ailen.services.memory_admin_service import MemoryAdminService

    for component in ("display", "audio", "vision", "ai"):
        health.set_component_status(component, ServiceStatus.UNKNOWN)
    health.set_component_status(
        "memory", ServiceStatus.HEALTHY if db_mgr.check_health() else ServiceStatus.UNHEALTHY,
    )
    status = StatusService(health_service=health)
    config_service = ConfigService(config_path)
    settings = SettingsService(config_service)
    update_root = (Path("runtime/lab/update-simulation")).resolve()
    update_service = build_update_service(
        cfg,
        mode="lab",
        paths=AppliancePaths(
            install_root=update_root / "install",
            state_root=update_root / "state",
        ),
    )
    try:
        from ailen.audio.alsa_backend import AlsaAudioInputBackend, AlsaDeviceEnumerator
        from ailen.audio.calibration import PcmNoiseCalibrator
        from ailen.audio.level import build_capture_processor

        observed_default = AlsaDeviceEnumerator().get_default_route(is_input=True)
        observed_source = cfg.audio.input_device
        if cfg.audio.input_device in {"auto", "default", "pipewire"} and observed_default:
            observed_source = f"pipewire:{observed_default}"
        noise_calibrator = PcmNoiseCalibrator(
            input_factory=lambda: AlsaAudioInputBackend(
                device=cfg.audio.input_device,
                sample_rate=cfg.audio.sample_rate,
                channels=cfg.audio.channels,
                frame_ms=cfg.audio.frame_ms,
            ),
            duration_seconds=3.0,
            frame_ms=cfg.audio.frame_ms,
            source_label=observed_source,
            frame_processor=build_capture_processor(
                sample_rate=cfg.audio.sample_rate,
                channels=cfg.audio.channels,
                frame_ms=cfg.audio.frame_ms,
                capture_gain_db=cfg.audio.capture_gain_db,
                auto_gain_enabled=cfg.audio.auto_gain_enabled,
                auto_gain_target_rms=cfg.audio.auto_gain_target_rms,
                max_auto_gain_db=cfg.audio.max_auto_gain_db,
                auto_gain_attack_ms=cfg.audio.auto_gain_attack_ms,
                auto_gain_release_ms=cfg.audio.auto_gain_release_ms,
                auto_gain_noise_gate_rms=cfg.audio.auto_gain_noise_gate_rms,
                auto_gain_gate_hold_ms=cfg.audio.auto_gain_gate_hold_ms,
                capture_limiter_peak=cfg.audio.capture_limiter_peak,
                noise_suppression_engine=cfg.speech.noise_suppression_engine,
                noise_suppression_level=cfg.speech.noise_suppression_level,
                input_processing_mode=cfg.audio.input_processing_mode,
                input_device=cfg.audio.input_device,
                effective_source=observed_source,
            ),
        )
        app = AILENWebApp(
            auth=auth,
            status=status,
            settings=settings,
            updates=update_service,
            noise_calibrator=noise_calibrator,
            memory=MemoryAdminService(MemoryRepository(db_mgr)),
            diagnostics=DiagnosticsAdminService(
                status, settings.get_config, reports_dir=Path("runtime/lab"),
            ),
        )

        logger.info("Starting AILEN web panel on %s:%d", host, port)
        print(
            f"AILEN Foundation v{__version__} running at http://{host}:{port}. "
            "Press Ctrl+C to stop."
        )
        serve_web(app, host=host, port=port)
    finally:
        update_service.close()
    return 0


def cmd_demo_face(args: argparse.Namespace, config_path: str | None) -> int:
    """Run the canonical configured Face path, optionally with automatic QA."""

    import time

    from ailen.face.showcase import FacePackShowcase
    from ailen.runtime.factory import LabComponentFactory

    force_headless = bool(getattr(args, "headless", False))
    force_gui = bool(getattr(args, "gui", False))
    showcase_enabled = bool(getattr(args, "showcase", False))
    duration = getattr(args, "duration", None)
    cfg = load_config(config_path)
    fps_override = getattr(args, "fps", None)
    fps = max(1, int(fps_override if fps_override is not None else cfg.display.fps_limit))
    style_override = getattr(args, "style", None)
    style = str(style_override or cfg.display.face_style)
    if showcase_enabled and style != "facepack":
        print("Error: --showcase requiere --style facepack o display.face_style=facepack.")
        return 2
    if force_headless and showcase_enabled:
        print("Error: el showcase visual no puede ejecutarse con --headless.")
        return 2

    cfg.display.face_style = style
    if fps_override is not None:
        cfg.display.fps_limit = fps
    controller, status = LabComponentFactory(cfg).build_face(headless=force_headless)
    print("==========================================================")
    print(f" AILEN Face — backend={status.backend} state={status.state}")
    print(f" {status.detail}")
    print(" Cierre: Ctrl+C o cerrar la ventana. No hay controles manuales de gestos.")
    print("==========================================================")

    if force_headless:
        print("Face headless activo: no se anuncian ni simulan expresiones visibles.")
        close = getattr(controller, "close", None)
        if callable(close):
            close()
        return 0

    start_window = getattr(controller, "start_window", None)
    if not callable(start_window):
        print("Face display no disponible; AILEN permanece headless/degraded.")
        return 2 if force_gui or showcase_enabled else 0

    showcase: FacePackShowcase | None = None
    try:
        start_window(interactive_keys=False)
        if not controller.is_display_active():
            print("Face display no disponible; AILEN permanece headless/degraded.")
            return 2 if force_gui or showcase_enabled else 0
        if showcase_enabled:
            showcase = FacePackShowcase(
                controller,
                filter_value=getattr(args, "showcase_filter", None),
                loop=not bool(getattr(args, "showcase_once", False)),
            )
            showcase.start()
        started = time.monotonic()
        while controller.is_display_active():
            update = getattr(controller, "update", None)
            if callable(update):
                update()
            if showcase is not None:
                showcase.update()
            if duration is not None and time.monotonic() - started >= max(0.0, duration):
                break
            time.sleep(min(0.01, 0.5 / fps))
    except KeyboardInterrupt:
        print("\nFace detenido por el usuario.")
    except Exception as exc:  # noqa: BLE001
        print(f"Face display falló y queda headless/degraded: {type(exc).__name__}: {exc}")
        return 2
    finally:
        if showcase is not None:
            showcase.close()
        close = getattr(controller, "close", None)
        if callable(close):
            close()
    return 0


def cmd_demo_vision(args: argparse.Namespace, config_path: str | None) -> int:
    """Run camera presence detection and debounce demo."""
    import time

    from ailen.vision.debouncer import VisionDebouncer
    from ailen.vision.opencv_backend import OpenCvVisionBackend

    camera_dev = getattr(args, "camera", "/dev/video0")
    detector = str(getattr(args, "detector", "haar"))
    model_path = str(getattr(args, "model", ""))
    score_threshold = float(getattr(args, "score", 0.8))
    presence_confirm = float(getattr(args, "presence_confirm", 0.8))
    absence_confirm = float(getattr(args, "absence_confirm", 2.0))
    dropout_grace = float(getattr(args, "dropout_grace", 0.6))
    duration = float(getattr(args, "duration", 10.0))

    backend = OpenCvVisionBackend(
        camera_device=camera_dev,
        fps=5,
        detector=detector,
        yunet_model_path=model_path,
        yunet_score_threshold=score_threshold,
    )
    debouncer = VisionDebouncer(
        presence_confirm_seconds=presence_confirm,
        absence_confirm_seconds=absence_confirm,
        dropout_grace_seconds=dropout_grace,
    )

    print("==========================================================")
    print(" AILEN Vision POC — Demo de Presencia y Debounce")
    print(
        f" Dispositivo: {camera_dev} | Detector: {detector} | "
        f"Presencia: {presence_confirm}s | Ausencia: {absence_confirm}s | "
        f"Gracia: {dropout_grace}s | Duración: {duration}s"
    )
    print("==========================================================")

    backend.start()
    health = backend.health()
    print(f"Estado del backend: {health.status.value} ({health.detail})")
    if health.status.value != "HEALTHY":
        backend.stop()
        print("ERROR: Vision backend is not healthy; physical camera test aborted.")
        return 1

    start_t = time.time()
    samples = 0
    raw_hits = 0
    stable_hits = 0
    stable_transitions = 0
    last_stable = False
    gaze_x_values: list[float] = []
    gaze_y_values: list[float] = []
    try:
        while time.time() - start_t < duration:
            raw = backend.get_latest_presence()
            stable = debouncer.update(raw)
            elapsed = time.time() - start_t
            samples += 1
            raw_hits += int(raw.present)
            stable_hits += int(stable.present)
            if stable.present != last_stable:
                stable_transitions += 1
                last_stable = stable.present
            if stable.present and stable.primary_x_normalized is not None:
                gaze_x_values.append(stable.primary_x_normalized)
            if stable.present and stable.primary_y_normalized is not None:
                gaze_y_values.append(stable.primary_y_normalized)
            confidence_text = f" conf={raw.confidence:.3f}" if raw.confidence is not None else ""
            print(
                f"[{elapsed:4.1f}s] Raw present={raw.present!s:5} (Caras: {raw.faces_count}){confidence_text} "
                f"--> Debounced present={stable.present!s:5} "
                f"| Gaze=({stable.primary_x_normalized or 0.0:+.2f}, {stable.primary_y_normalized or 0.0:+.2f})"
            )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nDemo vision interrumpida.")
    finally:
        backend.stop()

    raw_rate = (100.0 * raw_hits / samples) if samples else 0.0
    stable_rate = (100.0 * stable_hits / samples) if samples else 0.0
    print("----------------------------------------------------------")
    print(
        f"Resumen: muestras={samples}, detección_raw={raw_hits}/{samples} ({raw_rate:.1f}%), "
        f"presencia_estable={stable_hits}/{samples} ({stable_rate:.1f}%), "
        f"transiciones={stable_transitions}"
    )
    if gaze_x_values and gaze_y_values:
        print(
            f"Rango gaze: x=[{min(gaze_x_values):+.2f}, {max(gaze_x_values):+.2f}] "
            f"y=[{min(gaze_y_values):+.2f}, {max(gaze_y_values):+.2f}]"
        )
    print("Demo vision completada.")
    return 0


def cmd_diagnose_audio(args: argparse.Namespace, config_path: str | None) -> int:
    """Run audio input, output, ALSA, and speech engine diagnostics."""
    import shutil

    from ailen.audio.alsa_backend import AlsaDeviceEnumerator
    from ailen.audio.piper_backend import PiperTtsBackend
    from ailen.audio.vosk_backend import VoskSttBackend
    from ailen.audio.whisper_backend import WhisperCppSttBackend
    from ailen.core.config import load_config

    cfg = load_config(config_path)
    enumerator = AlsaDeviceEnumerator()
    devices = enumerator.list_devices()

    has_arecord = shutil.which("arecord") is not None
    has_aplay = shutil.which("aplay") is not None

    vosk_health = VoskSttBackend(model_path=cfg.speech.stt_model_path).health()
    whisper_health = WhisperCppSttBackend(model_path=cfg.speech.stt_model_path).health()
    piper_health = PiperTtsBackend(model_path=cfg.speech.tts_model_path).health()

    report: dict[str, Any] = {
        "alsa_system": {
            "arecord_available": has_arecord,
            "aplay_available": has_aplay,
            "canonical_format": "PCM 16-bit LE, 1 channel (mono), 16000 Hz",
        },
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "is_input": d.is_input,
                "is_output": d.is_output,
                "is_default": d.is_default,
            }
            for d in devices
        ],
        "speech_engines": {
            "configured_stt": cfg.speech.stt_engine,
            "configured_tts": cfg.speech.tts_engine,
            "configured_voice": cfg.speech.tts_voice,
            "vosk_stt": {"status": vosk_health.status.value, "detail": vosk_health.detail},
            "whisper_stt": {"status": whisper_health.status.value, "detail": whisper_health.detail},
            "piper_tts": {"status": piper_health.status.value, "detail": piper_health.detail},
        },
    }

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print(" AILEN Audio Diagnostics — Audio I/O & Speech Engines")
    print("==================================================================")
    print(f" ALSA arecord (Input)   : {'DISPONIBLE' if has_arecord else 'NO ENCONTRADO (alsa-utils)'}")
    print(f" ALSA aplay (Output)    : {'DISPONIBLE' if has_aplay else 'NO ENCONTRADO (alsa-utils)'}")
    print(f" Canonical Audio Format : {report['alsa_system']['canonical_format']}")
    print("------------------------------------------------------------------")
    print(" Dispositivos de Audio detectados:")
    for d in devices:
        dtype = "IN/OUT" if (d.is_input and d.is_output) else ("INPUT " if d.is_input else "OUTPUT")
        default_tag = " (DEFAULT)" if d.is_default else ""
        print(f"   [{dtype}] {d.id:20} : {d.name}{default_tag}")
    print("------------------------------------------------------------------")
    print(f" STT Configurado: {cfg.speech.stt_engine} | Vosk: {vosk_health.status.value} | Whisper: {whisper_health.status.value}")
    print(f" TTS Configurado: {cfg.speech.tts_engine} ({cfg.speech.tts_voice}) | Piper: {piper_health.status.value}")
    print("==================================================================")
    return 0


def cmd_diagnose_ai(args: argparse.Namespace, config_path: str | None) -> int:
    """Inspect local, LAN and named remote providers without inventing health."""

    from ailen.ai.budget import BudgetPolicy
    from ailen.ai.contracts import BackendHealth
    from ailen.ai.lan_backend import LanBrainAiBackend
    from ailen.ai.local_backend import LocalAiBackend
    from ailen.ai.remote_backend import build_remote_backend
    from ailen.ai.secrets import SecretResolver
    from ailen.core.config import load_config
    from ailen.domain.enums import ServiceStatus
    from ailen.infrastructure.sqlite.connection import SQLiteManager
    from ailen.infrastructure.sqlite.migrations import MigrationRunner
    from ailen.memory.repository import MemoryRepository

    cfg = load_config(config_path)
    db_mgr = SQLiteManager(cfg.memory.sqlite_path)
    MigrationRunner(db_mgr).run_migrations()
    repository = MemoryRepository(db_mgr)

    disabled_health = BackendHealth(ServiceStatus.DISABLED, "Disabled in config")
    local_health = disabled_health
    if cfg.ai.local.enabled:
        local_health = LocalAiBackend(
            endpoint=cfg.ai.local.endpoint,
            model=cfg.ai.local.model,
            timeout_seconds=cfg.ai.local.timeout_seconds,
        ).health()

    lan_health = disabled_health
    if cfg.ai.lan.enabled:
        lan_health = LanBrainAiBackend(
            endpoint=cfg.ai.lan.endpoint,
            model=cfg.ai.lan.model,
            trusted=cfg.ai.lan.trusted,
            timeout_seconds=cfg.ai.lan.timeout_seconds,
        ).health()

    resolver = SecretResolver()
    remote_report: dict[str, dict[str, object]] = {}
    for provider_id, remote in sorted(
        cfg.ai.remote.providers.items(),
        key=lambda item: (item[1].priority, item[0]),
    ):
        has_key = remote.auth_mode == "none" or resolver.has_secret(
            env_var=remote.api_key_env or None,
            file_name=remote.api_key_file or None,
        )
        status = disabled_health
        if cfg.ai.allow_remote and cfg.ai.remote.enabled and remote.enabled:
            backend = build_remote_backend(
                provider_id,
                remote,
                api_key=resolver.resolve(
                    env_var=remote.api_key_env or None,
                    file_name=remote.api_key_file or None,
                ),
            )
            status = backend.health()
        budget = BudgetPolicy(
            repository=repository,
            provider=f"remote:{provider_id}",
            daily_budget_usd=remote.daily_budget_usd,
            monthly_budget_usd=remote.monthly_budget_usd,
        )
        available, reason, spending = budget.is_budget_available()
        remote_report[provider_id] = {
            "enabled": remote.enabled,
            "protocol": remote.protocol,
            "endpoint": remote.endpoint,
            "model": remote.model,
            "priority": remote.priority,
            "credential_configured": has_key,
            "status": status.status.value,
            "detail": status.detail,
            "qualification_status": remote.qualification_status,
            "voice_realtime_eligible": remote.voice_realtime_eligible,
            "budget_available": available,
            "budget_reason": reason,
            "daily_spent_usd": spending["daily_spent_usd"],
            "monthly_spent_usd": spending["monthly_spent_usd"],
        }

    report: dict[str, Any] = {
        "node_profile": cfg.node.profile.value,
        "preferred_provider": cfg.ai.provider,
        "allow_remote": cfg.ai.allow_remote,
        "local": {
            "enabled": cfg.ai.local.enabled,
            "endpoint": cfg.ai.local.endpoint,
            "model": cfg.ai.local.model,
            "status": local_health.status.value,
            "detail": local_health.detail,
        },
        "lan_brain": {
            "enabled": cfg.ai.lan.enabled,
            "endpoint": cfg.ai.lan.endpoint,
            "model": cfg.ai.lan.model,
            "trusted": cfg.ai.lan.trusted,
            "status": lan_health.status.value,
            "detail": lan_health.detail,
        },
        "remote_providers": remote_report,
    }
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print(" AILEN AI Diagnostics — local / LAN / named remote providers")
    print("==================================================================")
    print(f" Perfil              : {cfg.node.profile.value}")
    print(f" Preferencia         : {cfg.ai.provider}")
    print(f" Local               : {local_health.status.value} · {local_health.detail}")
    print(f" LAN Brain           : {lan_health.status.value} · {lan_health.detail}")
    for provider_id, data in remote_report.items():
        print(
            f" remote:{provider_id:<20} {data['status']} · "
            f"model={data['model'] or 'manual/no configurado'} · "
            f"qualified={data['qualification_status']} · "
            f"credential={'yes' if data['credential_configured'] else 'no'}"
        )
    print("==================================================================")
    return 0


def cmd_demo_vad(args: argparse.Namespace) -> int:
    """Run real-time or synthetic VAD demo."""
    import time

    from ailen.audio.alsa_backend import AlsaAudioInputBackend
    from ailen.audio.pcm import compute_pcm_rms, generate_tone_pcm
    from ailen.audio.vad import EnergyVad

    device = getattr(args, "device", "default")
    threshold = float(getattr(args, "threshold", 0.02))
    duration = float(getattr(args, "duration", 5.0))

    backend = AlsaAudioInputBackend(device=device, sample_rate=16000, channels=1, frame_ms=20.0)
    vad = EnergyVad(threshold_rms=threshold)

    print("==========================================================")
    print(" AILEN Audio POC — Demo de VAD (Voice Activity Detection)")
    print(f" Dispositivo: {device} | Umbral RMS: {threshold} | Duración: {duration}s")
    print(" Presioná Ctrl+C para detener.")
    print("==========================================================")

    simulate = bool(getattr(args, "simulate", False))
    backend.start()
    health = backend.health()
    if not simulate and health.status.value != "HEALTHY":
        backend.stop()
        print(
            f"ERROR: el micrófono ALSA no pudo abrirse: {health.status.value} ({health.detail}). "
            "No se usará audio sintético. Use --simulate sólo si desea una prueba lógica."
        )
        return 1
    if simulate:
        print("SIMULATION MODE: la entrada física no participa en esta prueba.")

    start_t = time.time()
    try:
        step = 0
        while time.time() - start_t < duration:
            step += 1
            if not simulate:
                frame = backend.read_frame(timeout_seconds=0.05)
            else:
                # Alternate 1.5s silence and 1.0s tone (voice simulation)
                now_s = time.time() - start_t
                is_tone = (now_s % 2.5) > 1.5
                frame = generate_tone_pcm(440.0, 20.0, amplitude=0.08) if is_tone else b"\x00\x00" * 320
                time.sleep(0.02)

            if frame is None:
                continue

            res = vad.process_frame(frame)
            rms = compute_pcm_rms(frame)
            bars = int(min(20, rms * 200))
            meter = "|" * bars + "." * (20 - bars)
            status = "VOICE  [🗣️]" if res.is_speech else "SILENCE[  ]"
            elapsed = time.time() - start_t
            print(f"[{elapsed:4.1f}s] RMS: {rms:.4f} [{meter}] --> {status}")
    except KeyboardInterrupt:
        print("\nDemo VAD interrumpida.")
    finally:
        backend.stop()

    print("Demo VAD completada.")
    return 0


def cmd_demo_stt(args: argparse.Namespace, config_path: str | None) -> int:
    """Run Speech-to-Text transcription demo."""
    import time

    from ailen.audio.alsa_backend import AlsaAudioInputBackend
    from ailen.audio.coordinator import AudioInteractionCoordinator
    from ailen.audio.fake import FakeAudioInputBackend, FakeSttBackend
    from ailen.audio.pcm import generate_tone_pcm
    from ailen.audio.vosk_backend import VoskSttBackend
    from ailen.audio.whisper_backend import WhisperCppSttBackend
    from ailen.core.config import load_config

    cfg = load_config(config_path)
    engine = getattr(args, "engine", cfg.speech.stt_engine)
    model_path = getattr(args, "model", cfg.speech.stt_model_path)
    device = getattr(args, "device", cfg.audio.input_device)
    duration = float(getattr(args, "duration", 6.0))

    # Select STT backend
    stt_backend: Any
    if engine == "vosk":
        stt_backend = VoskSttBackend(model_path=model_path)
    elif engine == "whisper_cpp":
        stt_backend = WhisperCppSttBackend(model_path=model_path)
    else:
        stt_backend = FakeSttBackend(canned_text="Hola AILEN demo stt")

    simulate = bool(getattr(args, "simulate", False))
    if engine == "mock" and not simulate:
        print("ERROR: STT 'mock' no es una validación física. Use --engine vosk/whisper_cpp o --simulate.")
        return 1

    alsa_in = AlsaAudioInputBackend(device=device, sample_rate=16000, channels=1)
    alsa_in.start()
    is_real = alsa_in.health().status.value == "HEALTHY"
    alsa_health = alsa_in.health()
    alsa_in.stop()

    if not simulate and not is_real:
        print(
            f"ERROR: el micrófono ALSA no pudo abrirse: {alsa_health.status.value} "
            f"({alsa_health.detail}). No se inyectará audio sintético."
        )
        return 1

    audio_input: Any = FakeAudioInputBackend() if simulate else AlsaAudioInputBackend(device=device)

    coordinator = AudioInteractionCoordinator(
        audio_input=audio_input,
        stt=stt_backend,
    )

    print("==========================================================")
    print(" AILEN Audio POC — Demo STT (Speech-to-Text)")
    print(f" Motor: {engine} | Dispositivo: {device} | Duración: {duration}s")
    print(f" Estado backend STT: {stt_backend.health().status.value} ({stt_backend.health().detail})")
    print("==========================================================")

    if simulate:
        print("SIMULATION MODE: inyectando audio sintético; el micrófono físico no participa.")
        # Inject pre-roll, speech tone, and silence
        frames = [b"\x00\x00" * 320] * 5
        frames.extend([generate_tone_pcm(300.0, 20.0, amplitude=0.08)] * 30)
        frames.extend([b"\x00\x00" * 320] * 40)
        for f in frames:
            audio_input.push_frame(f)

    coordinator.start()
    start_t = time.time()
    try:
        while time.time() - start_t < duration:
            time.sleep(0.2)
            if coordinator.last_transcript is not None:
                tr = coordinator.last_transcript
                confidence = f"{tr.confidence:.2f}" if tr.confidence is not None else "N/D"
                print(
                    f"\n[TRANSCRIPCIÓN OBTENIDA]: \"{tr.text}\" "
                    f"(confianza: {confidence}, latencia: {tr.latency_ms:.1f}ms)"
                )
                break
    except KeyboardInterrupt:
        print("\nDemo STT interrumpida.")
    finally:
        coordinator.stop()

    print("Demo STT completada.")
    return 0


def cmd_demo_tts(args: argparse.Namespace, config_path: str | None) -> int:
    """Run Text-to-Speech synthesis and mouth sync demo."""
    from ailen.audio.alsa_backend import AlsaAudioOutputBackend
    from ailen.audio.coordinator import AudioInteractionCoordinator
    from ailen.audio.fake import FakeAudioOutputBackend, FakeTtsBackend
    from ailen.audio.piper_backend import PiperTtsBackend
    from ailen.core.config import load_config
    from ailen.face.null import NullFaceController

    cfg = load_config(config_path)
    text = args.text
    engine = getattr(args, "engine", cfg.speech.tts_engine)
    voice = getattr(args, "voice", cfg.speech.tts_voice)
    model = getattr(args, "model", cfg.speech.tts_model_path)
    rate = float(getattr(args, "rate", 1.0))

    tts_backend: Any
    if engine == "piper":
        tts_backend = PiperTtsBackend(
            model_path=model,
            config_path=cfg.speech.tts_config_path,
        )
    else:
        tts_backend = FakeTtsBackend()

    alsa_out = AlsaAudioOutputBackend()
    is_real = alsa_out.health().status.value == "HEALTHY"
    audio_output: Any = alsa_out if is_real else FakeAudioOutputBackend()
    face_ctrl = NullFaceController()

    coordinator = AudioInteractionCoordinator(
        audio_output=audio_output,
        tts=tts_backend,
        face_controller=face_ctrl,
    )

    print("==========================================================")
    print(" AILEN Audio POC — Demo TTS (Text-to-Speech)")
    print(f" Motor: {engine} | Voz: {voice} | Rate: {rate}")
    print(f" Texto: \"{text}\"")
    print(f" Estado backend TTS: {tts_backend.health().status.value} ({tts_backend.health().detail})")
    print("==========================================================")

    output = coordinator.speak(text=text, voice_id=voice, rate=rate)
    print(f"Síntesis completada en {output.latency_ms:.1f}ms | Duración audio: {output.duration_ms:.1f}ms")
    print("Demo TTS completada exitosamente.")
    return 0


def cmd_demo_ai(args: argparse.Namespace, config_path: str | None) -> int:
    """Exercise the canonical router with configured local/LAN/remote backends."""

    from ailen.ai.context import AiContextBuilder
    from ailen.ai.lan_backend import LanBrainAiBackend
    from ailen.ai.local_backend import LocalAiBackend
    from ailen.ai.orchestrator import AiOrchestrator
    from ailen.ai.remote_backend import build_remote_backend
    from ailen.ai.router import RouteRequest, RuleBasedRouter
    from ailen.ai.secrets import SecretResolver
    from ailen.core.config import load_config
    from ailen.domain.enums import DeviceProfile, PrivacyLevel, SocialMode
    from ailen.infrastructure.sqlite.connection import SQLiteManager
    from ailen.infrastructure.sqlite.migrations import MigrationRunner
    from ailen.memory.repository import MemoryRepository

    cfg = load_config(config_path)
    prompt = getattr(args, "prompt", "Hola")
    dry_run = getattr(args, "dry_run", False)
    try:
        social_mode = SocialMode(getattr(args, "mode", "WORKSHOP"))
    except ValueError:
        social_mode = SocialMode.WORKSHOP
    try:
        privacy_level = PrivacyLevel(getattr(args, "privacy", "PRIVATE"))
    except ValueError:
        privacy_level = PrivacyLevel.PRIVATE
    profile = cfg.node.profile
    requested_profile = getattr(args, "profile", None)
    if requested_profile:
        try:
            profile = DeviceProfile(requested_profile)
        except ValueError:
            pass

    db_mgr = SQLiteManager(cfg.memory.sqlite_path)
    MigrationRunner(db_mgr).run_migrations()
    repository = MemoryRepository(db_mgr)
    router = RuleBasedRouter()
    context_builder = AiContextBuilder(
        repository=repository,
        default_identity_name=cfg.identity.display_name,
    )

    enabled_remotes = tuple(
        f"remote:{provider_id}"
        for provider_id, provider in cfg.ai.remote.providers.items()
        if cfg.ai.allow_remote
        and cfg.ai.remote.enabled
        and provider.enabled
        and provider.endpoint
        and provider.model
        and (
            provider.qualification_status == "qualified"
            or cfg.ai.provider == f"remote:{provider_id}"
        )
    )
    priorities = {
        "local": cfg.ai.local.priority,
        "lan_brain": cfg.ai.lan.priority,
        **{
            f"remote:{provider_id}": provider.priority
            for provider_id, provider in cfg.ai.remote.providers.items()
        },
    }
    timeouts = {
        "local": cfg.ai.local.timeout_seconds,
        "lan_brain": cfg.ai.lan.timeout_seconds,
        **{
            f"remote:{provider_id}": provider.timeout_seconds
            for provider_id, provider in cfg.ai.remote.providers.items()
        },
    }
    realtime = {
        f"remote:{provider_id}": provider.voice_realtime_eligible
        and provider.qualification_status == "qualified"
        for provider_id, provider in cfg.ai.remote.providers.items()
    }
    plan = router.route(
        RouteRequest(
            intent=getattr(args, "intent", "chat"),
            profile=profile,
            privacy_level=privacy_level,
            internet_available=bool(enabled_remotes),
            lan_brain_available=cfg.ai.lan.enabled,
            lan_brain_trusted=cfg.ai.lan.trusted,
            local_backend_available=cfg.ai.local.enabled,
            external_allowed=cfg.ai.allow_remote,
            allow_sanitized_external_prompts=cfg.ai.allow_sanitized_external_prompts,
            remote_backends=enabled_remotes,
            preferred_backend=cfg.ai.provider,
            backend_priorities=priorities,
            backend_timeouts=timeouts,
            realtime_eligible_backends=realtime,
        )
    )
    ai_request = context_builder.build_request(
        user_message=prompt,
        mode=social_mode,
        privacy_level=privacy_level,
        identity_name=cfg.identity.display_name,
        destination=plan.primary_backend,
        lan_trusted=cfg.ai.lan.trusted,
    )

    print("==========================================================")
    print(" AILEN AI Demo — canonical adaptive routing")
    print(f" Destino primario : {plan.primary_backend}")
    print(f" Fallbacks        : {plan.fallback_backends}")
    print(f" Motivo           : {plan.reason_code}")
    print(f" Privacidad       : {plan.privacy_decision}")
    print("==========================================================")
    if dry_run:
        print("[DRY-RUN] No se realizó ninguna inferencia ni llamada de red.")
        return 0

    backends: dict[str, Any] = {}
    if cfg.ai.local.enabled:
        backends["local"] = LocalAiBackend(
            endpoint=cfg.ai.local.endpoint,
            model=cfg.ai.local.model,
            timeout_seconds=cfg.ai.local.timeout_seconds,
        )
    if cfg.ai.lan.enabled:
        backends["lan_brain"] = LanBrainAiBackend(
            endpoint=cfg.ai.lan.endpoint,
            model=cfg.ai.lan.model,
            trusted=cfg.ai.lan.trusted,
            timeout_seconds=cfg.ai.lan.timeout_seconds,
        )
    resolver = SecretResolver()
    for provider_id, provider in cfg.ai.remote.providers.items():
        route_id = f"remote:{provider_id}"
        if route_id not in enabled_remotes:
            continue
        backends[route_id] = build_remote_backend(
            provider_id,
            provider,
            api_key=resolver.resolve(
                env_var=provider.api_key_env or None,
                file_name=provider.api_key_file or None,
            ),
        )
    if not backends:
        print("No hay backend configurado; no se activa local ni remoto implícitamente.")
        return 2

    response, _ = AiOrchestrator(
        backends=backends,
        router=router,
        repository=repository,
    ).execute(ai_request, plan=plan)
    print(f"Respuesta ({response.provider}/{response.model}): {response.text!r}")
    print(
        f"Latencia: {response.latency_ms:.1f} ms | "
        f"finish={response.finish_reason}"
    )
    return 0


def cmd_lab_inspect(args: argparse.Namespace) -> int:
    """Inspect hardware capabilities, profile recommendation, runtimes, and model plan."""
    store = ModelStore()
    detector = HardwareDetector()
    report = detector.detect(str(store.base_dir))
    rec = detector.recommend_profile(report)
    rt_mgr = LocalRuntimeManager()
    runtimes = rt_mgr.detect_available_runtimes()
    planner = ModelPlanner()
    plan = planner.plan(report, profile=rec.profile)

    if getattr(args, "json", False):
        payload = {
            "hardware": report.to_dict(),
            "profile_recommendation": rec.to_dict(),
            "runtimes": [
                {
                    "type": r.runtime_type.value,
                    "executable": r.executable_path,
                    "endpoint": r.endpoint,
                    "detected": r.is_detected,
                    "status": r.health.status.value if r.health else "UNKNOWN",
                    "details": r.health.details if r.health else "",
                }
                for r in runtimes
            ],
            "model_plan": plan.to_dict(),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print("                    AILEN LAB HARDWARE INSPECTION                 ")
    print("==================================================================")
    print(f"OS / Distro     : {report.os_distribution} ({report.os_version}) [{report.os_family.value}]")
    print(f"CPU Model       : {report.cpu.model} ({report.cpu.architecture})")
    print(f"CPU Cores/Flags : {report.cpu.physical_cores or '?'} physical / {report.cpu.logical_cores or '?'} logical | AVX2={report.cpu.has_avx2} FMA={report.cpu.has_fma}")
    print(f"RAM Total/Avail : {report.ram.total_mb} MB total / {report.ram.available_mb} MB available ({report.ram.total_gb} GB)")
    if report.gpus:
        for idx, g in enumerate(report.gpus):
            vram_info = f"{g.vram_available_mb} MB free / {g.vram_total_mb} MB total" if g.vram_total_mb else "Shared/System"
            print(f"GPU [{idx}]          : {g.model} ({g.vendor.upper()}) | VRAM: {vram_info} | Backend: {g.backend or 'N/A'}")
    else:
        print("GPU             : None detected / Integrated")
    if report.disk:
        free_gb = round(report.disk.free_bytes / (1024**3), 2)
        total_gb = round(report.disk.total_bytes / (1024**3), 2)
        print(f"Disk Path       : {report.disk.path} ({free_gb} GB free / {total_gb} GB total)")
    print(f"Audio Devices   : {len(report.audio_inputs)} inputs / {len(report.audio_outputs)} outputs")
    print(f"Cameras         : {len(report.cameras)} detected")
    print(f"Displays        : {len(report.displays)} detected")
    print("------------------------------------------------------------------")
    print(f"RECOMMENDED PROFILE : {rec.profile.value}")
    print(f"Local Inference     : capable={rec.local_inference_capable} | budget={rec.recommended_local_budget_mb} MB | preferred_runtime={rec.preferred_runtime}")
    print(f"Profile Reasons     : {', '.join(rec.reason_codes)}")
    print("------------------------------------------------------------------")
    print("DETECTED LOCAL RUNTIMES:")
    for r in runtimes:
        st = r.health.status.value if r.health else "UNKNOWN"
        print(f"  - {r.runtime_type.value}: endpoint={r.endpoint} (detected={r.is_detected}, status={st})")
    print("------------------------------------------------------------------")
    print("RECOMMENDED LOCAL MODEL PLAN:")
    if plan.is_viable and plan.model_descriptor:
        print(f"  Model ID       : {plan.selected_model_id}")
        print(f"  Display Name   : {plan.model_descriptor.display_name}")
        print(f"  Device/Layers  : {plan.device.upper()} (gpu_layers={plan.gpu_layers})")
        print(f"  Estimated RAM  : {plan.estimated_ram_mb} MB | VRAM: {plan.estimated_vram_mb} MB")
        print(f"  Disk Required  : {plan.model_descriptor.disk_size_bytes // (1024 * 1024)} MB")
        print(f"  Plan Reasons   : {', '.join(plan.reason_codes)}")
    else:
        print("  Status         : NO VIABLE LOCAL MODEL PLAN (will delegate to LAN Brain or a named remote provider)")
        print(f"  Reasons        : {', '.join(plan.reason_codes)}")
    print("==================================================================")
    return 0


def cmd_lab_start(args: argparse.Namespace, config_path: str | None) -> int:
    """Start AILEN in Lab Mode using dedicated non-invasive LabRunner."""
    from ailen.runtime.runner import LabRunner

    cfg = load_config(config_path)
    setup_logging(cfg.logging)
    runner = LabRunner(
        config=cfg,
        dry_run=getattr(args, "dry_run", False),
        headless=getattr(args, "headless", False),
        no_camera=getattr(args, "no_camera", False),
        no_audio=getattr(args, "no_audio", False),
        no_ai=getattr(args, "no_ai", False),
        simulate=getattr(args, "simulate", False),
        fullscreen=getattr(args, "fullscreen", False),
        duration=getattr(args, "duration", None),
    )
    return runner.start()


def cmd_lab_doctor(args: argparse.Namespace, config_path: str | None) -> int:
    """Run non-invasive Lab Doctor diagnostics."""
    from ailen.runtime.doctor import LabDoctor

    cfg = load_config(config_path)
    doctor = LabDoctor(config=cfg)
    return doctor.print_report(as_json=getattr(args, "json", False))


def cmd_lab_prepare_ai(args: argparse.Namespace, config_path: str | None) -> int:
    """Run interactive or automated prepare-ai workflow."""
    from ailen.provisioning.planner import (
        HardwareQualificationStore,
        ProvisioningPlanner,
    )
    from ailen.runtime.prepare import LabAiPreparer

    cfg = load_config(config_path)
    try:
        qualifications = HardwareQualificationStore.from_directory(
            Path(str(args.qualification_dir))
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: evidencia de calificación inválida: {exc}")
        return 1
    preparer = LabAiPreparer(
        config=cfg,
        provisioning_planner=ProvisioningPlanner(qualifications=qualifications),
    )

    _report, code = preparer.run(
        auto_download=getattr(args, "yes", False),
        start_runtime=getattr(args, "start_runtime", False),
        activate_selection=getattr(args, "activate_selection", False),
    )
    return code


def cmd_lab_benchmark(args: argparse.Namespace) -> int:
    """Run lab benchmark harness and export report."""
    import time
    store = ModelStore()
    detector = HardwareDetector()
    report = detector.detect(str(store.base_dir))
    rec = detector.recommend_profile(report)
    planner = ModelPlanner()
    plan = planner.plan(report, profile=rec.profile)

    out_dir = Path(getattr(args, "output", "runtime/lab/benchmarks"))
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    bench_file = out_dir / f"lab_benchmark_{timestamp}.json"

    bench_data = {
        "timestamp": timestamp,
        "hardware_snapshot": report.to_dict(),
        "profile_recommendation": rec.to_dict(),
        "model_plan": plan.to_dict(),
    }
    bench_file.write_text(json.dumps(bench_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Benchmark lab report saved to: {bench_file}")
    return 0


def cmd_lab_benchmark_ai(args: argparse.Namespace) -> int:
    """Run local AI model benchmark without downloading external artifacts."""
    from ailen.runtime.model_benchmark import ModelBenchmarkRunner

    models = [m.strip() for m in getattr(args, "models", "").split(",") if m.strip()]
    if not models:
        models = ["qwen3.5:9b", "qwen2.5-coder:3b", "llama3.2:3b", "gemma3:4b", "qwen3.5:4b"]

    endpoint = getattr(args, "endpoint", "http://127.0.0.1:11434/v1")
    runner = ModelBenchmarkRunner(endpoint=endpoint)
    report = runner.run_benchmark(
        candidate_models=models,
        warmup_turns=getattr(args, "warmup", 1),
        max_prompts=getattr(args, "turns", None),
    )

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print("AILEN — LOCAL AI INFERENCE BENCHMARK")
    print(f"Endpoint: {report.endpoint}")
    print("==================================================================")
    print(f"{'MODEL':<24} {'STATUS':<15} {'FIRST(ms)':<10} {'AVG(ms)':<10} {'P95(ms)':<10} {'TOK/S':<8} {'PASS%'}")
    print("-" * 88)

    for m in report.models_evaluated:
        if m.status == "NOT_INSTALLED":
            print(f"{m.model_name:<24} {'NOT_INSTALLED':<15} {'-':<10} {'-':<10} {'-':<10} {'-':<8} {'-'}")
        else:
            cold_str = str(m.first_turn_ms) if m.first_turn_ms is not None else "-"
            avg_str = str(m.warm_latency_avg_ms) if m.warm_latency_avg_ms is not None else "-"
            p95_str = str(m.warm_latency_p95_ms) if m.warm_latency_p95_ms is not None else "-"
            tps_str = str(m.tokens_per_second_avg) if m.tokens_per_second_avg is not None else "-"
            pass_str = f"{m.structural_pass_rate}%"
            print(f"{m.model_name:<24} {m.status:<15} {cold_str:<10} {avg_str:<10} {p95_str:<10} {tps_str:<8} {pass_str}")

    print("==================================================================")
    return 0


def cmd_lab_benchmark_vision(args: argparse.Namespace, config_path: str | None) -> int:
    """Benchmark the configured face detector on the real camera (CPU-first)."""
    import time as _time

    from ailen.vision.benchmark import build_report, collect_samples
    from ailen.vision.opencv_backend import OpenCvVisionBackend

    cfg = load_config(config_path)
    detector = str(getattr(args, "detector", "") or cfg.vision.detector)
    model_path = str(getattr(args, "model", "") or cfg.vision.detector_model_path)
    score = float(getattr(args, "score", 0.0) or 0.0)
    if score <= 0.0:
        score = float(cfg.vision.detector_score_threshold)
    explicit_camera = str(getattr(args, "camera", "") or "").strip()
    camera_dev: str | int = explicit_camera or cfg.vision.camera_device
    if not explicit_camera:
        from ailen.hardware.detector import HardwareDetector

        detected_cameras = [
            camera.device_path
            for camera in HardwareDetector().detect().cameras
            if camera.is_available
        ]
        if str(camera_dev) not in detected_cameras and detected_cameras:
            camera_dev = detected_cameras[0]
    fps = int(getattr(args, "fps", 5) or 5)
    max_frames = max(1, int(getattr(args, "frames", 150)))
    phase = str(getattr(args, "phase", "uncontrolled"))
    timeout_s = float(getattr(args, "timeout", 120.0))

    if detector == "yunet" and not model_path.strip():
        print("ERROR: --detector yunet requiere --model o vision.detector_model_path en la config.")
        return 1

    backend = OpenCvVisionBackend(
        camera_device=camera_dev,
        fps=fps,
        detector=detector,
        yunet_model_path=model_path,
        yunet_score_threshold=score,
    )
    backend.start()
    try:
        health = backend.health()
        print("==========================================================")
        print(" AILEN Vision Detector Benchmark (CPU-first, sin GUI)")
        print(f" Dispositivo: {camera_dev} | Detector: {detector} | FPS: {fps} | Fase: {phase}")
        print("==========================================================")
        if health.status.value != "HEALTHY":
            print(f"ERROR: backend de visión no sano: {health.detail}")
            return 1

        start_t = _time.monotonic()
        samples = collect_samples(backend, max_frames=max_frames, timeout_seconds=timeout_s)
        duration_s = _time.monotonic() - start_t
    finally:
        backend.stop()

    report = build_report(
        detector=detector,
        camera_device=str(camera_dev),
        requested_fps=fps,
        phase=phase,
        samples=samples,
        duration_s=duration_s,
    )

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        conf_avg = f"{report.confidence_avg:.3f}" if report.confidence_avg is not None else "-"
        conf_min = f"{report.confidence_min:.3f}" if report.confidence_min is not None else "-"
        gaze_x = f"[{report.gaze_x_range[0]:+.2f}, {report.gaze_x_range[1]:+.2f}]" if report.gaze_x_range else "-"
        gaze_y = f"[{report.gaze_y_range[0]:+.2f}, {report.gaze_y_range[1]:+.2f}]" if report.gaze_y_range else "-"
        print(f"Frames muestreados : {report.frames} ({duration_s:.1f}s)")
        print(f"Detecciones        : {report.detections}/{report.frames} ({report.detection_rate:.1f}%)")
        print(f"Latencia avg/p50/p95/max ms: {report.avg_latency_ms:.1f} / {report.p50_latency_ms:.1f} / "
              f"{report.p95_latency_ms:.1f} / {report.max_latency_ms:.1f}")
        print(f"Confianza avg/min  : {conf_avg} / {conf_min}")
        print(f"Gaze x/y           : {gaze_x} / {gaze_y}")

    out_dir = Path(str(getattr(args, "output", "runtime/lab/vision_benchmarks")))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"vision_benchmark_{int(_time.time())}.json"
    out_file.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte guardado en: {out_file}")
    return 0


def cmd_lab_benchmark_stt(args: argparse.Namespace, config_path: str | None) -> int:
    """Benchmark STT engines over identical WAV inputs; never downloads models."""
    from ailen.audio.stt_benchmark import SttBenchmarkRunner

    cfg = load_config(config_path)
    wav_paths = [str(p) for p in getattr(args, "wav", []) if str(p).strip()]
    record_seconds = float(getattr(args, "record", 0.0) or 0.0)
    out_path = str(getattr(args, "out", "") or "")

    if record_seconds > 0:
        if not out_path:
            print("ERROR: --record requiere --out <ruta.wav> para guardar el audio autorizado.")
            return 1
        recorded = _record_wav_authorized(
            device=str(getattr(args, "audio_device", "default")),
            seconds=record_seconds,
            out_path=out_path,
        )
        if recorded != 0:
            return recorded
        wav_paths.append(out_path)

    if not wav_paths:
        print("ERROR: se requiere al menos un archivo WAV (--wav ruta.wav) o --record N.")
        return 1

    engines_list = [e.strip() for e in str(getattr(args, "engines", "vosk,whisper_cpp")).split(",") if e.strip()]
    reference = str(getattr(args, "reference", "") or "").strip() or None

    vosk_model = str(getattr(args, "vosk_model", "") or cfg.speech.stt_model_path)
    runner = SttBenchmarkRunner(
        vosk_model_path=vosk_model,
        whisper_binary=str(getattr(args, "whisper_binary", "whisper-cli")),
        whisper_model_path=str(getattr(args, "whisper_model", "")),
        language=cfg.speech.stt_language,
    )
    try:
        results = runner.run(wav_paths, engines=engines_list, reference=reference)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    if getattr(args, "json", False):
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
    else:
        print("==================================================================")
        print("AILEN — STT BENCHMARK")
        print("==================================================================")
        for r in results:
            wer_text = "-" if r.wer is None else f"{r.wer:.3f}"
            lat_text = "-" if r.latency_ms is None else f"{r.latency_ms:.0f}"
            print(f"{r.engine:<12} {r.status:<14} lat={lat_text:>6}ms words={r.word_count:<3} WER={wer_text:<7} {Path(r.wav_path).name}")
            if r.transcript:
                print(f"             transcript: {r.transcript[:120]}")
            if r.detail and r.status != "OK":
                print(f"             detalle: {r.detail[:120]}")
        print("==================================================================")
    return 0


def _parse_bounded_int_csv(raw: str, *, allowed: set[int], label: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        try:
            value = int(part.strip())
        except ValueError as exc:
            raise ValueError(f"{label} contiene un entero inválido: {part!r}") from exc
        if value not in allowed:
            raise ValueError(f"{label} fuera de rango: {value}")
        if value not in values:
            values.append(value)
    if not values:
        raise ValueError(f"{label} no puede estar vacío")
    return values


def _run_lab_barge_in_validation(
    *,
    cfg: Any,
    cases: list[Any],
    output_root: Path,
    timeout_seconds: float,
) -> int:
    """Run real early/middle/late interruption trials over canonical Lab audio."""
    import os
    import secrets
    from datetime import UTC, datetime

    from ailen.audio.alsa_backend import AlsaDeviceEnumerator
    from ailen.audio.voice_validation import (
        BargeInTrialResult,
        run_physical_barge_in_trial,
    )
    from ailen.core.events import EventBus
    from ailen.runtime.factory import LabComponentFactory

    factory = LabComponentFactory(config=cfg)
    audio_input, audio_output, audio_status = factory.build_audio_io()
    stt, stt_status = factory.build_stt()
    tts, tts_status = factory.build_tts()
    unavailable = [
        status
        for status, component in (
            (audio_status, audio_input),
            (stt_status, stt),
            (tts_status, tts),
        )
        if component is None
    ]
    if unavailable:
        for status in unavailable:
            print(f"ERROR: {status.name} no está listo: {status.detail}")
        return 1
    assert audio_input is not None
    assert audio_output is not None
    assert stt is not None
    assert tts is not None

    event_bus = EventBus(record_history=False)
    coordinator = factory.build_audio_coordinator(
        audio_input=audio_input,
        audio_output=audio_output,
        stt=stt,
        tts=tts,
        state_manager=StateManager(initial_state=AssistantState.IDLE),
        event_bus=event_bus,
        auto_reset_after_stt=True,
    )
    if coordinator is None:
        print("ERROR: no se pudo construir el pipeline de audio canónico.")
        return 1

    session_id = (
        f"barge-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{secrets.token_hex(3)}"
    )
    output_dir = output_root / session_id
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    enumerator = AlsaDeviceEnumerator()
    route_snapshot = {
        "configured_input": cfg.audio.input_device,
        "configured_output": cfg.audio.output_device,
        "default_input_route": enumerator.get_default_route(is_input=True),
        "default_output_route": enumerator.get_default_route(is_input=False),
        "default_input_physical": enumerator.get_default_alsa_endpoint(is_input=True),
        "default_output_physical": enumerator.get_default_alsa_endpoint(is_input=False),
    }
    results: list[BargeInTrialResult] = []
    aborted = False

    print("==================================================================")
    print("AILÉN — BARGE-IN FÍSICO TEMPRANO / MEDIO / TARDÍO")
    print("Usa Vosk, TTS y ALSA reales de la config. PCM permanece sólo en RAM.")
    print("No hay AEC real: el resultado depende también de fuga del parlante al micrófono.")
    print("La síntesis ONNX activa no se finge cancelable; se mide su drenaje aparte.")
    print(f"Session: {session_id}")
    print(f"Entrada: {cfg.audio.input_device} | Salida: {cfg.audio.output_device}")
    print("Enter=ejecutar, s=omitir, q=guardar parcial y salir.")
    print("==================================================================")

    def show_cue(phase: str, expected_text: str) -> None:
        print(f"\n>>> INTERRUMPÍ AHORA ({phase}): «{expected_text}» <<<", flush=True)

    coordinator.start()
    try:
        if not coordinator.capabilities()[0].available:
            print("ERROR: la captura de audio no quedó activa.")
            return 1
        for case in cases:
            print(
                f"\nEnsayo {case.phase}: la señal aparece a los "
                f"{case.cue_delay_seconds:.2f}s del primer PCM."
            )
            choice = input("Enter para iniciar / s omitir / q terminar: ").strip().lower()
            if choice == "q":
                aborted = True
                break
            if choice == "s":
                results.append(
                    BargeInTrialResult(
                        phase=case.phase,
                        expected_text=case.expected_text,
                        recognized_text="",
                        status="skipped",
                    )
                )
                continue
            turn_id = f"barge-{case.phase}-{secrets.token_hex(3)}"
            result = run_physical_barge_in_trial(
                coordinator=coordinator,
                phase=case.phase,
                expected_text=case.expected_text,
                cue_delay_seconds=case.cue_delay_seconds,
                timeout_seconds=timeout_seconds,
                turn_id=turn_id,
                on_cue=show_cue,
            )
            results.append(result)
            print(
                f"RESULTADO: {result.status} texto={result.recognized_text!r} "
                f"conf={result.confidence} WER={result.wer} "
                f"stop={result.playback_stop_ms}ms frames={result.buffered_frames} "
                f"drain={result.synthesis_drain_observed}"
            )
    except (EOFError, KeyboardInterrupt):
        aborted = True
        print("\nSesión detenida; se guarda sólo evidencia textual parcial.")
    finally:
        coordinator.stop()

    report = {
        "schema_version": 1,
        "session_id": session_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "partial" if aborted else "complete",
        "lab_host": "ASRock contended",
        "load_average": list(os.getloadavg()),
        "pcm_persisted": False,
        "aec_available": False,
        "active_config_modified": False,
        "route_snapshot": route_snapshot,
        "component_status": {
            "audio": audio_status.to_dict(),
            "stt": stt_status.to_dict(),
            "tts": tts_status.to_dict(),
        },
        "results": [result.to_dict() for result in results],
    }
    report_path = output_dir / "summary.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.chmod(0o600)
    lines = [
        f"# AILÉN barge-in validation {session_id}",
        "",
        f"- Estado: {report['status']}",
        "- PCM/audio persistido: no",
        "- AEC real disponible: no",
        "- Config activa modificada: no",
        "- Host: ASRock contended; no extrapolar a equipos 4/8 GB",
        "",
        "| Fase | Resultado | Stop ms | Frames | WER | Drenaje observado |",
        "|---|---|---:|---:|---:|---|",
    ]
    for result in results:
        lines.append(
            f"| {result.phase} | {result.status} | {result.playback_stop_ms} | "
            f"{result.buffered_frames} | {result.wer} | "
            f"{result.synthesis_drain_observed} |"
        )
    markdown_path = output_dir / "summary.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    markdown_path.chmod(0o600)
    print(f"\nMétricas: {report_path}")
    return 130 if aborted else 0


def cmd_lab_calibrate_voice(args: argparse.Namespace, config_path: str | None) -> int:
    """Run guided physical source/level/VAD/Vosk comparisons without PCM files."""
    import os
    import secrets
    from datetime import UTC, datetime

    from ailen.audio.alsa_backend import AlsaAudioInputBackend, AlsaDeviceEnumerator
    from ailen.audio.level import build_capture_processor
    from ailen.audio.stt_quality import SttQualityEvaluator
    from ailen.audio.vad import UtteranceCollector, WebRtcVad
    from ailen.audio.voice_validation import (
        VoiceSampleResult,
        VoiceValidationCase,
        capture_voice_sample,
        default_barge_in_validation_cases,
        default_voice_validation_cases,
        format_voice_sample_result,
        recommend_voice_configuration,
        select_voice_calibration_devices,
    )
    from ailen.audio.vosk_backend import VoskSttBackend
    from ailen.domain.enums import ServiceStatus

    cfg = load_config(config_path)
    try:
        vad_modes = _parse_bounded_int_csv(
            str(args.vad_modes), allowed={0, 1, 2, 3}, label="--vad-modes"
        )
        silence_timeouts = _parse_bounded_int_csv(
            str(args.silence_timeouts),
            allowed=set(range(200, 1501)),
            label="--silence-timeouts",
        )
        distances_cm = _parse_bounded_int_csv(
            str(args.distances_cm),
            allowed=set(range(20, 501)),
            label="--distances-cm",
        )
        processing_profiles = list(
            dict.fromkeys(
                part.strip().lower()
                for part in str(args.processing_profiles).split(",")
                if part.strip()
            )
        )
        silence_seconds = float(args.silence_seconds)
        if not processing_profiles or any(
            profile not in {"raw", "noise_only", "full"}
            for profile in processing_profiles
        ):
            raise ValueError(
                "--processing-profiles sólo acepta raw,noise_only,full"
            )
        if not 0.5 <= silence_seconds <= 5.0:
            raise ValueError("--silence-seconds debe estar entre 0.5 y 5.0")

        gain_raw = str(args.capture_gains).strip()
        capture_gains = (
            [float(part.strip()) for part in gain_raw.split(",") if part.strip()]
            if gain_raw
            else [cfg.audio.capture_gain_db]
        )
        if not capture_gains or any(not -24.0 <= value <= 30.0 for value in capture_gains):
            raise ValueError("--capture-gains debe contener valores entre -24 y 30 dB")
        capture_gains = list(dict.fromkeys(capture_gains))

        agc_raw = str(args.auto_gain_modes).strip()
        if agc_raw:
            mapping = {"off": False, "on": True}
            invalid = [
                part.strip().lower()
                for part in agc_raw.split(",")
                if part.strip().lower() not in mapping
            ]
            if invalid:
                raise ValueError("--auto-gain-modes sólo acepta off,on")
            auto_gain_modes = list(
                dict.fromkeys(mapping[part.strip().lower()] for part in agc_raw.split(","))
            )
        else:
            auto_gain_modes = [cfg.audio.auto_gain_enabled]
    except (TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    barge_in_cases = default_barge_in_validation_cases()
    if bool(args.barge_in_only):
        barge_matrix = {
            "mode": "barge_in",
            "trials": [
                {
                    "phase": barge_case.phase,
                    "expected_text": barge_case.expected_text,
                    "cue_delay_seconds": barge_case.cue_delay_seconds,
                }
                for barge_case in barge_in_cases
            ],
            "captures_audio": False,
            "aec_available": False,
            "note": (
                "--list-cases no abre audio; la prueba real usa el pipeline "
                "configurado y nunca persiste PCM."
            ),
        }
        if bool(args.list_cases):
            if bool(args.json):
                print(json.dumps(barge_matrix, indent=2, ensure_ascii=False))
            else:
                print("AILÉN — ensayos físicos de barge-in (sin AEC real)")
                for barge_case in barge_in_cases:
                    print(
                        f"- {barge_case.phase}: decí «{barge_case.expected_text}» "
                        "al recibir la señal"
                    )
            return 0
        return _run_lab_barge_in_validation(
            cfg=cfg,
            cases=barge_in_cases,
            output_root=Path(str(args.output)),
            timeout_seconds=max(1.0, float(args.barge_in_timeout)),
        )

    enumerator = AlsaDeviceEnumerator()
    pipewire_sources = []
    seen_source_ids: set[str] = set()
    for source in enumerator.list_pipewire_devices(is_input=True):
        if source.is_monitor or source.id in seen_source_ids:
            continue
        seen_source_ids.add(source.id)
        pipewire_sources.append(source)
    default_source = next(
        (source.id for source in pipewire_sources if source.is_default),
        None,
    )

    def observed_source_for(device: str) -> str:
        if device in {"auto", "default", "pipewire"} and default_source:
            return default_source
        return device
    explicit_devices = [
        str(item).strip() for item in args.device if str(item).strip()
    ]
    devices = select_voice_calibration_devices(
        explicit_devices=explicit_devices,
        configured_device=cfg.audio.input_device,
        pipewire_sources=pipewire_sources,
    )

    source_snapshot = [
        {
            "id": source.id,
            "name": source.name,
            "default": source.is_default,
            "state": source.state,
            "volume_percent": source.volume_percent,
            "volume_db": source.volume_db,
            "attenuation_warning": bool(
                (source.volume_percent is not None and source.volume_percent < 60.0)
                or (source.volume_db is not None and source.volume_db < -10.0)
            ),
        }
        for source in pipewire_sources
    ]
    source_by_id = {str(item["id"]): item for item in source_snapshot}

    cases = default_voice_validation_cases()
    limit = max(0, int(args.limit))
    if limit:
        cases = cases[:limit]
    matrix = {
        "devices": devices,
        "available_pipewire_sources": source_snapshot,
        "vad_modes": vad_modes,
        "silence_timeouts_ms": silence_timeouts,
        "capture_gains_db": capture_gains,
        "auto_gain_modes": auto_gain_modes,
        "distances_cm": distances_cm,
        "processing_profiles": processing_profiles,
        "silence_phase_seconds": silence_seconds,
        "cases": [
            {
                "case_id": case.case_id,
                "expected_text": case.expected_text,
                "instruction": case.instruction,
            }
            for case in cases
        ],
        "captures_audio": False,
        "note": "--list-cases no abre el micrófono; PCM real permanece sólo en RAM.",
    }
    if bool(args.list_cases):
        if bool(args.json):
            print(json.dumps(matrix, indent=2, ensure_ascii=False))
        else:
            print("AILÉN — matriz física de fuente + nivel + WebRTC VAD + Vosk")
            print(f"Fuentes: {devices}")
            print(
                f"Gain: {capture_gains} dB; AGC: {auto_gain_modes}; "
                f"distancias: {distances_cm} cm; perfiles: {processing_profiles}; "
                f"silencio: {silence_seconds:.1f} s"
            )
            print(f"WebRTC: {vad_modes}; cierre: {silence_timeouts} ms")
            for index, voice_case in enumerate(cases, start=1):
                print(
                    f"{index:02d}. {voice_case.expected_text} "
                    f"({voice_case.instruction})"
                )
        return 0

    stt = VoskSttBackend(
        model_path=cfg.speech.stt_model_path,
        sample_rate=cfg.audio.sample_rate,
    )
    stt_health = stt.health()
    if stt_health.status is not ServiceStatus.HEALTHY:
        print(f"ERROR: Vosk no está listo: {stt_health.detail}")
        return 1

    route_snapshot = {
        "configured_input": cfg.audio.input_device,
        "default_route": default_source,
        "default_physical_endpoint": enumerator.get_default_alsa_endpoint(is_input=True),
        "tested_devices": devices,
        "available_pipewire_sources": source_snapshot,
    }
    session_id = (
        f"voice-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{secrets.token_hex(3)}"
    )
    output_dir = Path(str(args.output)) / session_id
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    results: list[VoiceSampleResult] = []
    aborted = False

    print("==================================================================")
    print("AILÉN — COMPARACIÓN FÍSICA DE CAPTURA A DISTANCIA")
    print("PCM: sólo RAM; no se guarda WAV/audio. Config activa: no se modifica.")
    print("Easy Effects es sólo una fuente observable de Lab; AILÉN no depende de ella.")
    print("AGC/ganancia NO son AEC; durante playback persiste la limitación física de eco.")
    print("Trading Bot queda intacto; esta ASRock se etiqueta como contended.")
    print(f"Session: {session_id}")
    print(f"Configurada: {route_snapshot['configured_input']}")
    print(f"Default efectiva: {route_snapshot['default_route'] or 'no observable'}")
    for snapshot_entry in source_snapshot:
        warning = (
            " ⚠ ATENUADA" if snapshot_entry["attenuation_warning"] else ""
        )
        print(
            f"- {snapshot_entry['id']}: {snapshot_entry['name']} "
            f"{snapshot_entry['volume_percent']}% / "
            f"{snapshot_entry['volume_db']} dB "
            f"[{snapshot_entry['state']}]{warning}"
        )
    print("Cada muestra inicia con silencio medido; AILÉN indicará cuándo hablar.")
    print("Enter=iniciar, s=omitir, q=guardar parcial y salir.")
    print("==================================================================")

    trials: list[
        tuple[str, str, str, float, bool, int, int, int, VoiceValidationCase]
    ] = []
    for device in devices:
        is_external_dsp = "easyeffects" in device.casefold()
        profiles_for_device = (
            [("external_reference", "raw")]
            if is_external_dsp
            else [(profile, profile) for profile in processing_profiles]
        )
        for profile_label, build_profile in profiles_for_device:
            gain_values = capture_gains if build_profile == "full" else [0.0]
            agc_values = auto_gain_modes if build_profile == "full" else [False]
            for capture_gain_db in gain_values:
                for auto_gain_enabled in agc_values:
                    for distance_cm in distances_cm:
                        for vad_mode in vad_modes:
                            for silence_timeout_ms in silence_timeouts:
                                for voice_case in cases:
                                    trials.append(
                                        (
                                            device,
                                            profile_label,
                                            build_profile,
                                            capture_gain_db,
                                            auto_gain_enabled,
                                            distance_cm,
                                            vad_mode,
                                            silence_timeout_ms,
                                            voice_case,
                                        )
                                    )
    total = len(trials)
    ordinal = 0
    warned_attenuated_sources: set[str] = set()
    try:
        for (
            device,
            profile_label,
            build_profile,
            capture_gain_db,
            auto_gain_enabled,
            distance_cm,
            vad_mode,
            silence_timeout_ms,
            voice_case_raw,
        ) in trials:
            voice_case = voice_case_raw
            effective_source_hint = observed_source_for(device)
            source_info = source_by_id.get(effective_source_hint)
            if (
                source_info
                and source_info["attenuation_warning"]
                and device not in warned_attenuated_sources
            ):
                warned_attenuated_sources.add(device)
                print(
                    f"\n⚠ {source_info['name']} está atenuada a "
                    f"{source_info['volume_percent']}% / {source_info['volume_db']} dB. "
                    "Se medirá así; AILÉN no cambiará el sistema."
                )
            ordinal += 1
            print(
                f"\n[{ordinal}/{total}] source={device} profile={profile_label} "
                f"gain={capture_gain_db:+.1f}dB AGC={auto_gain_enabled} "
                f"WebRTC={vad_mode} close={silence_timeout_ms}ms"
            )
            print(
                f"LUEGO DECÍ A {distance_cm} cm: «{voice_case.expected_text}»"
            )
            print(f"INDICACIÓN: {voice_case.instruction}")
            choice = input(
                "Enter para medir silencio / s omitir / q terminar: "
            ).strip().lower()
            if choice == "q":
                aborted = True
                raise KeyboardInterrupt
            if choice == "s":
                results.append(
                    VoiceSampleResult(
                        case_id=voice_case.case_id,
                        expected_text=voice_case.expected_text,
                        recognized_text="",
                        device=device,
                        vad_mode=vad_mode,
                        silence_timeout_ms=silence_timeout_ms,
                        status="skipped",
                        processing_profile=profile_label,
                        distance_cm=distance_cm,
                        capture_gain_db=capture_gain_db,
                        auto_gain_enabled=auto_gain_enabled,
                    )
                )
                continue

            frame_ms = cfg.audio.frame_ms
            collector = UtteranceCollector(
                vad=WebRtcVad(
                    sample_rate=cfg.audio.sample_rate,
                    frame_ms=frame_ms,
                    mode=vad_mode,
                    hangover_frames=max(
                        0,
                        round(cfg.speech.vad_hangover_ms / frame_ms),
                    ),
                    min_rms=cfg.speech.vad_threshold,
                ),
                sample_rate=cfg.audio.sample_rate,
                channels=cfg.audio.channels,
                frame_ms=frame_ms,
                min_speech_ms=cfg.speech.min_speech_ms,
                silence_timeout_ms=silence_timeout_ms,
                max_utterance_seconds=cfg.speech.max_utterance_seconds,
                pre_roll_ms=cfg.speech.pre_roll_ms,
            )
            frame_processor = build_capture_processor(
                sample_rate=cfg.audio.sample_rate,
                channels=cfg.audio.channels,
                frame_ms=frame_ms,
                capture_gain_db=capture_gain_db,
                auto_gain_enabled=auto_gain_enabled,
                auto_gain_target_rms=cfg.audio.auto_gain_target_rms,
                max_auto_gain_db=cfg.audio.max_auto_gain_db,
                auto_gain_attack_ms=cfg.audio.auto_gain_attack_ms,
                auto_gain_release_ms=cfg.audio.auto_gain_release_ms,
                auto_gain_noise_gate_rms=cfg.audio.auto_gain_noise_gate_rms,
                auto_gain_gate_hold_ms=cfg.audio.auto_gain_gate_hold_ms,
                capture_limiter_peak=cfg.audio.capture_limiter_peak,
                noise_suppression_engine=cfg.speech.noise_suppression_engine,
                noise_suppression_level=cfg.speech.noise_suppression_level,
                input_processing_mode="auto",
                input_device=device,
                effective_source=effective_source_hint,
                processing_profile=build_profile,
            )

            def speech_ready(target_distance_cm: int = distance_cm) -> None:
                print(
                    f">>> HABLÁ AHORA, en volumen normal a {target_distance_cm} cm <<<",
                    flush=True,
                )

            result = capture_voice_sample(
                case=voice_case,
                device=device,
                vad_mode=vad_mode,
                silence_timeout_ms=silence_timeout_ms,
                audio_input=AlsaAudioInputBackend(
                    device=device,
                    sample_rate=cfg.audio.sample_rate,
                    channels=cfg.audio.channels,
                    frame_ms=frame_ms,
                ),
                collector=collector,
                stt=stt,
                quality=SttQualityEvaluator(
                    noise_confidence_max=cfg.speech.stt_noise_confidence_max,
                    conversation_min_confidence=(
                        cfg.speech.stt_conversation_min_confidence
                    ),
                    action_min_confidence=cfg.speech.voice_action_min_confidence,
                ),
                frame_processor=frame_processor,
                max_wait_seconds=max(1.0, float(args.max_wait)),
                silence_seconds=silence_seconds,
                distance_cm=distance_cm,
                on_speech_ready=speech_ready,
                capture_gain_db=capture_gain_db,
                auto_gain_enabled=auto_gain_enabled,
                processing_profile=profile_label,
                effective_source_hint=effective_source_hint,
            )
            results.append(result)
            print(f"RESULTADO: {format_voice_sample_result(result)}")
    except (EOFError, KeyboardInterrupt):
        aborted = True
        print("\nSesión detenida; se guardan sólo métricas textuales parciales.")

    recommendation = recommend_voice_configuration(results)
    report = {
        "schema_version": 2,
        "session_id": session_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "partial" if aborted else "complete",
        "lab_host": "ASRock contended",
        "load_average": list(os.getloadavg()),
        "pcm_persisted": False,
        "active_config_modified": False,
        "aec_available": False,
        "stt": {"engine": "vosk", "health": stt_health.status.value},
        "route_snapshot": route_snapshot,
        "matrix": matrix,
        "results": [result.to_dict() for result in results],
        "recommendation": recommendation,
        "barge_in": {
            "validated": False,
            "detail": "Ejecutar --barge-in-only por separado; AGC no equivale a AEC.",
        },
    }
    report_path = output_dir / "summary.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.chmod(0o600)
    markdown = [
        f"# AILÉN voice validation {session_id}",
        "",
        f"- Estado: {report['status']}",
        f"- Muestras: {len(results)}",
        "- PCM/audio persistido: no",
        "- Configuración activa modificada: no",
        "- AEC disponible: no",
        "- Host: ASRock contended; no extrapolar a 4/8 GB",
        "",
        "## Recomendación observacional",
        "",
        json.dumps(recommendation, ensure_ascii=False, sort_keys=True),
        "",
        "Requiere confirmación humana antes de persistir fuente, gain, AGC o VAD.",
    ]
    markdown_path = output_dir / "summary.md"
    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    markdown_path.chmod(0o600)
    print(f"\nMétricas: {report_path}")
    print("No se modificó config/ailen.toml. Toda recomendación requiere confirmación.")
    return 130 if aborted else 0

def _record_wav_authorized(device: str, seconds: float, out_path: str) -> int:
    """Record an explicit operator-authorized WAV via the ALSA input backend."""
    import time as _time
    import wave as _wave

    from ailen.audio.alsa_backend import AlsaAudioInputBackend

    backend = AlsaAudioInputBackend(device=device, sample_rate=16000, channels=1)
    frames: list[bytes] = []
    try:
        backend.start()
        health = backend.health()
        if health.status.value != "HEALTHY":
            print(f"ERROR: captura de audio no disponible: {health.detail}")
            return 1

        start_t = _time.monotonic()
        while _time.monotonic() - start_t < seconds:
            frame = backend.read_frame(timeout_seconds=0.2)
            if frame:
                frames.append(frame)
    finally:
        backend.stop()

    pcm = b"".join(frames)
    if not pcm:
        print("ERROR: no se capturó audio.")
        return 1

    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _wave.open(str(destination), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm)
    print(f"Audio grabado ({len(pcm) / 32000.0:.1f}s) en: {destination}")
    return 0


def cmd_lab_preflight(args: argparse.Namespace, config_path: str | None) -> int:
    """Run comprehensive physical lab preflight check."""
    from ailen.runtime.preflight import LabPreflightChecker

    cfg = load_config(config_path)
    checker = LabPreflightChecker(config=cfg)
    if getattr(args, "json", False):
        rep = checker.run_all(
            headless=getattr(args, "headless", False),
            no_camera=getattr(args, "no_camera", False),
            no_audio=getattr(args, "no_audio", False),
            no_ai=getattr(args, "no_ai", False),
        )
        print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
        return 0 if rep.overall_status == "READY_FOR_LIVE_TEST" else 1
    return checker.print_report(
        headless=getattr(args, "headless", False),
        no_camera=getattr(args, "no_camera", False),
        no_audio=getattr(args, "no_audio", False),
        no_ai=getattr(args, "no_ai", False),
    )


def cmd_lab_prepare_speech(args: argparse.Namespace, config_path: str | None) -> int:
    """Inspect or download required STT and TTS models for Lab Mode."""
    from ailen.speech.prepare import LabSpeechPreparer

    cfg = load_config(config_path)
    preparer = LabSpeechPreparer(config=cfg)
    _report, code = preparer.run_prepare(
        auto_download=getattr(args, "yes", False),
        stt_engine=getattr(args, "stt", "vosk"),
        voice_key=getattr(args, "voice", "es_ES-davefx-medium"),
    )
    return code


def cmd_lab_config(args: argparse.Namespace) -> int:
    """Initialize or manage isolated lab configuration at runtime/lab/ailen-lab.toml."""
    action = getattr(args, "lab_config_action", None)
    if action == "init":
        from ailen.runtime.lab_config import init_lab_config

        out_path, created = init_lab_config(
            profile_id=args.profile,
            force=getattr(args, "force", False),
            stt_engine=getattr(args, "stt", "vosk"),
            tts_voice=getattr(args, "voice", "es_ES-davefx-medium"),
            local_endpoint=getattr(args, "local_endpoint", "") or None,
            local_model=getattr(args, "local_model", "") or None,
            lan_endpoint=getattr(args, "lan_endpoint", "") or None,
            lan_model=getattr(args, "lan_model", "") or None,
            lan_trusted=bool(getattr(args, "lan_trusted", False)),
        )
        if created:
            print(f"[OK] Isolated lab configuration created at: {out_path}")
        else:
            print(f"[!] Lab configuration already exists at: {out_path} (use -f/--force to overwrite)")
        return 0
    print("Uso: ailen lab config [init]")
    return 1


def cmd_lab_audio_devices(args: argparse.Namespace, config_path: str | None) -> int:
    """List physical ALSA hardware separately from virtual routing endpoints."""
    from ailen.audio.alsa_backend import AlsaDeviceEnumerator

    cfg = load_config(config_path)
    enumerator = AlsaDeviceEnumerator()
    capture_hw = enumerator.list_hardware_devices(is_input=True)
    playback_hw = enumerator.list_hardware_devices(is_input=False)
    endpoints = enumerator.list_devices()
    default_capture = enumerator.get_default_route(is_input=True)

    if getattr(args, "json", False):
        payload = {
            "hardware_capture": [
                {"id": d.id, "name": d.name} for d in capture_hw
            ],
            "hardware_playback": [
                {"id": d.id, "name": d.name} for d in playback_hw
            ],
            "routing_endpoints": [
                {
                    "id": d.id,
                    "name": d.name,
                    "is_input": d.is_input,
                    "is_output": d.is_output,
                    "is_default": d.is_default,
                    "backend": d.backend,
                    "state": d.state,
                    "volume_percent": d.volume_percent,
                    "volume_db": d.volume_db,
                    "is_monitor": d.is_monitor,
                }
                for d in endpoints
            ],
            "configured_capture": cfg.audio.input_device,
            "effective_default_capture": default_capture,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print("             ALSA PHYSICAL HARDWARE ENDPOINTS                    ")
    print("==================================================================")
    if capture_hw:
        print("CAPTURE (use these first for microphone tests):")
        for d in capture_hw:
            print(f"  [MIC] {d.id:<32} : {d.name}")
    else:
        print("CAPTURE: no hardware endpoints reported by `arecord -l`.")
    if playback_hw:
        print("PLAYBACK:")
        for d in playback_hw:
            print(f"  [OUT] {d.id:<32} : {d.name}")
    else:
        print("PLAYBACK: no hardware endpoints reported by `aplay -l`.")

    print("------------------------------------------------------------------")
    print("PIPEWIRE SOURCES (stable syntax: pipewire:<node-name>):")
    for d in endpoints:
        if d.backend != "pipewire" or not d.is_input or d.is_monitor:
            continue
        default_tag = " (DEFAULT)" if d.is_default else ""
        level = ""
        if d.volume_percent is not None:
            level += f" {d.volume_percent:.0f}%"
        if d.volume_db is not None:
            level += f" / {d.volume_db:.2f} dB"
        warning = "  ⚠ ATENUADA" if (
            (d.volume_percent is not None and d.volume_percent < 60.0)
            or (d.volume_db is not None and d.volume_db < -10.0)
        ) else ""
        print(
            f"  [MIC] {d.id} : {d.name}{default_tag} [{d.state or 'unknown'}]"
            f"{level}{warning}"
        )
    print(f"CONFIGURADA: {cfg.audio.input_device}")
    print(f"DEFAULT EFECTIVA: {default_capture or 'no observable'}")
    print("------------------------------------------------------------------")
    print("ALSA ROUTING/PLUGIN ENDPOINTS (not proof of physical hardware):")
    for d in endpoints:
        if d.backend != "pipewire" and (d.is_default or d.id in {"pipewire", "pulse"}):
            dtype = "INPUT" if d.is_input else "OUTPUT"
            default_tag = " (DEFAULT)" if d.is_default else ""
            print(f"  [{dtype}] {d.id:<26} : {d.name}{default_tag}")
    print("==================================================================")
    return 0


def cmd_lab_cameras(args: argparse.Namespace) -> int:
    """List physical camera devices detected in the system."""
    detector = HardwareDetector()
    report = detector.detect()
    if getattr(args, "json", False):
        print(json.dumps([{"device_path": c.device_path, "index": c.index, "name": c.name, "is_available": c.is_available} for c in report.cameras], indent=2, ensure_ascii=False))
        return 0
    print("==================================================================")
    print("                    DETECTED CAMERAS                              ")
    print("==================================================================")
    if report.cameras:
        for c in report.cameras:
            print(f"Camera [{c.index}]: {c.device_path} ({c.name})")
    else:
        print("No physical V4L2 cameras detected.")
    print("==================================================================")
    return 0


def cmd_lab(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute lab subcommand."""
    action = getattr(args, "lab_action", None)
    if action == "inspect":
        return cmd_lab_inspect(args)
    elif action == "start":
        return cmd_lab_start(args, config_path)
    elif action == "doctor":
        return cmd_lab_doctor(args, config_path)
    elif action == "preflight":
        return cmd_lab_preflight(args, config_path)
    elif action == "prepare-ai":
        return cmd_lab_prepare_ai(args, config_path)
    elif action == "prepare-speech":
        return cmd_lab_prepare_speech(args, config_path)
    elif action == "config":
        return cmd_lab_config(args)
    elif action == "audio-devices":
        return cmd_lab_audio_devices(args, config_path)
    elif action == "cameras":
        return cmd_lab_cameras(args)
    elif action == "benchmark":
        return cmd_lab_benchmark(args)
    elif action == "benchmark-ai":
        return cmd_lab_benchmark_ai(args)
    elif action == "benchmark-vision":
        return cmd_lab_benchmark_vision(args, config_path)
    elif action == "benchmark-stt":
        return cmd_lab_benchmark_stt(args, config_path)
    elif action == "calibrate-voice":
        return cmd_lab_calibrate_voice(args, config_path)
    print("Uso: ailen lab [inspect|start|doctor|preflight|prepare-ai|prepare-speech|config|audio-devices|cameras|benchmark|benchmark-ai|benchmark-vision|benchmark-stt|calibrate-voice]")
    return 1


def cmd_speech_list(args: argparse.Namespace) -> int:
    """List all speech models and voices in the catalog."""
    from ailen.speech.catalog import SpeechAssetCatalog
    from ailen.speech.store import SpeechAssetStore

    catalog = SpeechAssetCatalog()
    store = SpeechAssetStore()
    assets = catalog.list_assets(engine=getattr(args, "engine", None))

    if getattr(args, "json", False):
        out = []
        for a in assets:
            d = a.to_dict()
            d["installed"] = store.exists(a)
            d["verified"] = store.verify(a) if store.exists(a) else False
            out.append(d)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    print(f"{'ASSET ID':<32} {'ENGINE':<12} {'TYPE':<12} {'LOCALE':<8} {'GENDER':<8} {'SIZE (MB)':<10} {'INSTALLED'}")
    print("-" * 95)
    for a in assets:
        inst = "YES" if store.exists(a) else "NO"
        mb = a.expected_size_bytes / (1024 * 1024)
        print(f"{a.asset_id:<32} {a.engine:<12} {a.asset_type.value:<12} {a.locale:<8} {a.voice_gender.value:<8} {mb:<10.1f} {inst}")
    return 0


def cmd_speech_plan(args: argparse.Namespace) -> int:
    """Show recommended STT and TTS models for speech pipeline."""
    from ailen.speech.prepare import LabSpeechPreparer

    preparer = LabSpeechPreparer()
    report = preparer.inspect(
        stt_engine=getattr(args, "stt", "vosk"),
        voice_key=getattr(args, "voice", "es_ES-davefx-medium"),
    )
    if getattr(args, "json", False):
        print(json.dumps({
            "stt": {
                "engine": report.stt.engine,
                "target_asset": report.stt.target_asset.to_dict() if report.stt.target_asset else None,
                "installed": report.stt.is_installed,
                "verified": report.stt.is_verified,
                "runtime_available": report.stt.runtime_available,
            },
            "tts": {
                "engine": report.tts.engine,
                "target_asset": report.tts.target_asset.to_dict() if report.tts.target_asset else None,
                "installed": report.tts.is_installed,
                "verified": report.tts.is_verified,
                "runtime_available": report.tts.runtime_available,
            },
        }, indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print("                   RECOMMENDED SPEECH PLAN                        ")
    print("==================================================================")
    if report.stt.target_asset:
        print(f"STT Model      : {report.stt.target_asset.asset_id} ({report.stt.engine})")
        print(f"  Installed    : {'YES' if report.stt.is_installed else 'NO'}")
        print(f"  Runtime      : {report.stt.runtime_detail}")
    if report.tts.target_asset:
        print(f"TTS Voice      : {report.tts.target_asset.asset_id} (piper / {report.tts.target_asset.voice_gender.value})")
        print(f"  Installed    : {'YES' if report.tts.is_installed else 'NO'}")
        print(f"  Runtime      : {report.tts.runtime_detail}")
    print("==================================================================")
    return 0


def cmd_speech_fetch(args: argparse.Namespace) -> int:
    """Download and verify speech asset into SpeechAssetStore."""
    from ailen.speech.catalog import SpeechAssetCatalog
    from ailen.speech.downloader import SpeechAssetDownloader, SpeechDownloadError
    from ailen.speech.store import SpeechAssetStore

    asset_id = args.asset_id
    catalog = SpeechAssetCatalog()
    desc = catalog.get(asset_id)
    if not desc:
        print(f"Error: Speech asset '{asset_id}' not found in catalog. Use 'ailen speech list' to view available assets.")
        return 1

    store = SpeechAssetStore()
    if store.exists(desc) and store.verify(desc):
        print(f"Asset '{asset_id}' is already installed at {store.get_asset_path(desc)}")
        return 0

    mb = desc.expected_size_bytes / (1024 * 1024)
    print("==================================================================")
    print("                 SPEECH ASSET DOWNLOAD REQUEST                    ")
    print("==================================================================")
    print(f"Asset ID     : {desc.asset_id}")
    print(f"Engine       : {desc.engine}")
    print(f"Type         : {desc.asset_type.value}")
    print(f"Download Size: ~{mb:.1f} MB")
    print(f"Destination  : {store.get_asset_path(desc)}")
    print(f"SHA-256      : {desc.sha256}")
    print("==================================================================")

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"¿Desea descargar '{asset_id}' (~{mb:.1f} MB)? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes", "s", "si", "sí"):
                print("Descarga cancelada por el usuario.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\nOperación cancelada.")
            return 1

    downloader = SpeechAssetDownloader(store=store, catalog=catalog)
    try:
        def on_prog(downloaded: int, total: int) -> None:
            pct = (downloaded / total * 100.0) if total > 0 else 0
            mb_d = downloaded / (1024 * 1024)
            mb_t = total / (1024 * 1024)
            print(f"\rDescargando: {mb_d:.1f}/{mb_t:.1f} MB ({pct:.1f}%)", end="", flush=True)

        target = downloader.download(desc, progress_callback=on_prog)
        print(f"\nDescarga y verificación completadas con éxito: {target}")
        return 0
    except SpeechDownloadError as exc:
        print(f"\nError en la descarga: {exc}")
        return 1


def cmd_speech_verify(args: argparse.Namespace) -> int:
    """Verify SHA-256 checksum of an installed speech asset."""
    from ailen.speech.catalog import SpeechAssetCatalog
    from ailen.speech.store import SpeechAssetStore

    asset_id = args.asset_id
    catalog = SpeechAssetCatalog()
    desc = catalog.get(asset_id)
    if not desc:
        print(f"Error: Speech asset '{asset_id}' not found in catalog.")
        return 1

    store = SpeechAssetStore()
    if not store.exists(desc):
        print(f"Error: Speech asset '{asset_id}' is not installed in local store.")
        return 1

    print(f"Verifying SHA-256 for '{asset_id}'...")
    valid = store.verify(desc)
    if valid:
        print(f"SUCCESS: Integrity check passed for '{asset_id}' (SHA-256 match).")
        return 0
    print(f"FAILURE: SHA-256 mismatch for '{asset_id}'!")
    return 1


def cmd_speech(args: argparse.Namespace) -> int:
    """Execute speech subcommand."""
    action = getattr(args, "speech_action", None)
    if action == "list":
        return cmd_speech_list(args)
    elif action == "plan":
        return cmd_speech_plan(args)
    elif action == "fetch":
        return cmd_speech_fetch(args)
    elif action == "verify":
        return cmd_speech_verify(args)
    print("Uso: ailen speech [list|plan|fetch|verify]")
    return 1


def cmd_models_list(args: argparse.Namespace) -> int:
    """List all models in catalog and installation status."""
    catalog = ModelCatalog()
    store = ModelStore()
    models = catalog.list_models()

    if getattr(args, "json", False):
        out = []
        for m in models:
            d = m.to_dict()
            d["installed"] = store.exists(m.model_id)
            d["installed_size_bytes"] = store.get_size(m.model_id)
            out.append(d)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    print(f"{'MODEL ID':<35} {'FAMILY':<8} {'CLASS':<8} {'DISK (MB)':<10} {'RAM (MB)':<10} {'INSTALLED'}")
    print("-" * 85)
    for m in models:
        installed_str = "YES" if store.exists(m.model_id) else "NO"
        disk_mb = m.disk_size_bytes // (1024 * 1024)
        print(f"{m.model_id:<35} {m.family:<8} {m.parameter_class:<8} {disk_mb:<10} {m.ram_requirement_mb:<10} {installed_str}")
    return 0


def cmd_models_plan(args: argparse.Namespace) -> int:
    """Evaluate and print recommended model plan for current hardware."""
    from ailen.models.catalog import ModelPurpose

    store = ModelStore()
    detector = HardwareDetector()
    report = detector.detect(str(store.base_dir))
    rec = detector.recommend_profile(report)
    planner = ModelPlanner()

    purpose_str = getattr(args, "purpose", "BALANCED").upper()
    purpose = ModelPurpose(purpose_str) if purpose_str in ModelPurpose._value2member_map_ else ModelPurpose.BALANCED
    require_downloadable = not getattr(args, "all", False)

    plan = planner.plan(report, profile=rec.profile, purpose=purpose, require_downloadable=require_downloadable)

    if getattr(args, "json", False):
        print(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print("                   RECOMMENDED MODEL PLAN                         ")
    print("==================================================================")
    if plan.is_viable and plan.model_descriptor:
        print(f"Selected Model : {plan.selected_model_id}")
        print(f"Display Name   : {plan.model_descriptor.display_name}")
        print(f"Device / Layer : {plan.device.upper()} (gpu_layers={plan.gpu_layers})")
        print(f"Estimated RAM  : {plan.estimated_ram_mb} MB")
        print(f"Estimated VRAM : {plan.estimated_vram_mb} MB")
        print(f"Context Window : {plan.context_size}")
        print(f"Reasons        : {', '.join(plan.reason_codes)}")
    else:
        print("Status         : NO VIABLE LOCAL MODEL PLAN")
        print(f"Reasons        : {', '.join(plan.reason_codes)}")
    print("==================================================================")
    return 0


def cmd_models_fetch(args: argparse.Namespace) -> int:
    """Download and verify model artifact into ModelStore."""
    model_id = args.model_id
    catalog = ModelCatalog()
    descriptor = catalog.get_model(model_id)
    if not descriptor:
        print(f"Error: Model '{model_id}' not found in catalog. Use 'ailen models list' to view available models.")
        return 1
    if not descriptor.downloadable:
        print(
            f"Error: Model '{model_id}' is catalog metadata only and is not approved for download. "
            "Choose a verified downloadable model from `ailen models list`."
        )
        return 1

    store = ModelStore()
    if store.exists(model_id):
        print(f"Model '{model_id}' is already installed at {store.get_model_path(model_id)}")
        return 0

    disk_mb = descriptor.disk_size_bytes // (1024 * 1024)
    print("==================================================================")
    print("                  MODEL DOWNLOAD REQUEST                          ")
    print("==================================================================")
    print(f"Model ID     : {descriptor.model_id}")
    print(f"Display Name : {descriptor.display_name}")
    print(f"Download Size: ~{disk_mb} MB")
    print(f"Destination  : {store.get_model_path(model_id)}")
    print(f"SHA-256      : {descriptor.sha256}")
    print("==================================================================")

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"¿Desea descargar '{model_id}' ({disk_mb} MB)? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes", "s", "si", "sí"):
                print("Descarga cancelada por el usuario.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\nOperación cancelada.")
            return 1

    downloader = ModelDownloader(store=store)
    try:
        def on_progress(downloaded: int, total: int) -> None:
            pct = (downloaded / total * 100.0) if total > 0 else 0
            mb_done = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            print(f"\rDescargando: {mb_done:.1f}/{mb_total:.1f} MB ({pct:.1f}%)", end="", flush=True)

        target_path = downloader.download(descriptor, progress_callback=on_progress)
        print(f"\nDescarga y verificación completadas con éxito: {target_path}")
        return 0
    except ModelDownloadError as e:
        print(f"\nError en la descarga: {e}")
        return 1


def cmd_models_verify(args: argparse.Namespace) -> int:
    """Verify SHA-256 integrity of an installed model."""
    model_id = args.model_id
    catalog = ModelCatalog()
    descriptor = catalog.get_model(model_id)
    if not descriptor:
        print(f"Error: Model '{model_id}' not found in catalog.")
        return 1

    store = ModelStore()
    if not store.exists(model_id):
        print(f"Error: Model '{model_id}' is not installed in local store ({store.base_dir}).")
        return 1

    print(f"Verifying SHA-256 for '{model_id}'...")
    valid = store.verify(model_id, descriptor.sha256)
    if valid:
        print(f"SUCCESS: Integrity check passed for '{model_id}' (SHA-256 match).")
        return 0
    print(f"FAILURE: SHA-256 mismatch for '{model_id}'!")
    return 1


def cmd_models_provision_plan(args: argparse.Namespace) -> int:
    """Print the canonical installation decision without downloading anything."""

    from ailen.provisioning.planner import (
        HardwareQualificationStore,
        ProvisioningPlanner,
    )

    store = ModelStore()
    report = HardwareDetector().detect(str(store.base_dir))
    try:
        qualifications = HardwareQualificationStore.from_directory(
            Path(str(args.qualification_dir))
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: evidencia de calificación inválida: {exc}")
        return 1
    plan = ProvisioningPlanner(qualifications=qualifications).plan(
        report,
        topology=str(args.topology),
        manual_model_override=str(args.model_override).strip() or None,
    )
    if getattr(args, "json", False):
        print(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print(" AILEN PROVISIONING PLAN — no downloads performed")
    print("==================================================================")
    print(f"Hardware class : {plan.hardware_class}")
    print(f"Tier / topology: {plan.hardware_tier} / {plan.topology}")
    print(f"Runtime        : {plan.runtime} ({plan.runtime_reason})")
    print(f"Execution      : {plan.execution_device} (GPU layers: {plan.gpu_layers})")
    print(f"Primary model  : {plan.primary_model_id or 'none qualified'}")
    print(f"Candidates     : {list(plan.candidate_model_ids)}")
    print(f"Auto-download  : {'eligible after consent' if plan.auto_download_allowed else 'blocked'}")
    print(f"Consent actions: {list(plan.consent_actions)}")
    print(f"Reasons        : {', '.join(plan.reason_codes)}")
    print("==================================================================")
    return 0


def cmd_models_qualification_template(args: argparse.Namespace) -> int:
    """Create an evidence template without resolving or downloading weights."""
    from ailen.models.qualification import qualification_template

    descriptor = ModelCatalog().get_model(str(args.model_id))
    if descriptor is None:
        print(f"Error: Model '{args.model_id}' not found in catalog.")
        return 1
    destination = Path(
        str(args.output).strip()
        or f"runtime/lab/model_qualification/{descriptor.model_id}.json"
    )
    if destination.exists() and not bool(args.force):
        print(f"Error: {destination} already exists (use --force to replace it).")
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(qualification_template(descriptor).to_json(), encoding="utf-8")
    print(f"Manifest candidato creado: {destination}")
    print("No se descargaron pesos ni se certificó hardware.")
    return 0


def cmd_models_qualification_validate(args: argparse.Namespace) -> int:
    """Validate a qualification manifest and fail closed on incomplete proof."""
    from ailen.models.qualification import ModelQualificationManifest

    source = Path(str(args.manifest))
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("manifest root must be an object")
        manifest = ModelQualificationManifest.from_dict(raw)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: manifest inválido: {exc}")
        return 1
    missing = manifest.missing_for_qualification()
    if missing:
        print(f"NO CALIFICADO ({manifest.status.value}): faltan {', '.join(missing)}")
        return 2
    print(f"EVIDENCIA COMPLETA: {manifest.model_id} ({manifest.status.value})")
    return 0

def cmd_models(args: argparse.Namespace) -> int:
    """Execute models subcommand."""
    action = getattr(args, "models_action", None)
    if action == "list":
        return cmd_models_list(args)
    elif action == "plan":
        return cmd_models_plan(args)
    elif action == "provision-plan":
        return cmd_models_provision_plan(args)
    elif action == "fetch":
        return cmd_models_fetch(args)
    elif action == "verify":
        return cmd_models_verify(args)
    elif action == "qualification-template":
        return cmd_models_qualification_template(args)
    elif action == "qualification-validate":
        return cmd_models_qualification_validate(args)
    print("Uso: ailen models [list|plan|provision-plan|fetch|verify|qualification-template|qualification-validate]")
    return 1


def cmd_demo(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute demo subcommand."""
    target = getattr(args, "demo_target", None)
    if target == "face":
        return cmd_demo_face(args, config_path)
    elif target == "vision":
        return cmd_demo_vision(args, config_path)
    elif target == "vad":
        return cmd_demo_vad(args)
    elif target == "stt":
        return cmd_demo_stt(args, config_path)
    elif target == "tts":
        return cmd_demo_tts(args, config_path)
    elif target == "ai":
        return cmd_demo_ai(args, config_path)
    print("Uso: ailen demo [face|vision|vad|stt|tts|ai]")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "diagnose":
        target = getattr(args, "diag_target", None)
        if target == "hardware":
            return cmd_diagnose_hardware(args)
        elif target == "audio":
            return cmd_diagnose_audio(args, args.config_path)
        elif target == "ai":
            return cmd_diagnose_ai(args, args.config_path)
        else:
            print("Use: ailen diagnose [hardware|audio|ai]")
            return 1

    if args.command == "config":
        return cmd_config(args, args.config_path)

    if args.command == "db":
        return cmd_db(args, args.config_path)

    if args.command == "status":
        return cmd_status(args, args.config_path)

    if args.command == "admin":
        if getattr(args, "admin_action", None) == "set-password":
            return cmd_admin_set_password(args, args.config_path)
        print("Use: ailen admin set-password")
        return 1

    if args.command == "serve":
        return cmd_serve(args, args.config_path)

    if args.command == "demo":
        return cmd_demo(args, args.config_path)

    if args.command == "lab":
        return cmd_lab(args, args.config_path)

    if args.command == "speech":
        return cmd_speech(args)

    if args.command == "models":
        return cmd_models(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

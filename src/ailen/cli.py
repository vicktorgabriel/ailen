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
    demo_parser = subparsers.add_parser("demo", help="Interactive physical presence, face, and audio demos")
    demo_sub = demo_parser.add_subparsers(dest="demo_target", help="Demo target component")

    # Subcommand: demo face
    demo_face = demo_sub.add_parser("face", help="Interactive Face animator and renderer demo")
    demo_face.add_argument("--headless", action="store_true", help="Run headless in terminal without opening GUI window")
    demo_face.add_argument("--gui", action="store_true", help="Force opening GUI window (Tkinter)")
    demo_face.add_argument("--duration", type=float, default=None, help="Run demo for N seconds and exit")
    demo_face.add_argument("--fps", type=int, default=30, help="Target FPS (default: 30)")

    # Subcommand: demo vision
    demo_vis = demo_sub.add_parser("vision", help="Camera presence detection and debounce demo")
    demo_vis.add_argument("--camera", default="/dev/video0", help="Camera device path or index (default: /dev/video0)")
    demo_vis.add_argument("--debounce", type=float, default=2.0, help="Debounce window in seconds (default: 2.0)")
    demo_vis.add_argument("--duration", type=float, default=10.0, help="Run duration in seconds (default: 10.0)")

    # Subcommand: demo vad
    demo_vad = demo_sub.add_parser("vad", help="Real-time Voice Activity Detection (VAD) demo")
    demo_vad.add_argument("--device", default="default", help="Input device (default: default)")
    demo_vad.add_argument("--threshold", type=float, default=0.02, help="VAD RMS threshold (default: 0.02)")
    demo_vad.add_argument("--duration", type=float, default=5.0, help="Run duration in seconds (default: 5.0)")

    # Subcommand: demo stt
    demo_stt = demo_sub.add_parser("stt", help="Speech-to-Text transcription demo")
    demo_stt.add_argument("--device", default="default", help="Input device (default: default)")
    demo_stt.add_argument("--engine", default="mock", help="STT engine (mock, vosk, whisper_cpp)")
    demo_stt.add_argument("--model", default="", help="STT model path")
    demo_stt.add_argument("--duration", type=float, default=6.0, help="Listen duration in seconds (default: 6.0)")

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
    lab_start.add_argument("--duration", type=float, default=None, help="Run for N seconds and terminate cleanly")
    lab_sub.add_parser("doctor", help="Run non-invasive system readiness diagnostic")
    lab_bench = lab_sub.add_parser("benchmark", help="Run reproducible lab benchmark harness")
    lab_bench.add_argument("--output", default="runtime/lab/benchmarks", help="Destination directory for benchmark artifact")

    # Command: models
    models_parser = subparsers.add_parser("models", help="Manage local GGUF model catalog and storage")
    models_sub = models_parser.add_subparsers(dest="models_action", help="Models action")
    models_list = models_sub.add_parser("list", help="List all catalog models and installation status")
    models_list.add_argument("--json", action="store_true", help="Output as JSON")
    models_plan = models_sub.add_parser("plan", help="Evaluate hardware capabilities and output recommended model plan")
    models_plan.add_argument("--json", action="store_true", help="Output as JSON")
    models_fetch = models_sub.add_parser("fetch", help="Download and verify a model from catalog")
    models_fetch.add_argument("model_id", help="Model ID from catalog (e.g. qwen2.5-0.5b-instruct-q4_k_m)")
    models_fetch.add_argument("-y", "--yes", action="store_true", help="Bypass interactive confirmation prompt")
    models_verify = models_sub.add_parser("verify", help="Verify SHA-256 integrity of an installed model")
    models_verify.add_argument("model_id", help="Model ID to verify in local store")

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
    status = StatusService(health_service=health)
    config_service = ConfigService(config_path)
    settings = SettingsService(config_service)
    app = AILENWebApp(auth=auth, status=status, settings=settings)

    logger.info("Starting AILEN web panel on %s:%d", host, port)
    print(f"AILEN Foundation v{__version__} running at http://{host}:{port}. Press Ctrl+C to stop.")
    serve_web(app, host=host, port=port)
    return 0


def cmd_demo_face(args: argparse.Namespace) -> int:
    """Run interactive Face animator demo."""
    from ailen.face.animator import FaceAnimator
    from ailen.face.gui import TkinterFaceController

    force_headless = getattr(args, "headless", False)
    force_gui = getattr(args, "gui", False)
    fps = max(1, getattr(args, "fps", 30))
    duration = getattr(args, "duration", None)

    gui = TkinterFaceController(fps_limit=fps)
    can_gui = gui.is_available() and not force_headless

    if force_gui and not gui.is_available():
        print("Aviso: Tkinter no está disponible en este entorno; ejecutando en modo headless.")

    if can_gui and (force_gui or not force_headless):
        try:
            print("==========================================================")
            print(" AILEN Face POC — Demo interactiva (Tkinter 2D Canvas)")
            print(" Controles de teclado:")
            print("   1..8  : IDLE, ATTENTION, LISTENING, PROCESSING, SPEAKING, SLEEP, WAKE, ERROR")
            print("   Flechas: Orientar mirada (Gaze)")
            print("   Espacio: Nivel de apertura de boca (habla)")
            print("   Q / Esc: Salir")
            print("==========================================================")
            gui.start_window(interactive_keys=True)
            if duration:
                gui.schedule_close(int(duration * 1000))
            gui.mainloop()
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"No se pudo iniciar ventana gráfica ({e}); pasando a modo headless.")

    # Headless loop
    import time

    print("==========================================================")
    print(f" AILEN Face POC — Demo Headless (FPS objetivo: {fps})")
    print(" Presioná Ctrl+C para detener.")
    print("==========================================================")
    animator = FaceAnimator()
    start_t = time.time()
    frame_count = 0
    interval = 1.0 / fps

    states = [
        (0.0, AssistantState.IDLE, (0.0, 0.0), 0.0),
        (2.0, AssistantState.ATTENTION, (0.4, 0.1), 0.0),
        (4.0, AssistantState.LISTENING, (0.4, 0.1), 0.0),
        (6.0, AssistantState.PROCESSING, (-0.2, 0.5), 0.0),
        (8.0, AssistantState.SPEAKING, (0.0, 0.0), 0.7),
        (10.0, AssistantState.SLEEP, (0.0, -0.2), 0.0),
        (12.0, AssistantState.IDLE, (0.0, 0.0), 0.0),
    ]
    cur_idx = 0

    try:
        while True:
            now = time.time()
            elapsed = now - start_t
            if duration and elapsed >= duration:
                break

            # Cycle demo states every few seconds in headless mode
            if cur_idx < len(states) - 1 and elapsed >= states[cur_idx + 1][0]:
                cur_idx += 1
                _, state, gaze, speech = states[cur_idx]
                animator.set_state(state)
                animator.set_gaze(*gaze)
                animator.set_speech_level(speech)

            pose = animator.step(current_time=now)
            frame_count += 1

            if frame_count % fps == 0 or frame_count == 1:
                fps_achieved = frame_count / max(0.001, elapsed)
                print(
                    f"[{elapsed:5.1f}s | {fps_achieved:4.1f} FPS] State={animator.state.value:10} "
                    f"| Gaze=({pose.gaze_x:+.2f}, {pose.gaze_y:+.2f}) "
                    f"| Eyes=(L:{pose.left_eye_open:.2f}, R:{pose.right_eye_open:.2f}) "
                    f"| Mouth={pose.mouth_open:.2f} | Expr={pose.expression:8}"
                )

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nDemo detenida por el usuario.")

    print(f"Demo headless completada. Total frames: {frame_count}")
    return 0


def cmd_demo_vision(args: argparse.Namespace, config_path: str | None) -> int:
    """Run camera presence detection and debounce demo."""
    import time

    from ailen.vision.debouncer import VisionDebouncer
    from ailen.vision.opencv_backend import OpenCvVisionBackend

    camera_dev = getattr(args, "camera", "/dev/video0")
    debounce_sec = float(getattr(args, "debounce", 2.0))
    duration = float(getattr(args, "duration", 10.0))

    backend = OpenCvVisionBackend(camera_device=camera_dev, fps=5)
    debouncer = VisionDebouncer(debounce_seconds=debounce_sec)

    print("==========================================================")
    print(" AILEN Vision POC — Demo de Presencia y Debounce")
    print(f" Dispositivo: {camera_dev} | Ventana Debounce: {debounce_sec}s | Duración: {duration}s")
    print("==========================================================")

    backend.start()
    health = backend.health()
    print(f"Estado del backend: {health.status.value} ({health.detail})")

    start_t = time.time()
    try:
        while time.time() - start_t < duration:
            raw = backend.get_latest_presence()
            stable = debouncer.update(raw)
            elapsed = time.time() - start_t
            print(
                f"[{elapsed:4.1f}s] Raw present={raw.present!s:5} (Caras: {raw.faces_count}) "
                f"--> Debounced present={stable.present!s:5} "
                f"| Gaze=({stable.primary_x_normalized or 0.0:+.2f}, {stable.primary_y_normalized or 0.0:+.2f})"
            )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nDemo vision interrumpida.")
    finally:
        backend.stop()

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
    """Run AI Router, Local, LAN Brain, and Cloud LLM diagnostics."""
    from ailen.ai.budget import BudgetPolicy
    from ailen.ai.cloud_backend import CloudAiBackend
    from ailen.ai.contracts import BackendHealth
    from ailen.ai.lan_backend import LanBrainAiBackend
    from ailen.ai.local_backend import LocalAiBackend
    from ailen.ai.secrets import SecretResolver
    from ailen.core.config import load_config
    from ailen.domain.enums import ServiceStatus
    from ailen.infrastructure.sqlite.connection import SQLiteManager
    from ailen.memory.repository import MemoryRepository

    cfg = load_config(config_path)
    db_mgr = SQLiteManager(cfg.memory.sqlite_path)
    repo = MemoryRepository(db_mgr)
    budget_policy = BudgetPolicy(
        repository=repo,
        daily_budget_usd=cfg.ai.cloud.daily_budget_usd,
        monthly_budget_usd=cfg.ai.cloud.monthly_budget_usd,
    )
    budget_avail, budget_reason, spending = budget_policy.is_budget_available()

    # Local backend health
    local_backend = LocalAiBackend(
        endpoint=cfg.ai.local.endpoint,
        model=cfg.ai.local.model,
        timeout_seconds=cfg.ai.local.timeout_seconds,
    )
    local_health = local_backend.health() if cfg.ai.local.enabled else BackendHealth(ServiceStatus.DISABLED, "Disabled in config")

    # LAN Brain health
    lan_backend = LanBrainAiBackend(
        endpoint=cfg.ai.lan.endpoint,
        model=cfg.ai.lan.model,
        trusted=cfg.ai.lan.trusted,
        timeout_seconds=cfg.ai.lan.timeout_seconds,
    )
    lan_health = lan_backend.health() if cfg.ai.lan.enabled else BackendHealth(ServiceStatus.DISABLED, "Disabled in config")

    # Cloud backend health
    secret_resolver = SecretResolver()
    has_key = secret_resolver.resolve(
        env_var=cfg.ai.cloud.api_key_env,
        file_name=cfg.ai.cloud.api_key_file,
    ) is not None

    cloud_backend = CloudAiBackend(
        endpoint=cfg.ai.cloud.endpoint,
        model=cfg.ai.cloud.model,
        api_key_env=cfg.ai.cloud.api_key_env,
        api_key_file=cfg.ai.cloud.api_key_file,
        secrets_resolver=secret_resolver,
        timeout_seconds=cfg.ai.cloud.timeout_seconds,
        provider_name=cfg.ai.cloud.provider,
        input_cost_per_million=cfg.ai.cloud.input_cost_per_million,
        output_cost_per_million=cfg.ai.cloud.output_cost_per_million,
    )
    cloud_health = cloud_backend.health() if cfg.ai.cloud.enabled else BackendHealth(ServiceStatus.DISABLED, "Disabled in config")

    report: dict[str, Any] = {
        "node_profile": cfg.node.profile.value,
        "default_provider": cfg.ai.provider,
        "allow_cloud": cfg.ai.allow_cloud,
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
        "cloud": {
            "enabled": cfg.ai.cloud.enabled,
            "provider": cfg.ai.cloud.provider,
            "endpoint": cfg.ai.cloud.endpoint,
            "model": cfg.ai.cloud.model,
            "api_key_configured": has_key,
            "status": cloud_health.status.value,
            "detail": cloud_health.detail,
        },
        "budget": {
            "daily_spent_usd": spending["daily_spent_usd"],
            "daily_limit_usd": cfg.ai.cloud.daily_budget_usd,
            "monthly_spent_usd": spending["monthly_spent_usd"],
            "monthly_limit_usd": cfg.ai.cloud.monthly_budget_usd,
            "budget_available": budget_avail,
            "reason_code": budget_reason,
        },
    }

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("==================================================================")
    print(" AILEN AI Diagnostics — Hybrid AI Router & Providers")
    print("==================================================================")
    print(f" Perfil de Dispositivo : {cfg.node.profile.value}")
    print(f" Proveedor por defecto : {cfg.ai.provider} | Allow Cloud: {cfg.ai.allow_cloud}")
    print("------------------------------------------------------------------")
    print(f" Local LLM Server      : {'ENABLED' if cfg.ai.local.enabled else 'DISABLED'} | Status: {local_health.status.value} ({local_health.detail})")
    print(f"   Endpoint: {cfg.ai.local.endpoint} | Model: {cfg.ai.local.model}")
    print(f" LAN Brain Server      : {'ENABLED' if cfg.ai.lan.enabled else 'DISABLED'} | Status: {lan_health.status.value} ({lan_health.detail})")
    print(f"   Endpoint: {cfg.ai.lan.endpoint} | Trusted: {cfg.ai.lan.trusted} | Model: {cfg.ai.lan.model}")
    print(f" Cloud Provider        : {'ENABLED' if cfg.ai.cloud.enabled else 'DISABLED'} | Status: {cloud_health.status.value} ({cloud_health.detail})")
    print(f"   Endpoint: {cfg.ai.cloud.endpoint} | Model: {cfg.ai.cloud.model} | API Key: {'CONFIGURED' if has_key else 'NOT FOUND'}")
    print("------------------------------------------------------------------")
    print(f" Presupuesto Cloud     : {'DISPONIBLE' if budget_avail else 'EXCEDIDO (' + budget_reason + ')'}")
    print(f"   Gasto Hoy: ${spending['daily_spent_usd']:.4f} / ${cfg.ai.cloud.daily_budget_usd:.2f}")
    print(f"   Gasto Mes: ${spending['monthly_spent_usd']:.4f} / ${cfg.ai.cloud.monthly_budget_usd:.2f}")
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

    backend.start()
    health = backend.health()
    use_synthetic = health.status.value != "HEALTHY"
    if use_synthetic:
        print(f"Aviso: Backend ALSA en estado {health.status.value} ({health.detail}); ejecutando demo con stream simulado.")

    start_t = time.time()
    try:
        step = 0
        while time.time() - start_t < duration:
            step += 1
            if not use_synthetic:
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

    alsa_in = AlsaAudioInputBackend(device=device, sample_rate=16000, channels=1)
    alsa_in.start()
    is_real = alsa_in.health().status.value == "HEALTHY"
    alsa_in.stop()

    audio_input: Any = AlsaAudioInputBackend(device=device) if is_real else FakeAudioInputBackend()

    coordinator = AudioInteractionCoordinator(
        audio_input=audio_input,
        stt=stt_backend,
    )

    print("==========================================================")
    print(" AILEN Audio POC — Demo STT (Speech-to-Text)")
    print(f" Motor: {engine} | Dispositivo: {device} | Duración: {duration}s")
    print(f" Estado backend STT: {stt_backend.health().status.value} ({stt_backend.health().detail})")
    print("==========================================================")

    if not is_real:
        print("Aviso: Dispositivo de micrófono no disponible; inyectando enunciado sintético simulado.")
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
    """Run AI routing and inference demo."""
    from ailen.ai.budget import BudgetPolicy
    from ailen.ai.cloud_backend import CloudAiBackend
    from ailen.ai.context import AiContextBuilder
    from ailen.ai.fake import FakeAiBackend
    from ailen.ai.lan_backend import LanBrainAiBackend
    from ailen.ai.local_backend import LocalAiBackend
    from ailen.ai.orchestrator import AiOrchestrator
    from ailen.ai.router import RouteRequest, RuleBasedRouter
    from ailen.core.config import load_config
    from ailen.domain.enums import DeviceProfile, PrivacyLevel, SocialMode
    from ailen.infrastructure.sqlite.connection import SQLiteManager
    from ailen.memory.repository import MemoryRepository

    cfg = load_config(config_path)
    prompt = getattr(args, "prompt", "Hola")
    dry_run = getattr(args, "dry_run", False)
    mode_str = getattr(args, "mode", "WORKSHOP")
    privacy_str = getattr(args, "privacy", "PRIVATE")
    profile_str = getattr(args, "profile", None)
    intent_str = getattr(args, "intent", "chat")

    try:
        social_mode = SocialMode(mode_str)
    except ValueError:
        social_mode = SocialMode.WORKSHOP

    try:
        privacy_level = PrivacyLevel(privacy_str)
    except ValueError:
        privacy_level = PrivacyLevel.PRIVATE

    profile = cfg.node.profile
    if profile_str:
        try:
            profile = DeviceProfile(profile_str)
        except ValueError:
            pass

    db_mgr = SQLiteManager(cfg.memory.sqlite_path)
    repo = MemoryRepository(db_mgr)
    budget_policy = BudgetPolicy(
        repository=repo,
        daily_budget_usd=cfg.ai.cloud.daily_budget_usd,
        monthly_budget_usd=cfg.ai.cloud.monthly_budget_usd,
    )
    budget_avail, _budget_reason, _ = budget_policy.is_budget_available()

    router = RuleBasedRouter()
    context_builder = AiContextBuilder(
        repository=repo,
        default_identity_name=cfg.identity.display_name,
    )

    # Route decision
    route_req = RouteRequest(
        intent=intent_str,
        profile=profile,
        privacy_level=privacy_level,
        internet_available=cfg.ai.allow_cloud,
        lan_brain_available=cfg.ai.lan.enabled,
        lan_brain_trusted=cfg.ai.lan.trusted,
        local_backend_available=cfg.ai.local.enabled,
        cloud_allowed=cfg.ai.cloud.enabled and cfg.ai.allow_cloud,
        budget_exceeded=not budget_avail,
    )
    plan = router.route(route_req)

    ai_req = context_builder.build_request(
        user_message=prompt,
        mode=social_mode,
        privacy_level=privacy_level,
        identity_name=cfg.identity.display_name,
        destination=plan.primary_backend,
        lan_trusted=cfg.ai.lan.trusted,
    )

    print("==========================================================")
    print(" AILEN AI Demo — Hybrid Routing & Context")
    print(f" Mensaje: \"{prompt}\"")
    print(f" Perfil: {profile.value} | Modo: {social_mode.value} | Privacidad: {privacy_level.value}")
    print(f" Destino Primario : {plan.primary_backend.upper()}")
    print(f" Fallbacks        : {[fb.upper() for fb in plan.fallback_backends]}")
    print(f" Motivo (Reason)  : {plan.reason_code}")
    print(f" Decisión Privacy : {plan.privacy_decision}")
    print(f" Memorias Context : {len(ai_req.retrieved_memory)} ítems")
    print("==========================================================")

    if dry_run:
        print("[DRY-RUN] Decisión de enrutamiento completada sin llamadas de red.")
        return 0

    # Build orchestrator with active backends (or fake fallback)
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
    if cfg.ai.cloud.enabled:
        backends["cloud"] = CloudAiBackend(
            endpoint=cfg.ai.cloud.endpoint,
            model=cfg.ai.cloud.model,
            api_key_env=cfg.ai.cloud.api_key_env,
            api_key_file=cfg.ai.cloud.api_key_file,
            timeout_seconds=cfg.ai.cloud.timeout_seconds,
            provider_name=cfg.ai.cloud.provider,
            input_cost_per_million=cfg.ai.cloud.input_cost_per_million,
            output_cost_per_million=cfg.ai.cloud.output_cost_per_million,
        )
    if not backends:
        backends["local"] = FakeAiBackend(canned_response="Respuesta simulada local (sin servidor configurado)")
        backends["fake"] = backends["local"]

    orchestrator = AiOrchestrator(backends=backends, router=router, repository=repo)
    resp, _exec_plan = orchestrator.execute(ai_req, plan=plan)

    print(f"Respuesta ({resp.provider}/{resp.model}): \"{resp.text}\"")
    print(f"Latencia: {resp.latency_ms:.1f}ms | Tokens In/Out: {resp.usage.input_tokens}/{resp.usage.output_tokens} | Finish: {resp.finish_reason}")
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
        print("  Status         : NO VIABLE LOCAL MODEL PLAN (will delegate to LAN Brain or Cloud)")
        print(f"  Reasons        : {', '.join(plan.reason_codes)}")
    print("==================================================================")
    return 0


def cmd_lab_start(args: argparse.Namespace, config_path: str | None) -> int:
    """Start AILEN in Lab Mode using dedicated non-invasive LabRunner."""
    from ailen.runtime.runner import LabRunner

    cfg = load_config(config_path)
    runner = LabRunner(
        config=cfg,
        dry_run=getattr(args, "dry_run", False),
        headless=getattr(args, "headless", False),
        no_camera=getattr(args, "no_camera", False),
        no_audio=getattr(args, "no_audio", False),
        no_ai=getattr(args, "no_ai", False),
        duration=getattr(args, "duration", None),
    )
    return runner.start()


def cmd_lab_doctor(args: argparse.Namespace, config_path: str | None) -> int:
    """Run non-invasive Lab Doctor diagnostics."""
    from ailen.runtime.doctor import LabDoctor

    cfg = load_config(config_path)
    doctor = LabDoctor(config=cfg)
    return doctor.print_report()


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


def cmd_lab(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute lab subcommand."""
    action = getattr(args, "lab_action", None)
    if action == "inspect":
        return cmd_lab_inspect(args)
    elif action == "start":
        return cmd_lab_start(args, config_path)
    elif action == "doctor":
        return cmd_lab_doctor(args, config_path)
    elif action == "benchmark":
        return cmd_lab_benchmark(args)
    print("Uso: ailen lab [inspect|start|doctor|benchmark]")
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
    store = ModelStore()
    detector = HardwareDetector()
    report = detector.detect(str(store.base_dir))
    rec = detector.recommend_profile(report)
    planner = ModelPlanner()
    plan = planner.plan(report, profile=rec.profile)

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
    else:
        print(f"FAILURE: SHA-256 mismatch for '{model_id}'!")
        return 1


def cmd_models(args: argparse.Namespace) -> int:
    """Execute models subcommand."""
    action = getattr(args, "models_action", None)
    if action == "list":
        return cmd_models_list(args)
    elif action == "plan":
        return cmd_models_plan(args)
    elif action == "fetch":
        return cmd_models_fetch(args)
    elif action == "verify":
        return cmd_models_verify(args)
    print("Uso: ailen models [list|plan|fetch|verify]")
    return 1


def cmd_demo(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute demo subcommand."""
    target = getattr(args, "demo_target", None)
    if target == "face":
        return cmd_demo_face(args)
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

    if args.command == "models":
        return cmd_models(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command Line Interface (CLI) for AILEN."""

import argparse
import getpass
import json
import logging
import sys
from pathlib import Path

from ailen.core.config import dump_config_toml, load_config, validate_config
from ailen.core.diagnostics import HardwareDiagnostics, format_hardware_report
from ailen.core.health import HealthService
from ailen.core.logging import setup_logging
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
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
    diag_parser = subparsers.add_parser("diagnose", help="Hardware diagnostics and discovery")
    diag_sub = diag_parser.add_subparsers(dest="diag_target", help="Diagnostics target")
    hw_parser = diag_sub.add_parser("hardware", help="Inspect system hardware and recommend profile")
    hw_parser.add_argument("--json", action="store_true", help="Output report as JSON")

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
    demo_parser = subparsers.add_parser("demo", help="Interactive physical presence and face demos")
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


def cmd_demo(args: argparse.Namespace, config_path: str | None) -> int:
    """Execute demo subcommand."""
    target = getattr(args, "demo_target", None)
    if target == "face":
        return cmd_demo_face(args)
    elif target == "vision":
        return cmd_demo_vision(args, config_path)
    print("Uso: ailen demo face | ailen demo vision")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "diagnose":
        if getattr(args, "diag_target", None) == "hardware":
            return cmd_diagnose_hardware(args)
        else:
            print("Use: ailen diagnose hardware")
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

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

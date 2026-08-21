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

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

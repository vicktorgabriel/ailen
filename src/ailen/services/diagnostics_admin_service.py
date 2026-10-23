"""Read-only diagnostics projected into bounded, content-free admin snapshots."""

import json
import math
import os
import re
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ailen.core.config import AILENConfig
from ailen.domain.models import HealthReport, RuntimeState, utc_now_iso
from ailen.runtime.doctor import DiagnosticCheck, LabDoctor


class DiagnosticStatus(Protocol):
    def get_health_report(self) -> HealthReport: ...
    def get_runtime_state(self) -> RuntimeState: ...


@dataclass(frozen=True)
class CheckSummary:
    name: str
    result: str


@dataclass(frozen=True)
class LatencySummary:
    label: str
    samples: int
    average_ms: float | None
    p95_ms: float | None


@dataclass(frozen=True)
class TelemetrySummary:
    state: str = "NO_DATA"
    ended_at: str = ""
    rows: tuple[LatencySummary, ...] = ()


@dataclass(frozen=True)
class DiagnosticsSnapshot:
    health: str
    components: tuple[tuple[str, str], ...]
    assistant_state: str
    checked_at: str
    doctor_state: str
    doctor_checked_at: str
    checks: tuple[CheckSummary, ...]
    telemetry: TelemetrySummary


class DiagnosticsAdmin(Protocol):
    def snapshot(self) -> DiagnosticsSnapshot: ...
    def run_checks(self) -> bool: ...


class DiagnosticsAdminService:
    """GET reads health and the latest finished Lab report; POST runs Doctor.

    No raw logs, model paths, prompts or exception messages cross this boundary.
    The reports directory is set by composition, never by a Web request.
    """

    _MAX_REPORT_BYTES = 1024 * 1024
    _MAX_DIRECTORY_ENTRIES = 4096
    _CHECK_NAMES = frozenset({
        "Python Environment", "Tkinter GUI", "OpenCV Vision", "CPU Instruction Sets",
        "System Memory", "Audio Devices", "Camera Devices", "STT Voice Model",
        "TTS Voice Model", "Local AI Runtime", "Model Storage Disk", "Recommended Model",
        "Remote AI Providers",
    })

    def __init__(
        self, status: DiagnosticStatus, config: Callable[[], AILENConfig],
        reports_dir: Path | None = None, *,
        check_runner: Callable[[AILENConfig], list[DiagnosticCheck]] | None = None,
    ) -> None:
        self._status = status
        self._config = config
        self._reports_dir = reports_dir
        self._check_runner = check_runner or (lambda cfg: LabDoctor(cfg).run_all_checks())
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._doctor_state = "NOT_RUN"
        self._doctor_checked_at = ""
        self._checks: tuple[CheckSummary, ...] = ()

    def run_checks(self) -> bool:
        if not self._run_lock.acquire(blocking=False):
            return False
        try:
            with self._state_lock:
                self._doctor_state, self._checks = "RUNNING", ()
            try:
                raw_checks = self._check_runner(self._config())
                checks = tuple(CheckSummary(
                    item.name if item.name in self._CHECK_NAMES else "Proveedor / componente",
                    item.result if item.result in {"PASS", "WARN", "FAIL", "SKIP"} else "UNKNOWN",
                ) for item in raw_checks[:64])
                results = {item.result for item in checks}
                state = (
                    "FAIL" if "FAIL" in results else "WARN" if "WARN" in results
                    else "UNKNOWN" if not checks or "UNKNOWN" in results
                    else "PASS" if "PASS" in results else "SKIP"
                )
            except Exception:  # noqa: BLE001 - public boundary redacts backend failures
                checks, state = (), "UNAVAILABLE"
            with self._state_lock:
                self._checks, self._doctor_state = checks, state
                self._doctor_checked_at = utc_now_iso()
            return True
        finally:
            self._run_lock.release()

    def snapshot(self) -> DiagnosticsSnapshot:
        try:
            health = self._status.get_health_report()
            runtime = self._status.get_runtime_state()
            # Unknown components cannot become an all-green aggregate.
            overall = health.status.value
            if overall == "HEALTHY" and any(v.value == "UNKNOWN" for v in health.components.values()):
                overall = "UNKNOWN"
            components = tuple((key, value.value) for key, value in health.components.items())
            assistant_state = runtime.assistant_state.value
            checked_at = health.checked_at
        except Exception:  # noqa: BLE001 - public boundary redacts backend failures
            overall, components, assistant_state, checked_at = "UNAVAILABLE", (), "UNKNOWN", ""
        with self._state_lock:
            state, timestamp, checks = self._doctor_state, self._doctor_checked_at, self._checks
        return DiagnosticsSnapshot(
            overall, components, assistant_state, checked_at,
            state, timestamp, checks, self._telemetry(),
        )

    def _telemetry(self) -> TelemetrySummary:
        root = self._reports_dir
        if root is None:
            return TelemetrySummary()
        try:
            if root.is_symlink():
                return TelemetrySummary("UNAVAILABLE")
            if not root.exists():
                return TelemetrySummary()
            latest: tuple[int, Path] | None = None
            with os.scandir(root) as entries:
                for index, entry in enumerate(entries):
                    if index >= self._MAX_DIRECTORY_ENTRIES:
                        return TelemetrySummary("UNAVAILABLE")
                    match = re.fullmatch(r"session_(\d{1,12})\.json", entry.name)
                    if match and (latest is None or int(match[1]) > latest[0]):
                        latest = int(match[1]), Path(entry.path)
            if latest is None:
                return TelemetrySummary()
            path = latest[1]
            if path.is_symlink() or not path.is_file():
                return TelemetrySummary("UNAVAILABLE")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    return TelemetrySummary("UNAVAILABLE")
                raw = stream.read(self._MAX_REPORT_BYTES + 1)
            if len(raw) > self._MAX_REPORT_BYTES:
                return TelemetrySummary("UNAVAILABLE")
            report = json.loads(raw)
            if not isinstance(report, dict):
                return TelemetrySummary("UNAVAILABLE")
            # Legacy reports lack provenance, so their measurements cannot be promoted.
            if report.get("execution_mode") != "real":
                return TelemetrySummary("UNVERIFIED")
            ended = self._number(report.get("ended_at"))
            if ended is None:
                return TelemetrySummary("UNAVAILABLE")
            timestamp = datetime.fromtimestamp(ended, UTC).isoformat()
            rows = []
            for section, prefix, label in (
                ("speech", "stt_latency", "Transcripción STT"),
                ("ai", "latency", "Respuesta IA completa"),
                ("speech", "tts_latency", "Síntesis TTS"),
                ("speech", "ttfar", "Fin de voz a primer PCM enviado a reproducción"),
            ):
                values = report.get(section)
                if not isinstance(values, dict):
                    values = {}
                samples = values.get(f"{prefix}_samples", 0)
                count = samples if type(samples) is int and 0 < samples <= 1000000 else 0
                average = self._number(values.get(f"{prefix}_avg_ms")) if count else None
                p95 = self._number(values.get(f"{prefix}_p95_ms")) if count else None
                rows.append(LatencySummary(label, count, average, p95))
            return TelemetrySummary("RECORDED", timestamp, tuple(rows))
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            return TelemetrySummary("UNAVAILABLE")

    @staticmethod
    def _number(value: object) -> float | None:
        if type(value) not in (int, float):
            return None
        try:
            number = float(value)  # type: ignore[arg-type]
            return number if math.isfinite(number) and number >= 0 else None
        except OverflowError:
            return None

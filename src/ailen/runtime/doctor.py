"""Non-invasive system readiness diagnostic for AILEN Lab Mode."""

import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from ailen.ai.secrets import SecretResolver
from ailen.core.config import AILENConfig
from ailen.hardware.detector import HardwareDetector
from ailen.models.catalog import ModelCatalog
from ailen.models.planner import ModelPlanner
from ailen.models.store import ModelStore
from ailen.runtime.contracts import RuntimeStatus
from ailen.runtime.manager import LocalRuntimeManager


@dataclass
class DiagnosticCheck:
    name: str
    result: str  # "PASS", "WARN", "FAIL", "SKIP"
    detail: str


class LabDoctor:
    """Runs read-only system capability and dependency checks without modifying the host."""

    def __init__(self, config: AILENConfig | None = None) -> None:
        self.config = config

    def run_all_checks(self) -> list[DiagnosticCheck]:
        """Execute diagnostic checks across software, hardware, and assets."""
        checks: list[DiagnosticCheck] = []

        # 1. Python Environment Check. Importing this package already implies the
        # declared Python >= 3.11 requirement was satisfied.
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        checks.append(DiagnosticCheck(name="Python Environment", result="PASS", detail=f"Python {py_ver} ({sys.executable})"))

        # 2. Tkinter GUI Framework
        if importlib.util.find_spec("tkinter") is not None:
            checks.append(DiagnosticCheck(name="Tkinter GUI", result="PASS", detail="Tkinter library loaded successfully"))
        else:
            checks.append(DiagnosticCheck(name="Tkinter GUI", result="WARN", detail="python3-tk not installed; headless fallback will be used"))

        # 3. OpenCV Vision Library
        if importlib.util.find_spec("cv2") is not None:
            checks.append(DiagnosticCheck(name="OpenCV Vision", result="PASS", detail="cv2 module available"))
        else:
            checks.append(DiagnosticCheck(name="OpenCV Vision", result="WARN", detail="opencv-python not installed; vision disabled"))

        # 4. Hardware Inspection & Peripherals
        store = ModelStore()
        detector = HardwareDetector()
        report = detector.detect(str(store.base_dir))
        rec = detector.recommend_profile(report)

        cpu_desc = f"{report.cpu.model} | AVX2={report.cpu.has_avx2} FMA={report.cpu.has_fma}"
        checks.append(DiagnosticCheck(name="CPU Instruction Sets", result="PASS" if report.cpu.has_avx2 else "WARN", detail=cpu_desc))

        ram_desc = f"{report.ram.available_mb} MB free / {report.ram.total_mb} MB total"
        if report.ram.total_mb >= 4000:
            checks.append(DiagnosticCheck(name="System Memory", result="PASS", detail=ram_desc))
        elif report.ram.total_mb > 0:
            checks.append(DiagnosticCheck(name="System Memory", result="WARN", detail=f"Constrained RAM: {ram_desc}"))
        else:
            checks.append(DiagnosticCheck(name="System Memory", result="WARN", detail="RAM unmeasured/unknown"))

        # Audio I/O
        if len(report.audio_inputs) > 0 and len(report.audio_outputs) > 0:
            checks.append(DiagnosticCheck(name="Audio Devices", result="PASS", detail=f"{len(report.audio_inputs)} in / {len(report.audio_outputs)} out"))
        else:
            checks.append(DiagnosticCheck(name="Audio Devices", result="WARN", detail=f"{len(report.audio_inputs)} in / {len(report.audio_outputs)} out detected"))

        # Camera
        if len(report.cameras) > 0:
            checks.append(DiagnosticCheck(name="Camera Devices", result="PASS", detail=f"{len(report.cameras)} camera(s) detected"))
        else:
            checks.append(DiagnosticCheck(name="Camera Devices", result="WARN", detail="No physical cameras found"))

        # 5. Local AI Runtimes
        runtime_mgr = LocalRuntimeManager()
        runtimes = runtime_mgr.detect_available_runtimes()
        healthy_runtimes = [r for r in runtimes if r.health and r.health.status == RuntimeStatus.HEALTHY]

        if healthy_runtimes:
            rt = healthy_runtimes[0]
            checks.append(DiagnosticCheck(name="Local AI Runtime", result="PASS", detail=f"{rt.runtime_type.value} at {rt.endpoint} (HEALTHY)"))
        else:
            checks.append(DiagnosticCheck(name="Local AI Runtime", result="WARN", detail="No active runtime at 8080/11434; run llama-server or ollama"))

        # 6. Model Store and Recommended Model
        free_gb = round(shutil.disk_usage(store.base_dir if store.base_dir.exists() else Path.home()).free / (1024**3), 2)
        if free_gb >= 2.0:
            checks.append(DiagnosticCheck(name="Model Storage Disk", result="PASS", detail=f"{free_gb} GB free at {store.base_dir}"))
        else:
            checks.append(DiagnosticCheck(name="Model Storage Disk", result="WARN", detail=f"Low disk space: {free_gb} GB free at {store.base_dir}"))

        planner = ModelPlanner(catalog=ModelCatalog())
        plan = planner.plan(report, profile=rec.profile)
        if plan.is_viable and plan.selected_model_id:
            if store.exists(plan.selected_model_id):
                checks.append(DiagnosticCheck(name="Recommended Model", result="PASS", detail=f"{plan.selected_model_id} installed"))
            else:
                checks.append(DiagnosticCheck(
                    name="Recommended Model",
                    result="WARN",
                    detail=f"{plan.selected_model_id} not installed. Run: ailen models fetch {plan.selected_model_id}",
                ))
        else:
            checks.append(DiagnosticCheck(name="Recommended Model", result="SKIP", detail="Remote/Rule-only routing planned"))

        # 7. Cloud AI Configuration
        if self.config and self.config.ai.cloud.enabled:
            has_key = SecretResolver().resolve(
                env_var=self.config.ai.cloud.api_key_env,
                file_name=self.config.ai.cloud.api_key_file,
            ) is not None
            if has_key:
                checks.append(DiagnosticCheck(name="Cloud AI Config", result="PASS", detail="Cloud enabled with API key present"))
            else:
                checks.append(DiagnosticCheck(name="Cloud AI Config", result="WARN", detail="Cloud enabled but API key missing"))
        else:
            checks.append(DiagnosticCheck(name="Cloud AI Config", result="SKIP", detail="Cloud AI disabled in config"))

        return checks

    def print_report(self) -> int:
        """Run checks and print formatted diagnostic table."""
        checks = self.run_all_checks()
        print("==================================================================")
        print("                        AILEN LAB DOCTOR                          ")
        print("==================================================================")
        print(f"{'CHECK':<24} {'RESULT':<8} {'DETAIL'}")
        print("------------------------------------------------------------------")
        for c in checks:
            print(f"{c.name:<24} {c.result:<8} {c.detail}")
        print("==================================================================")

        fail_count = sum(1 for c in checks if c.result == "FAIL")
        warn_count = sum(1 for c in checks if c.result == "WARN")

        if fail_count > 0:
            print(f"DIAGNOSTIC SUMMARY: {fail_count} FAILED, {warn_count} WARNINGS. Lab cannot run properly.")
            return 1
        if warn_count > 0:
            print(f"DIAGNOSTIC SUMMARY: ALL PASS OR WARN ({warn_count} non-blocking warnings). Lab ready in degraded mode.")
            return 0
        print("DIAGNOSTIC SUMMARY: ALL CHECKS PASSED. Lab workstation fully ready.")
        return 0

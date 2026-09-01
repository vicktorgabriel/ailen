"""Non-invasive system readiness diagnostic for AILEN Lab Mode."""

import importlib.util
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ailen.ai.secrets import SecretResolver
from ailen.audio.piper_backend import piper_runtime_available
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
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LabDoctor:
    """Runs read-only system capability and dependency checks without modifying the host."""

    def __init__(self, config: AILENConfig | None = None) -> None:
        self.config = config

    def run_all_checks(self) -> list[DiagnosticCheck]:
        """Execute diagnostic checks across software, hardware, and assets."""
        checks: list[DiagnosticCheck] = []

        # 1. Python Environment Check
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        checks.append(DiagnosticCheck(name="Python Environment", result="PASS", detail=f"Python {py_ver} ({sys.executable})"))

        # 2. Tkinter GUI Framework
        if importlib.util.find_spec("tkinter") is not None:
            checks.append(DiagnosticCheck(name="Tkinter GUI", result="PASS", detail="Tkinter library loaded successfully"))
        else:
            checks.append(DiagnosticCheck(
                name="Tkinter GUI",
                result="WARN",
                detail="python3-tk not installed; headless fallback will be used",
                remediation="Install python3-tk or run with --headless",
            ))

        # 3. OpenCV Vision Library
        if importlib.util.find_spec("cv2") is not None:
            checks.append(DiagnosticCheck(name="OpenCV Vision", result="PASS", detail="cv2 module available"))
        else:
            checks.append(DiagnosticCheck(
                name="OpenCV Vision",
                result="WARN",
                detail="opencv-python not installed; vision disabled",
                remediation="pip install -e '.[vision]'",
            ))

        # 4. Hardware Inspection & Peripherals
        store = ModelStore()
        detector = HardwareDetector()
        report = detector.detect(str(store.base_dir))
        rec = detector.recommend_profile(report)

        cpu_desc = f"{report.cpu.model} | AVX2={report.cpu.has_avx2} FMA={report.cpu.has_fma}"
        checks.append(DiagnosticCheck(
            name="CPU Instruction Sets",
            result="PASS" if report.cpu.has_avx2 else "WARN",
            detail=cpu_desc,
            remediation="" if report.cpu.has_avx2 else "Models requiring AVX2 will be skipped",
        ))

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
            checks.append(DiagnosticCheck(
                name="Audio Devices",
                result="WARN",
                detail=f"{len(report.audio_inputs)} in / {len(report.audio_outputs)} out detected",
                remediation="Connect microphone/speakers or pass --no-audio",
            ))

        # Camera
        if len(report.cameras) > 0:
            checks.append(DiagnosticCheck(name="Camera Devices", result="PASS", detail=f"{len(report.cameras)} camera(s) detected"))
        else:
            checks.append(DiagnosticCheck(
                name="Camera Devices",
                result="WARN",
                detail="No physical cameras found",
                remediation="Connect USB camera or pass --no-camera",
            ))

        # 5. Speech Assets (STT / TTS)
        if self.config:
            # STT Check
            stt_engine = self.config.speech.stt_engine.lower()
            if stt_engine == "vosk":
                stt_path = self.config.speech.stt_model_path.strip()
                if stt_path and Path(stt_path).is_dir():
                    checks.append(DiagnosticCheck(name="STT Voice Model", result="PASS", detail=f"Vosk model at {stt_path}"))
                else:
                    checks.append(DiagnosticCheck(
                        name="STT Voice Model",
                        result="WARN",
                        detail=f"Vosk model path missing: '{stt_path or 'unconfigured'}'",
                        remediation="Set speech.stt_model_path in ailen.toml to valid Vosk model directory",
                    ))
            elif stt_engine == "mock":
                checks.append(DiagnosticCheck(name="STT Voice Model", result="SKIP", detail="STT set to mock"))
            else:
                checks.append(DiagnosticCheck(name="STT Voice Model", result="WARN", detail=f"STT engine '{stt_engine}'"))

            # TTS Check
            tts_engine = self.config.speech.tts_engine.lower()
            if tts_engine == "piper":
                tts_path = self.config.speech.tts_model_path.strip()
                piper_ok = piper_runtime_available()
                if piper_ok and tts_path and Path(tts_path).is_file():
                    checks.append(DiagnosticCheck(name="TTS Voice Model", result="PASS", detail=f"Piper ONNX model at {tts_path}"))
                else:
                    detail = f"Piper Python runtime={'OK' if piper_ok else 'MISSING'}, model={tts_path or 'unconfigured'}"
                    checks.append(DiagnosticCheck(
                        name="TTS Voice Model",
                        result="WARN",
                        detail=detail,
                        remediation="Install piper-tts and set speech.tts_model_path in ailen.toml",
                    ))
            elif tts_engine == "mock":
                checks.append(DiagnosticCheck(name="TTS Voice Model", result="SKIP", detail="TTS set to mock"))
            else:
                checks.append(DiagnosticCheck(name="TTS Voice Model", result="WARN", detail=f"TTS engine '{tts_engine}'"))

        # 6. Local AI Runtimes
        runtime_mgr = LocalRuntimeManager()
        runtimes = runtime_mgr.detect_available_runtimes()
        healthy_runtimes = [r for r in runtimes if r.health and r.health.status == RuntimeStatus.HEALTHY]

        if healthy_runtimes:
            rt = healthy_runtimes[0]
            checks.append(DiagnosticCheck(name="Local AI Runtime", result="PASS", detail=f"{rt.runtime_type.value} at {rt.endpoint} (HEALTHY)"))
        else:
            checks.append(DiagnosticCheck(
                name="Local AI Runtime",
                result="WARN",
                detail="No active runtime at 8080/11434",
                remediation="Start Ollama (ollama serve) or run llama-server",
            ))

        # 7. Model Store and Recommended Model
        free_gb = round(shutil.disk_usage(store.base_dir if store.base_dir.exists() else Path.home()).free / (1024**3), 2)
        if free_gb >= 2.0:
            checks.append(DiagnosticCheck(name="Model Storage Disk", result="PASS", detail=f"{free_gb} GB free at {store.base_dir}"))
        else:
            checks.append(DiagnosticCheck(
                name="Model Storage Disk",
                result="WARN",
                detail=f"Low disk space: {free_gb} GB free at {store.base_dir}",
                remediation="Free disk space in model storage path",
            ))

        planner = ModelPlanner(catalog=ModelCatalog())
        plan = planner.plan(report, profile=rec.profile)
        if plan.is_viable and plan.selected_model_id:
            if store.exists(plan.selected_model_id):
                checks.append(DiagnosticCheck(name="Recommended Model", result="PASS", detail=f"{plan.selected_model_id} installed"))
            else:
                checks.append(DiagnosticCheck(
                    name="Recommended Model",
                    result="WARN",
                    detail=f"{plan.selected_model_id} not installed",
                    remediation=f"Run: ailen models fetch {plan.selected_model_id}",
                ))
        else:
            checks.append(DiagnosticCheck(name="Recommended Model", result="SKIP", detail="Remote/Rule-only routing planned"))

        # 8. Named remote providers. Configuration/credential presence is not
        # health; an explicit inference test is required for READY.
        enabled_remotes = []
        if self.config and self.config.ai.allow_remote and self.config.ai.remote.enabled:
            resolver = SecretResolver()
            for provider_id, provider in self.config.ai.remote.providers.items():
                if not provider.enabled:
                    continue
                configured = bool(provider.endpoint and provider.model)
                has_key = provider.auth_mode == "none" or resolver.has_secret(
                    env_var=provider.api_key_env or None,
                    file_name=provider.api_key_file or None,
                )
                enabled_remotes.append(provider_id)
                checks.append(
                    DiagnosticCheck(
                        name=f"Remote AI Config ({provider_id})",
                        result="WARN" if configured and has_key else "FAIL",
                        detail=(
                            "Configured and credential present; health remains unverified"
                            if configured and has_key
                            else "Missing endpoint/model or provider-specific credential"
                        ),
                        remediation=(
                            "Run an explicit provider test from /ia"
                            if configured and has_key
                            else "Configure this provider in /ia and restart AILEN"
                        ),
                    )
                )
        if not enabled_remotes:
            checks.append(
                DiagnosticCheck(
                    name="Remote AI Providers",
                    result="SKIP",
                    detail="No named remote provider is enabled",
                )
            )

        return checks

    def print_report(self, as_json: bool = False) -> int:
        """Run checks and print formatted diagnostic table or JSON."""
        checks = self.run_all_checks()

        if as_json:
            print(json.dumps([c.to_dict() for c in checks], indent=2))
            fail_count = sum(1 for c in checks if c.result == "FAIL")
            return 1 if fail_count > 0 else 0

        print("==================================================================")
        print("                        AILEN LAB DOCTOR                          ")
        print("==================================================================")
        print(f"{'CHECK':<24} {'RESULT':<8} {'DETAIL'}")
        print("------------------------------------------------------------------")
        for c in checks:
            print(f"{c.name:<24} {c.result:<8} {c.detail}")
            if c.remediation:
                print(f"  -> Remediation: {c.remediation}")
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

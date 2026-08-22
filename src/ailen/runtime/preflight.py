"""Live Lab Preflight checker verifying all physical hardware, assets, and runtimes."""

import importlib.util
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ailen.audio.alsa_backend import AlsaDeviceEnumerator
from ailen.audio.piper_backend import resolve_piper_executable
from ailen.core.config import AILENConfig
from ailen.hardware.detector import HardwareDetector
from ailen.models.catalog import ModelCatalog
from ailen.models.store import ModelStore
from ailen.runtime.inventory import RuntimeModelInventory
from ailen.runtime.manager import LocalRuntimeManager
from ailen.speech.catalog import SpeechAssetCatalog
from ailen.speech.store import SpeechAssetStore

logger = logging.getLogger(__name__)


@dataclass
class PreflightCheckItem:
    """Single preflight evaluation item."""
    name: str
    is_required: bool
    status: str  # "PASS", "WARN", "FAIL", "SKIP"
    detail: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreflightReport:
    """Complete preflight evaluation summary."""
    overall_status: str  # "READY_FOR_LIVE_TEST" or "NOT_READY_FOR_LIVE_TEST"
    checks: list[PreflightCheckItem] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "checks": [c.to_dict() for c in self.checks],
            "missing_required": self.missing_required,
            "missing_optional": self.missing_optional,
        }


class LabPreflightChecker:
    """Assesses host readiness for an interactive live physical laboratory test."""

    def __init__(
        self,
        config: AILENConfig | None = None,
        speech_store: SpeechAssetStore | None = None,
        model_store: ModelStore | None = None,
    ) -> None:
        self.config = config or AILENConfig()
        self.speech_store = speech_store or SpeechAssetStore()
        self.model_store = model_store or ModelStore()
        self.speech_catalog = SpeechAssetCatalog()
        self.model_catalog = ModelCatalog()
        self.runtime_manager = LocalRuntimeManager()
        self.inventory = RuntimeModelInventory()

    def run_all(self, headless: bool = False, no_camera: bool = False, no_audio: bool = False, no_ai: bool = False) -> PreflightReport:
        """Execute full suite of preflight readiness checks."""
        checks: list[PreflightCheckItem] = []

        # 1. Face GUI
        if headless:
            checks.append(PreflightCheckItem(
                name="Face GUI",
                is_required=False,
                status="SKIP",
                detail="Headless mode active (GUI skipped)",
            ))
        else:
            try:
                import tkinter  # noqa: F401
                checks.append(PreflightCheckItem(
                    name="Face GUI",
                    is_required=True,
                    status="PASS",
                    detail="Tkinter available",
                ))
            except ImportError:
                checks.append(PreflightCheckItem(
                    name="Face GUI",
                    is_required=True,
                    status="FAIL",
                    detail="python3-tk missing; GUI face cannot render",
                    remediation="Run: sudo apt install python3-tk (or pass --headless)",
                ))

        # 2. Vision & Camera
        if no_camera:
            checks.append(PreflightCheckItem(
                name="Vision & Camera",
                is_required=False,
                status="SKIP",
                detail="Camera disabled via flag",
            ))
        else:
            has_cv2 = importlib.util.find_spec("cv2") is not None
            detector = HardwareDetector()
            hw_rep = detector.detect()
            has_camera = len(hw_rep.cameras) > 0

            if not has_cv2:
                checks.append(PreflightCheckItem(
                    name="Vision Library",
                    is_required=True,
                    status="FAIL",
                    detail="opencv-python not installed in .venv",
                    remediation="Run: ./.venv/bin/pip install -e '.[vision]'",
                ))
            elif not has_camera:
                checks.append(PreflightCheckItem(
                    name="Camera Hardware",
                    is_required=True,
                    status="FAIL",
                    detail="No physical V4L2 cameras detected",
                    remediation="Connect USB webcam or pass --no-camera",
                ))
            else:
                checks.append(PreflightCheckItem(
                    name="Vision & Camera",
                    is_required=True,
                    status="PASS",
                    detail=f"OpenCV loaded, {len(hw_rep.cameras)} camera(s) detected",
                ))

        # 3. Audio Devices (Input & Output)
        if no_audio:
            checks.append(PreflightCheckItem(
                name="Audio I/O",
                is_required=False,
                status="SKIP",
                detail="Audio disabled via flag",
            ))
        else:
            enumerator = AlsaDeviceEnumerator()
            capture_hw = enumerator.list_hardware_devices(is_input=True)
            playback_hw = enumerator.list_hardware_devices(is_input=False)

            if not capture_hw:
                checks.append(PreflightCheckItem(
                    name="Audio Input",
                    is_required=True,
                    status="FAIL",
                    detail="No physical ALSA capture hardware endpoints reported by `arecord -l`",
                    remediation="Connect/configure a microphone or capture device, then retry",
                ))
            else:
                ids = ", ".join(d.id for d in capture_hw[:4])
                checks.append(PreflightCheckItem(
                    name="Audio Input",
                    is_required=True,
                    status="PASS",
                    detail=(
                        f"{len(capture_hw)} capture hardware endpoint(s): {ids}. "
                        "Signal presence still requires a VAD/STT test."
                    ),
                ))

            if not playback_hw:
                checks.append(PreflightCheckItem(
                    name="Audio Output",
                    is_required=True,
                    status="FAIL",
                    detail="No physical ALSA playback hardware endpoints reported by `aplay -l`",
                    remediation="Connect/configure speakers/headphones or playback hardware",
                ))
            else:
                checks.append(PreflightCheckItem(
                    name="Audio Output",
                    is_required=True,
                    status="PASS",
                    detail=(
                        f"{len(playback_hw)} playback hardware endpoint(s) available. "
                        "Audible output still requires an explicit playback test."
                    ),
                ))

        # 4. STT Engine & Model
        if no_audio:
            checks.append(PreflightCheckItem(name="STT", is_required=False, status="SKIP", detail="Audio disabled"))
        else:
            stt_engine = self.config.speech.stt_engine.lower()
            if stt_engine == "mock":
                checks.append(PreflightCheckItem(
                    name="STT Engine",
                    is_required=True,
                    status="FAIL",
                    detail="STT engine is set to 'mock'; real STT required for live physical test",
                    remediation="Run: ailen lab prepare-speech --yes and update config to vosk or whisper_cpp",
                ))
            elif stt_engine == "vosk":
                has_vosk_pkg = importlib.util.find_spec("vosk") is not None
                model_path_str = self.config.speech.stt_model_path.strip()
                has_model = bool(model_path_str and Path(model_path_str).is_dir())
                if not has_vosk_pkg:
                    checks.append(PreflightCheckItem(
                        name="STT Engine (Vosk)",
                        is_required=True,
                        status="FAIL",
                        detail="vosk package not installed in .venv",
                        remediation="Run: ./.venv/bin/pip install -e '.[stt-vosk]'",
                    ))
                elif not has_model:
                    checks.append(PreflightCheckItem(
                        name="STT Model (Vosk)",
                        is_required=True,
                        status="FAIL",
                        detail=f"Vosk model directory not found: '{model_path_str}'",
                        remediation="Run: ailen lab prepare-speech --yes",
                    ))
                else:
                    checks.append(PreflightCheckItem(
                        name="STT Engine & Model",
                        is_required=True,
                        status="PASS",
                        detail=f"Vosk loaded with model '{model_path_str}'",
                    ))
            elif stt_engine == "whisper_cpp":
                has_bin = bool(shutil.which("whisper-cli") or shutil.which("main"))
                model_path_str = self.config.speech.stt_model_path.strip()
                has_model = bool(model_path_str and Path(model_path_str).is_file())
                if not has_bin:
                    checks.append(PreflightCheckItem(
                        name="STT Engine (whisper.cpp)",
                        is_required=True,
                        status="FAIL",
                        detail="whisper-cli binary not found in PATH",
                        remediation="Install whisper-cli binary in PATH",
                    ))
                elif not has_model:
                    checks.append(PreflightCheckItem(
                        name="STT Model (whisper.cpp)",
                        is_required=True,
                        status="FAIL",
                        detail=f"Whisper model file not found: '{model_path_str}'",
                        remediation="Run: ailen speech fetch whisper-ggml-tiny -y",
                    ))
                else:
                    checks.append(PreflightCheckItem(
                        name="STT Engine & Model",
                        is_required=True,
                        status="PASS",
                        detail=f"whisper.cpp model '{model_path_str}' loaded",
                    ))

        # 5. TTS Engine, Binary & Voice Model
        if no_audio:
            checks.append(PreflightCheckItem(name="TTS", is_required=False, status="SKIP", detail="Audio disabled"))
        else:
            tts_engine = self.config.speech.tts_engine.lower()
            if tts_engine == "mock":
                checks.append(PreflightCheckItem(
                    name="TTS Engine",
                    is_required=True,
                    status="FAIL",
                    detail="TTS engine is set to 'mock'; real Piper TTS required for live physical test",
                    remediation="Run: ailen lab prepare-speech --yes and set speech.tts_engine = 'piper'",
                ))
            elif tts_engine == "piper":
                has_piper = bool(resolve_piper_executable("piper"))
                model_path_str = self.config.speech.tts_model_path.strip()
                has_model = bool(model_path_str and Path(model_path_str).is_file())
                if not has_piper:
                    checks.append(PreflightCheckItem(
                        name="TTS Binary (Piper)",
                        is_required=True,
                        status="FAIL",
                        detail="piper executable not found in PATH",
                        remediation="Install Piper binary in PATH (e.g. ~/.local/bin/piper)",
                    ))
                elif not has_model:
                    checks.append(PreflightCheckItem(
                        name="TTS Voice Model",
                        is_required=True,
                        status="FAIL",
                        detail=f"Piper voice model not found: '{model_path_str}'",
                        remediation="Run: ailen lab prepare-speech --yes",
                    ))
                else:
                    checks.append(PreflightCheckItem(
                        name="TTS Engine & Voice",
                        is_required=True,
                        status="PASS",
                        detail=f"Piper voice '{model_path_str}' loaded",
                    ))

        # 6. Local AI Runtime & Model
        if no_ai:
            checks.append(PreflightCheckItem(name="Local AI", is_required=False, status="SKIP", detail="AI disabled via flag"))
        else:
            endpoint = self.config.ai.local.endpoint
            health = self.runtime_manager.check_health(endpoint)
            is_runtime_healthy = health.status.value == "HEALTHY"

            if not is_runtime_healthy:
                checks.append(PreflightCheckItem(
                    name="Local AI Runtime",
                    is_required=True,
                    status="FAIL",
                    detail=f"Local LLM runtime not responding at {endpoint} ({health.details})",
                    remediation="Start Ollama or run: ailen lab prepare-ai --start-runtime",
                ))
            else:
                checks.append(PreflightCheckItem(
                    name="Local AI Runtime",
                    is_required=True,
                    status="PASS",
                    detail=f"Runtime active at {endpoint} ({health.details})",
                ))

        # Summarize
        missing_req = [c.name for c in checks if c.is_required and c.status == "FAIL"]
        missing_opt = [c.name for c in checks if not c.is_required and c.status in ("WARN", "FAIL")]
        overall = "READY_FOR_LIVE_TEST" if not missing_req else "NOT_READY_FOR_LIVE_TEST"

        return PreflightReport(
            overall_status=overall,
            checks=checks,
            missing_required=missing_req,
            missing_optional=missing_opt,
        )

    def print_report(self, headless: bool = False, no_camera: bool = False, no_audio: bool = False, no_ai: bool = False) -> int:
        """Print formatted CLI preflight report."""
        report = self.run_all(headless=headless, no_camera=no_camera, no_audio=no_audio, no_ai=no_ai)

        print("\n============================================================")
        print("AILEN — LIVE LAB PREFLIGHT READINESS CHECK")
        print("============================================================\n")

        for item in report.checks:
            req_badge = "[REQ]" if item.is_required else "[OPT]"
            status_badge = f"[{item.status}]"
            print(f"{status_badge:<8} {req_badge} {item.name:<24} {item.detail}")
            if item.remediation and item.status in ("FAIL", "WARN"):
                print(f"         -> Remediation: {item.remediation}")

        print("\n------------------------------------------------------------")
        print(f"PREFLIGHT RESULT: {report.overall_status}")
        print("------------------------------------------------------------")

        if report.overall_status == "READY_FOR_LIVE_TEST":
            print("\n[OK] All physical components and assets are ready. You may proceed with 'ailen lab start'.")
            return 0

        print(f"\n[!] System is NOT ready for live physical test. Missing required items: {', '.join(report.missing_required)}")
        return 1

"""Live Lab Preflight checker verifying all physical hardware, assets, and runtimes."""

import importlib.util
import logging
import os
import shutil
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ailen.audio.alsa_backend import AlsaDeviceEnumerator
from ailen.audio.piper_backend import piper_runtime_available
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
            source_mode = self.config.vision.camera_source.strip().lower()
            network_camera_ready = False
            network_camera_detail = ""
            check_network_camera = (
                self.config.vision.network_camera_enabled
                and source_mode in {"auto", "rtsp"}
            )
            if check_network_camera:
                host = self.config.vision.network_camera_host.strip()
                port = self.config.vision.network_camera_port
                username = self.config.vision.network_camera_username.strip()
                password_env = self.config.vision.network_camera_password_env.strip()
                secret_ready = not username or bool(password_env and os.environ.get(password_env))
                reachable = False
                if host and 1 <= port <= 65535:
                    try:
                        with socket.create_connection((host, port), timeout=0.75):
                            reachable = True
                    except OSError:
                        reachable = False
                network_camera_ready = bool(host and reachable and secret_ready)
                if network_camera_ready:
                    network_camera_detail = f"RTSP camera {host}:{port} reachable; credentials available"
                elif not host:
                    network_camera_detail = "RTSP camera host not configured"
                elif not secret_ready:
                    network_camera_detail = f"RTSP credential env '{password_env}' is not set"
                else:
                    network_camera_detail = f"RTSP camera {host}:{port} is not reachable"

            vision_api_ready = False
            vision_api_detail = "opencv-python not installed in .venv"
            if has_cv2:
                try:
                    import cv2  # type: ignore[import-not-found]

                    selected_detector = self.config.vision.detector
                    if selected_detector == "yunet":
                        model_path = Path(self.config.vision.detector_model_path).expanduser()
                        has_api = hasattr(cv2, "FaceDetectorYN")
                        has_model = model_path.is_file()
                        score = float(self.config.vision.detector_score_threshold)
                        score_valid = 0.0 < score <= 1.0
                        # A real PASS requires actually constructing the detector
                        # (validates ONNX integrity), not just the file existing.
                        loaded = False
                        if has_api and has_model and score_valid:
                            probe = cv2.FaceDetectorYN.create(
                                str(model_path),
                                "",
                                (320, 320),
                                score,
                                0.3,
                                5000,
                            )
                            loaded = probe is not None
                        vision_api_ready = loaded
                        if vision_api_ready:
                            vision_api_detail = (
                                f"OpenCV {getattr(cv2, '__version__', 'unknown')} YuNet ready "
                                f"with model '{model_path}' (score={score})"
                            )
                        else:
                            vision_api_detail = (
                                f"OpenCV {getattr(cv2, '__version__', 'unknown')} YuNet unavailable "
                                f"(FaceDetectorYN={has_api}, model={has_model}, score_valid={score_valid}, loaded={loaded})"
                            )
                    else:
                        cascade_dir = getattr(getattr(cv2, "data", None), "haarcascades", "")
                        cascade_path = (
                            Path(cascade_dir) / "haarcascade_frontalface_default.xml"
                            if cascade_dir else None
                        )
                        has_classifier = hasattr(cv2, "CascadeClassifier")
                        has_cascade_asset = bool(cascade_path and cascade_path.is_file())
                        loadable = False
                        if has_classifier and has_cascade_asset:
                            cascade_obj = cv2.CascadeClassifier(str(cascade_path))
                            loadable = not cascade_obj.empty()
                        vision_api_ready = loadable
                        if vision_api_ready:
                            vision_api_detail = (
                                f"OpenCV {getattr(cv2, '__version__', 'unknown')} Haar ready "
                                "(experimental detector)"
                            )
                        else:
                            vision_api_detail = (
                                f"OpenCV {getattr(cv2, '__version__', 'unknown')} lacks required Haar support "
                                f"(CascadeClassifier={has_classifier}, cascade_asset={has_cascade_asset}, loadable={loadable})"
                            )
                except Exception as exc:  # noqa: BLE001
                    vision_api_detail = f"OpenCV vision readiness failed: {exc}"

            if not has_cv2 or not vision_api_ready:
                checks.append(PreflightCheckItem(
                    name="Vision Library",
                    is_required=True,
                    status="FAIL",
                    detail=vision_api_detail,
                    remediation="Install the configured detector/model or run with --no-camera",
                ))
            else:
                if source_mode == "usb":
                    source_ready = has_camera
                    failure_detail = "USB/V4L2 camera selected but no physical camera was detected"
                    remediation = "Connect USB webcam or select vision.camera_source=auto/rtsp"
                elif source_mode == "rtsp":
                    source_ready = network_camera_ready
                    failure_detail = network_camera_detail or "RTSP camera selected but unavailable"
                    remediation = (
                        f"Set {self.config.vision.network_camera_password_env} and verify RTSP reachability"
                        if self.config.vision.network_camera_enabled
                        else "Enable network camera configuration or select vision.camera_source=usb/auto"
                    )
                else:
                    source_ready = has_camera or network_camera_ready
                    failure_detail = network_camera_detail or "No physical V4L2 or ready RTSP camera detected"
                    remediation = "Connect USB webcam, configure RTSP, or pass --no-camera"

                if not source_ready:
                    checks.append(PreflightCheckItem(
                        name="Camera Hardware",
                        is_required=True,
                        status="FAIL",
                        detail=failure_detail,
                        remediation=remediation,
                    ))
                else:
                    sources = []
                    if source_mode in {"auto", "usb"} and has_camera:
                        sources.append(f"{len(hw_rep.cameras)} V4L2 camera(s)")
                    if source_mode in {"auto", "rtsp"} and network_camera_ready:
                        sources.append(network_camera_detail)
                    checks.append(PreflightCheckItem(
                        name="Vision & Camera",
                        is_required=True,
                        status="PASS",
                        detail=f"{vision_api_detail}; source={source_mode}; " + "; ".join(sources),
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
                has_piper = piper_runtime_available()
                model_path_str = self.config.speech.tts_model_path.strip()
                has_model = bool(model_path_str and Path(model_path_str).is_file())
                if not has_piper:
                    checks.append(PreflightCheckItem(
                        name="TTS Runtime (Piper)",
                        is_required=True,
                        status="FAIL",
                        detail="piper-tts Python package is not installed",
                        remediation="Install the project speech dependency that provides piper-tts",
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

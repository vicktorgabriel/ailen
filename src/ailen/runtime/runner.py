"""Dedicated non-invasive runner for AILEN Lab Mode."""

import datetime
import importlib.util
import logging
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from ailen.audio.contracts import AudioInputBackend, AudioOutputBackend
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.core.config import AILENConfig
from ailen.core.conversation import ConversationCoordinator
from ailen.face.animator import FaceAnimator
from ailen.face.contracts import FaceController
from ailen.face.gui import TkinterFaceController
from ailen.face.null import NullFaceController
from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.hardware.detector import HardwareDetector
from ailen.models.catalog import ModelCatalog
from ailen.models.planner import ModelPlan, ModelPlanner
from ailen.models.store import ModelStore
from ailen.runtime.contracts import RuntimeStatus
from ailen.runtime.manager import LocalRuntimeManager
from ailen.vision.contracts import VisionBackend

logger = logging.getLogger(__name__)


@dataclass
class ComponentStatus:
    name: str
    backend: str
    state: str  # "READY", "RUNNING", "DISABLED", "MISSING_MODEL", "DEGRADED", "UNAVAILABLE"
    detail: str = ""


class LabRunner:
    """Orchestrates non-invasive Lab Mode runtime for development workstations."""

    def __init__(
        self,
        config: AILENConfig,
        dry_run: bool = False,
        headless: bool = False,
        no_camera: bool = False,
        no_audio: bool = False,
        no_ai: bool = False,
        duration: float | None = None,
        log_dir: Path | str | None = None,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.headless = headless
        self.no_camera = no_camera
        self.no_audio = no_audio
        self.no_ai = no_ai
        self.duration = duration

        self.log_dir = Path(log_dir) if log_dir else Path("runtime/lab")
        self._is_running = False
        self._shutdown_requested = False

        # Component instances
        self.face_controller: FaceController | None = None
        self.face_animator: FaceAnimator | None = None
        self.vision_backend: VisionBackend | None = None
        self.audio_coordinator: AudioInteractionCoordinator | None = None
        self.conversation_coordinator: ConversationCoordinator | None = None

        self.hardware_report: HardwareCapabilityReport | None = None
        self.model_plan: ModelPlan | None = None
        self.component_statuses: list[ComponentStatus] = []

    def inspect_and_plan(self) -> tuple[HardwareCapabilityReport, ModelPlan]:
        """Detect hardware and calculate optimal model plan."""
        store = ModelStore()
        detector = HardwareDetector()
        self.hardware_report = detector.detect(str(store.base_dir))
        rec = detector.recommend_profile(self.hardware_report)

        planner = ModelPlanner(catalog=ModelCatalog())
        self.model_plan = planner.plan(self.hardware_report, profile=rec.profile)
        return self.hardware_report, self.model_plan

    def init_components(self) -> list[ComponentStatus]:
        """Initialize lab components and collect readiness status."""
        self.component_statuses.clear()

        # 1. Face Component
        if self.headless or not self.config.display.enabled:
            self.face_controller = NullFaceController()
            self.component_statuses.append(
                ComponentStatus(name="Face", backend="NullFaceController", state="READY", detail="Headless mode active")
            )
        else:
            if importlib.util.find_spec("tkinter") is not None:
                try:
                    self.face_animator = FaceAnimator()
                    self.face_controller = TkinterFaceController(animator=self.face_animator)
                    self.component_statuses.append(
                        ComponentStatus(name="Face", backend="Tkinter", state="READY", detail="GUI window enabled")
                    )
                except Exception as e:  # noqa: BLE001
                    self.face_controller = NullFaceController()
                    self.component_statuses.append(
                        ComponentStatus(
                            name="Face",
                            backend="NullFaceController",
                            state="DEGRADED",
                            detail=f"Tkinter window error ({e}), using headless",
                        )
                    )
            else:
                self.face_controller = NullFaceController()
                self.component_statuses.append(
                    ComponentStatus(
                        name="Face",
                        backend="NullFaceController",
                        state="DEGRADED",
                        detail="Tkinter unavailable, using headless",
                    )
                )

        # 2. Vision Component
        if self.no_camera or not self.config.vision.enabled:
            self.component_statuses.append(
                ComponentStatus(name="Vision", backend="None", state="DISABLED", detail="Disabled by flag/config")
            )
        else:
            if importlib.util.find_spec("cv2") is not None:
                from ailen.vision.opencv_backend import OpenCvVisionBackend

                if self.hardware_report and len(self.hardware_report.cameras) > 0:
                    self.vision_backend = OpenCvVisionBackend(
                        camera_device=self.config.vision.camera_device,
                        fps=self.config.vision.fps,
                    )
                    self.component_statuses.append(
                        ComponentStatus(
                            name="Vision",
                            backend="OpenCV",
                            state="READY",
                            detail=f"Device {self.config.vision.camera_device} active",
                        )
                    )
                else:
                    self.component_statuses.append(
                        ComponentStatus(
                            name="Vision",
                            backend="OpenCV",
                            state="DISABLED",
                            detail="No physical cameras detected",
                        )
                    )
            else:
                self.component_statuses.append(
                    ComponentStatus(
                        name="Vision",
                        backend="OpenCV",
                        state="UNAVAILABLE",
                        detail="opencv-python not installed",
                    )
                )

        # 3. Audio / STT / TTS Component
        if self.no_audio:
            self.component_statuses.append(
                ComponentStatus(name="Audio", backend="None", state="DISABLED", detail="Disabled by flag")
            )
            self.component_statuses.append(
                ComponentStatus(name="STT", backend="None", state="DISABLED", detail="Audio disabled")
            )
            self.component_statuses.append(
                ComponentStatus(name="TTS", backend="None", state="DISABLED", detail="Audio disabled")
            )
        else:
            if sys.platform.startswith("linux"):
                try:
                    from ailen.audio.alsa_backend import (
                        AlsaAudioInputBackend,
                        AlsaAudioOutputBackend,
                    )

                    in_backend: AudioInputBackend = AlsaAudioInputBackend()
                    out_backend: AudioOutputBackend = AlsaAudioOutputBackend()
                    self.audio_coordinator = AudioInteractionCoordinator(
                        audio_input=in_backend,
                        audio_output=out_backend,
                    )
                    self.component_statuses.append(
                        ComponentStatus(name="Audio", backend="ALSA", state="READY", detail="Microphone & Speakers active")
                    )
                except Exception as e:  # noqa: BLE001
                    self.component_statuses.append(
                        ComponentStatus(name="Audio", backend="ALSA", state="UNAVAILABLE", detail=str(e))
                    )
            else:
                self.component_statuses.append(
                    ComponentStatus(
                        name="Audio",
                        backend="ALSA",
                        state="UNAVAILABLE",
                        detail="Native audio backend not implemented on this OS yet",
                    )
                )

            # STT Check
            stt_model_path = Path("models/stt/vosk")
            if stt_model_path.is_dir():
                self.component_statuses.append(
                    ComponentStatus(name="STT", backend="Vosk", state="READY", detail=str(stt_model_path))
                )
            else:
                self.component_statuses.append(
                    ComponentStatus(name="STT", backend="Vosk", state="MISSING_MODEL", detail="Model directory missing")
                )

            # TTS Check
            tts_model_path = Path("models/tts/piper.onnx")
            if tts_model_path.is_file():
                self.component_statuses.append(
                    ComponentStatus(name="TTS", backend="Piper", state="READY", detail=str(tts_model_path))
                )
            else:
                self.component_statuses.append(
                    ComponentStatus(name="TTS", backend="Piper", state="MISSING_MODEL", detail="ONNX voice model missing")
                )

        # 4. Local AI & Runtimes
        if self.no_ai:
            self.component_statuses.append(
                ComponentStatus(name="AI Inference", backend="None", state="DISABLED", detail="Disabled by flag")
            )
        else:
            runtime_mgr = LocalRuntimeManager()
            runtimes = runtime_mgr.detect_available_runtimes()

            healthy_runtimes = [r for r in runtimes if r.health and r.health.status == RuntimeStatus.HEALTHY]
            store = ModelStore()

            if self.model_plan and self.model_plan.is_viable and self.model_plan.selected_model_id:
                installed = store.exists(self.model_plan.selected_model_id)
                detail = f"Model: {self.model_plan.selected_model_id} (Installed={installed})"
                if healthy_runtimes and installed:
                    self.component_statuses.append(
                        ComponentStatus(
                            name="Local AI",
                            backend=healthy_runtimes[0].runtime_type.value,
                            state="READY",
                            detail=detail,
                        )
                    )
                elif healthy_runtimes and not installed:
                    self.component_statuses.append(
                        ComponentStatus(
                            name="Local AI",
                            backend=healthy_runtimes[0].runtime_type.value,
                            state="MISSING_MODEL",
                            detail=f"Runtime active but model missing. Run: ailen models fetch {self.model_plan.selected_model_id}",
                        )
                    )
                else:
                    self.component_statuses.append(
                        ComponentStatus(
                            name="Local AI",
                            backend="llama-server/ollama",
                            state="NOT_RUNNING",
                            detail="No local runtime server reachable on port 8080/11434",
                        )
                    )
            else:
                self.component_statuses.append(
                    ComponentStatus(
                        name="Local AI",
                        backend="Rule-based/Remote",
                        state="READY",
                        detail="Fallback routing active",
                    )
                )

        return self.component_statuses

    def print_status_table(self) -> None:
        """Render standard lab component status table."""
        print("==================================================================")
        print("                    AILEN LAB COMPONENT STATUS                    ")
        print("==================================================================")
        print(f"{'COMPONENT':<14} {'BACKEND':<18} {'STATE':<14} {'DETAIL'}")
        print("------------------------------------------------------------------")
        for s in self.component_statuses:
            print(f"{s.name:<14} {s.backend:<18} {s.state:<14} {s.detail}")
        print("==================================================================")

        active_statuses = [s for s in self.component_statuses if s.state != "DISABLED"]
        degraded = any(s.state != "READY" for s in active_statuses)
        if active_statuses and not degraded:
            print("STATUS: AILEN LAB READY (All enabled components are ready)")
        else:
            print("STATUS: AILEN LAB DEGRADED (One or more enabled components need attention)")
        print("==================================================================")

    def _setup_signal_handlers(self) -> None:
        """Register graceful shutdown handlers for SIGINT and SIGTERM."""
        def handler(sig: int, frame: FrameType | None) -> None:
            logger.info("Shutdown signal %s received. Stopping lab runner...", sig)
            self._shutdown_requested = True
            self.stop()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def start(self) -> int:
        """Start the lab session, run event loop, and cleanly terminate upon completion."""
        self.inspect_and_plan()
        self.init_components()
        self.print_status_table()

        if self.dry_run:
            print("Dry-run complete: all components initialized without entering loop.")
            return 0

        # Setup logging session
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            session_file = self.log_dir / f"session_{int(time.time())}.log"
            session_file.write_text(
                f"AILEN Lab Session Started: {datetime.datetime.now(datetime.UTC).isoformat()}\n",
                encoding="utf-8",
            )
        except OSError:
            pass

        self._setup_signal_handlers()
        self._is_running = True
        start_time = time.time()

        print("AILEN Lab Mode running. Press Ctrl+C to terminate cleanly.")

        # Start Vision capture if present
        if self.vision_backend:
            try:
                self.vision_backend.start()
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not start vision backend: %s", e)

        # Start Audio recording if present
        if self.audio_coordinator:
            try:
                self.audio_coordinator.start()
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not start audio coordinator: %s", e)

        try:
            while self._is_running and not self._shutdown_requested:
                if self.duration and (time.time() - start_time) >= self.duration:
                    logger.info("Duration limit reached (%s s). Stopping...", self.duration)
                    break

                # Tick face animation
                if self.face_controller and hasattr(self.face_controller, "update"):
                    try:
                        self.face_controller.update()
                    except Exception:  # noqa: BLE001, S110
                        pass

                time.sleep(0.016)  # ~60 FPS loop
        except KeyboardInterrupt:
            print("\nCtrl+C detected.")
        finally:
            self.stop()

        print("AILEN Lab shutdown cleanly completed.")
        return 0

    def stop(self) -> None:
        """Stop all managed components safely."""
        self._is_running = False

        if self.vision_backend:
            try:
                self.vision_backend.stop()
            except Exception as e:  # noqa: BLE001
                logger.warning("Error stopping vision backend: %s", e)
            self.vision_backend = None

        if self.audio_coordinator:
            try:
                self.audio_coordinator.stop()
            except Exception as e:  # noqa: BLE001
                logger.warning("Error stopping audio coordinator: %s", e)
            self.audio_coordinator = None

        if self.face_controller:
            try:
                if hasattr(self.face_controller, "close"):
                    self.face_controller.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("Error closing face controller: %s", e)
            self.face_controller = None

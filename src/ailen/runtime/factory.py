"""Dedicated component factory resolving real vs simulated backends for Lab Mode."""

import importlib.util
import logging
import shutil
import sys
from pathlib import Path

from ailen.ai.cloud_backend import CloudAiBackend
from ailen.ai.contracts import AiBackend
from ailen.ai.fake import FakeAiBackend
from ailen.ai.http_backend import GenericOpenAiBackend
from ailen.ai.lan_backend import LanBrainAiBackend
from ailen.ai.ollama_backend import OllamaNativeBackend
from ailen.ai.residency import ModelResidencyPolicy
from ailen.ai.secrets import SecretResolver
from ailen.audio.alsa_backend import (
    AlsaAudioInputBackend,
    AlsaAudioOutputBackend,
    AlsaDeviceEnumerator,
)
from ailen.audio.contracts import (
    AudioInputBackend,
    AudioOutputBackend,
    SttBackend,
    TtsBackend,
)
from ailen.audio.fake import (
    FakeAudioInputBackend,
    FakeAudioOutputBackend,
    FakeSttBackend,
    FakeTtsBackend,
)
from ailen.audio.piper_backend import PiperTtsBackend, resolve_piper_executable
from ailen.audio.vosk_backend import VoskSttBackend
from ailen.audio.whisper_backend import WhisperCppSttBackend
from ailen.core.config import AILENConfig
from ailen.domain.enums import InferenceProfile, ServiceStatus
from ailen.face.animator import FaceAnimator
from ailen.face.contracts import FaceController
from ailen.face.gui import TkinterFaceController
from ailen.face.null import NullFaceController
from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.models.planner import ModelPlan
from ailen.runtime.contracts import ExternalRuntimeDescriptor, RuntimeStatus, RuntimeType
from ailen.runtime.inventory import RuntimeModelInventory
from ailen.vision.contracts import VisionBackend
from ailen.vision.fake import FakeVisionBackend

logger = logging.getLogger(__name__)


class ComponentStatus:
    """Readiness status metadata for a subsystem component."""

    def __init__(
        self,
        name: str,
        backend: str,
        state: str,  # "READY", "SIMULATED", "MISSING_MODEL", "DEGRADED", "UNAVAILABLE", "DISABLED"
        detail: str = "",
        remediation: str = "",
    ) -> None:
        self.name = name
        self.backend = backend
        self.state = state
        self.detail = detail
        self.remediation = remediation

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "backend": self.backend,
            "state": self.state,
            "detail": self.detail,
            "remediation": self.remediation,
        }


class LabComponentFactory:
    """Instantiates and configures Lab Mode components with strict separation between real and simulated modes."""

    def __init__(
        self,
        config: AILENConfig,
        hardware_report: HardwareCapabilityReport | None = None,
    ) -> None:
        self.config = config
        self.hardware_report = hardware_report

    # -------------------------------------------------------------------------
    # Face Component
    # -------------------------------------------------------------------------
    def build_face(
        self,
        headless: bool = False,
        simulate: bool = False,
        fullscreen: bool = False,
    ) -> tuple[FaceController, ComponentStatus]:
        """Build visual Face controller."""
        if simulate:
            animator = FaceAnimator()
            return NullFaceController(animator=animator), ComponentStatus(
                name="Face",
                backend="NullFaceController (Simulated)",
                state="SIMULATED",
                detail="Simulated test face controller",
            )

        if headless or not self.config.display.enabled:
            animator = FaceAnimator()
            return NullFaceController(animator=animator), ComponentStatus(
                name="Face",
                backend="NullFaceController",
                state="READY",
                detail="Headless operation active",
            )

        if importlib.util.find_spec("tkinter") is not None:
            try:
                animator = FaceAnimator()
                controller = TkinterFaceController(
                    animator=animator,
                    width=self.config.display.width,
                    height=self.config.display.height,
                    fullscreen=fullscreen or self.config.display.fullscreen,
                )
                return controller, ComponentStatus(
                    name="Face",
                    backend="Tkinter",
                    state="READY",
                    detail=f"GUI window enabled ({self.config.display.width}x{self.config.display.height})",
                )
            except Exception as exc:  # noqa: BLE001
                animator = FaceAnimator()
                return NullFaceController(animator=animator), ComponentStatus(
                    name="Face",
                    backend="NullFaceController",
                    state="DEGRADED",
                    detail=f"Tkinter window init failed ({exc}); fallback to headless",
                    remediation="Verify X11/display server is running or pass --headless",
                )

        animator = FaceAnimator()
        return NullFaceController(animator=animator), ComponentStatus(
            name="Face",
            backend="NullFaceController",
            state="DEGRADED",
            detail="python3-tk not installed; fallback to headless",
            remediation="Install python3-tk or run with --headless",
        )

    # -------------------------------------------------------------------------
    # Vision Component
    # -------------------------------------------------------------------------
    def build_vision(
        self,
        no_camera: bool = False,
        simulate: bool = False,
    ) -> tuple[VisionBackend | None, ComponentStatus]:
        """Build camera presence vision backend."""
        if no_camera or not self.config.vision.enabled:
            return None, ComponentStatus(
                name="Vision",
                backend="None",
                state="DISABLED",
                detail="Disabled by flag/config",
            )

        if simulate:
            fake_v = FakeVisionBackend()
            fake_v.set_presence(True)
            return fake_v, ComponentStatus(
                name="Vision",
                backend="FakeVisionBackend (Simulated)",
                state="SIMULATED",
                detail="Simulated presence detection active",
            )

        if importlib.util.find_spec("cv2") is None:
            return None, ComponentStatus(
                name="Vision",
                backend="OpenCV",
                state="UNAVAILABLE",
                detail="opencv-python library not installed",
                remediation="pip install -e '.[vision]'",
            )

        cameras_count = len(self.hardware_report.cameras) if self.hardware_report else 0
        if cameras_count == 0:
            return None, ComponentStatus(
                name="Vision",
                backend="OpenCV",
                state="DISABLED",
                detail="No physical cameras detected on host",
                remediation="Connect a USB camera or run with --no-camera",
            )

        try:
            from ailen.vision.opencv_backend import OpenCvVisionBackend

            backend = OpenCvVisionBackend(
                camera_device=self.config.vision.camera_device,
                fps=self.config.vision.fps,
            )
            return backend, ComponentStatus(
                name="Vision",
                backend="OpenCV",
                state="READY",
                detail=f"Camera device '{self.config.vision.camera_device}' active @ {self.config.vision.fps} FPS",
            )
        except Exception as exc:  # noqa: BLE001
            return None, ComponentStatus(
                name="Vision",
                backend="OpenCV",
                state="UNAVAILABLE",
                detail=f"OpenCV initialization failed: {exc}",
            )

    # -------------------------------------------------------------------------
    # Audio I/O Components
    # -------------------------------------------------------------------------
    def build_audio_io(
        self,
        no_audio: bool = False,
        simulate: bool = False,
    ) -> tuple[AudioInputBackend | None, AudioOutputBackend | None, ComponentStatus]:
        """Build ALSA audio input and output backends."""
        if no_audio:
            return None, None, ComponentStatus(
                name="Audio",
                backend="None",
                state="DISABLED",
                detail="Audio disabled by flag",
            )

        if simulate:
            return (
                FakeAudioInputBackend(),
                FakeAudioOutputBackend(),
                ComponentStatus(
                    name="Audio",
                    backend="FakeAudio (Simulated)",
                    state="SIMULATED",
                    detail="Simulated audio capture and playback",
                ),
            )

        if not sys.platform.startswith("linux"):
            return None, None, ComponentStatus(
                name="Audio",
                backend="ALSA",
                state="UNAVAILABLE",
                detail=f"ALSA audio is only supported on Linux (current: {sys.platform})",
            )

        try:
            in_dev = self.config.audio.input_device
            out_dev = self.config.audio.output_device

            if shutil.which("arecord") is None or shutil.which("aplay") is None:
                return None, None, ComponentStatus(
                    name="Audio",
                    backend="ALSA",
                    state="UNAVAILABLE",
                    detail="arecord/aplay not available",
                    remediation="Install alsa-utils before running live audio",
                )

            report_inputs = self.hardware_report.audio_inputs if self.hardware_report else []
            report_outputs = self.hardware_report.audio_outputs if self.hardware_report else []
            enumerator = AlsaDeviceEnumerator()
            hardware_inputs = enumerator.list_hardware_devices(is_input=True)
            hardware_outputs = enumerator.list_hardware_devices(is_input=False)
            routing_endpoints = enumerator.list_devices()

            if not report_inputs and not hardware_inputs:
                return None, None, ComponentStatus(
                    name="Audio",
                    backend="ALSA",
                    state="UNAVAILABLE",
                    detail="No real audio capture hardware detected",
                    remediation="Connect/configure microphone and run `ailen lab audio-devices`",
                )
            if not report_outputs and not hardware_outputs:
                return None, None, ComponentStatus(
                    name="Audio",
                    backend="ALSA",
                    state="UNAVAILABLE",
                    detail="No real audio playback hardware detected",
                    remediation="Connect/configure speakers/headphones and run `ailen lab audio-devices`",
                )

            # HardwareCapabilityReport uses /proc/asound IDs (e.g. hw:03-00),
            # while the operator-facing lab CLI intentionally recommends ALSA
            # `plughw:CARD=...,DEV=...` endpoints from arecord/aplay -l. Accept
            # either source so a device proven by the lab CLI is not rejected by
            # the factory merely because the two enumerators use different IDs.
            input_ids = (
                {d.id for d in report_inputs}
                | {d.id for d in hardware_inputs}
                | {d.id for d in routing_endpoints if d.is_input}
            )
            output_ids = (
                {d.id for d in report_outputs}
                | {d.id for d in hardware_outputs}
                | {d.id for d in routing_endpoints if d.is_output}
            )
            if in_dev != "default" and in_dev not in input_ids:
                return None, None, ComponentStatus(
                    name="Audio", backend="ALSA", state="UNAVAILABLE",
                    detail=f"Configured input device '{in_dev}' was not detected",
                    remediation="Run `ailen lab audio-devices` and choose a listed physical capture endpoint",
                )
            if out_dev != "default" and out_dev not in output_ids:
                return None, None, ComponentStatus(
                    name="Audio", backend="ALSA", state="UNAVAILABLE",
                    detail=f"Configured output device '{out_dev}' was not detected",
                    remediation="Run `ailen lab audio-devices` and choose a listed physical playback endpoint",
                )

            in_backend = AlsaAudioInputBackend(device=in_dev, sample_rate=self.config.audio.sample_rate)
            out_backend = AlsaAudioOutputBackend(device=out_dev)
            return in_backend, out_backend, ComponentStatus(
                name="Audio",
                backend="ALSA",
                state="READY",
                detail=f"ALSA endpoints detected: in='{in_dev}' out='{out_dev}' @ {self.config.audio.sample_rate}Hz",
            )

        except Exception as exc:  # noqa: BLE001
            return None, None, ComponentStatus(
                name="Audio",
                backend="ALSA",
                state="UNAVAILABLE",
                detail=f"ALSA initialization failed: {exc}",
            )

    # -------------------------------------------------------------------------
    # STT Component
    # -------------------------------------------------------------------------
    def build_stt(
        self,
        no_audio: bool = False,
        simulate: bool = False,
    ) -> tuple[SttBackend | None, ComponentStatus]:
        """Build Speech-to-Text backend."""
        if no_audio:
            return None, ComponentStatus(name="STT", backend="None", state="DISABLED", detail="Audio disabled")

        if simulate:
            return FakeSttBackend(canned_text="Hola Ailén"), ComponentStatus(
                name="STT", backend="FakeStt (Simulated)", state="SIMULATED", detail="Simulated STT active"
            )

        engine = self.config.speech.stt_engine.lower()
        if engine == "vosk":
            if importlib.util.find_spec("vosk") is None:
                return None, ComponentStatus(
                    name="STT",
                    backend="Vosk",
                    state="UNAVAILABLE",
                    detail="vosk library not installed",
                    remediation="pip install -e '.[stt-vosk]'",
                )

            model_path_str = self.config.speech.stt_model_path.strip()
            if not model_path_str or not Path(model_path_str).is_dir():
                return None, ComponentStatus(
                    name="STT",
                    backend="Vosk",
                    state="MISSING_MODEL",
                    detail=f"Vosk model path not found: '{model_path_str or 'not configured'}'",
                    remediation="Set speech.stt_model_path in ailen.toml to valid Vosk model directory",
                )

            vosk_backend = VoskSttBackend(model_path=model_path_str)
            vosk_health = vosk_backend.health()
            if vosk_health.status == ServiceStatus.HEALTHY:
                return vosk_backend, ComponentStatus(
                    name="STT", backend="Vosk", state="READY", detail=f"Vosk model '{model_path_str}' loaded"
                )
            return None, ComponentStatus(
                name="STT", backend="Vosk", state="UNAVAILABLE", detail=f"Vosk health check failed: {vosk_health.detail}"
            )

        if engine == "whisper_cpp":
            model_path_str = self.config.speech.stt_model_path.strip()
            whisper_backend = WhisperCppSttBackend(model_path=model_path_str)
            whisper_health = whisper_backend.health()
            if whisper_health.status == ServiceStatus.HEALTHY:
                return whisper_backend, ComponentStatus(
                    name="STT", backend="whisper.cpp", state="READY", detail=f"Whisper model '{model_path_str}'"
                )
            return None, ComponentStatus(
                name="STT",
                backend="whisper.cpp",
                state="MISSING_MODEL" if "not found" in whisper_health.detail else "UNAVAILABLE",
                detail=whisper_health.detail,
                remediation="Ensure whisper-cli binary and model file exist",
            )

        return None, ComponentStatus(
            name="STT",
            backend=engine or "None",
            state="DISABLED",
            detail=f"STT engine '{engine}' not active or unconfigured",
        )

    # -------------------------------------------------------------------------
    # TTS Component
    # -------------------------------------------------------------------------
    def build_tts(
        self,
        no_audio: bool = False,
        simulate: bool = False,
    ) -> tuple[TtsBackend | None, ComponentStatus]:
        """Build Text-to-Speech synthesis backend."""
        if no_audio:
            return None, ComponentStatus(name="TTS", backend="None", state="DISABLED", detail="Audio disabled")

        if simulate:
            return FakeTtsBackend(), ComponentStatus(
                name="TTS", backend="FakeTts (Simulated)", state="SIMULATED", detail="Simulated TTS active"
            )

        engine = self.config.speech.tts_engine.lower()
        if engine == "piper":
            piper_exe = resolve_piper_executable("piper")
            if not piper_exe:
                return None, ComponentStatus(
                    name="TTS",
                    backend="Piper",
                    state="UNAVAILABLE",
                    detail="piper binary not found in PATH",
                    remediation="Install piper binary in PATH",
                )

            model_path_str = self.config.speech.tts_model_path.strip()
            if not model_path_str or not Path(model_path_str).is_file():
                return None, ComponentStatus(
                    name="TTS",
                    backend="Piper",
                    state="MISSING_MODEL",
                    detail=f"Piper voice model .onnx not found: '{model_path_str or 'not configured'}'",
                    remediation="Set speech.tts_model_path in ailen.toml to valid .onnx voice model",
                )

            piper_backend = PiperTtsBackend(
                binary_path=piper_exe,
                model_path=model_path_str,
                config_path=self.config.speech.tts_config_path,
            )
            piper_health = piper_backend.health()
            if piper_health.status == ServiceStatus.HEALTHY:
                return piper_backend, ComponentStatus(
                    name="TTS", backend="Piper", state="READY", detail=f"Piper voice model '{model_path_str}' loaded"
                )
            return None, ComponentStatus(
                name="TTS", backend="Piper", state="UNAVAILABLE", detail=f"Piper health check failed: {piper_health.detail}"
            )

        return None, ComponentStatus(
            name="TTS",
            backend=engine or "None",
            state="DISABLED",
            detail=f"TTS engine '{engine}' unconfigured",
        )

    # -------------------------------------------------------------------------
    # AI Backends
    # -------------------------------------------------------------------------
    def build_ai_backends(
        self,
        no_ai: bool = False,
        simulate: bool = False,
        model_plan: ModelPlan | None = None,
        runtime_descriptors: list[ExternalRuntimeDescriptor] | None = None,
        inference_profile: InferenceProfile | None = None,
    ) -> tuple[dict[str, AiBackend], ComponentStatus]:
        """Build configured AI backends without silently substituting models/providers."""
        if no_ai:
            return {}, ComponentStatus(name="AI Inference", backend="None", state="DISABLED", detail="AI disabled by flag")

        if simulate:
            return {
                "local": FakeAiBackend(canned_response="Hola, estoy funcionando en modo simulación de laboratorio."),
                "fake": FakeAiBackend(canned_response="Respuesta simulada."),
            }, ComponentStatus(
                name="AI Inference",
                backend="FakeAi (Simulated)",
                state="SIMULATED",
                detail="Simulated local AI backend active",
            )

        backends: dict[str, AiBackend] = {}
        runtimes = runtime_descriptors or []
        healthy_runtimes = [r for r in runtimes if r.health and r.health.status == RuntimeStatus.HEALTHY]
        inventory = RuntimeModelInventory()
        local_problem = "No healthy local runtime detected"

        target_id = model_plan.selected_model_id if model_plan else None
        target_aliases = model_plan.model_descriptor.runtime_aliases if model_plan and model_plan.model_descriptor else []

        # Local runtime: require an explicit model mapping. Never take the first
        # arbitrary model from an existing Ollama installation.
        for rt in healthy_runtimes:
            candidates: list[tuple[str, list[str]]] = []
            if self.config.ai.local.enabled and self.config.ai.local.model.strip():
                candidates.append((self.config.ai.local.model.strip(), []))
            if target_id:
                candidates.append((target_id, target_aliases))

            resolved_model: str | None = None
            for candidate_id, aliases in candidates:
                resolved_model = inventory.resolve_model(rt.endpoint, candidate_id, aliases=aliases)
                if resolved_model:
                    break

            if resolved_model:
                if rt.runtime_type == RuntimeType.OLLAMA:
                    keep_alive = ModelResidencyPolicy.get_default_keep_alive(
                        inference_profile or InferenceProfile.BALANCED
                    )
                    backends["local"] = OllamaNativeBackend(
                        endpoint=rt.endpoint,
                        model=resolved_model,
                        timeout_seconds=self.config.ai.local.timeout_seconds,
                        think=False,
                        keep_alive=keep_alive,
                    )
                    local_problem = (
                        f"Ollama native API at {rt.endpoint} using '{resolved_model}' "
                        "with thinking disabled for voice latency"
                    )
                else:
                    backends["local"] = GenericOpenAiBackend(
                        endpoint=rt.endpoint,
                        model=resolved_model,
                        provider_name=rt.runtime_type.value.lower(),
                        is_local=True,
                        timeout_seconds=self.config.ai.local.timeout_seconds,
                    )
                    local_problem = f"{rt.runtime_type.value} at {rt.endpoint} using '{resolved_model}'"
                break

            local_problem = (
                f"{rt.runtime_type.value} is healthy but no configured/catalog model maps to its inventory"
            )

        # Optional trusted/untrusted LAN Brain. Routing/privacy policy decides
        # whether its trust level permits a given request.
        if self.config.ai.lan.enabled:
            lan_backend = LanBrainAiBackend(
                endpoint=self.config.ai.lan.endpoint,
                model=self.config.ai.lan.model,
                timeout_seconds=self.config.ai.lan.timeout_seconds,
                trusted=self.config.ai.lan.trusted,
            )
            if lan_backend.health().status == ServiceStatus.HEALTHY:
                backends["lan_brain"] = lan_backend

        # Cloud uses the same SecretResolver/config contract audited in R3A; no
        # hard-coded environment variable names are allowed here.
        if self.config.ai.cloud.enabled:
            cloud_backend = CloudAiBackend(
                endpoint=self.config.ai.cloud.endpoint,
                model=self.config.ai.cloud.model,
                api_key_env=self.config.ai.cloud.api_key_env,
                api_key_file=self.config.ai.cloud.api_key_file,
                secrets_resolver=SecretResolver(),
                timeout_seconds=self.config.ai.cloud.timeout_seconds,
                provider_name=self.config.ai.cloud.provider,
                input_cost_per_million=self.config.ai.cloud.input_cost_per_million,
                output_cost_per_million=self.config.ai.cloud.output_cost_per_million,
            )
            if cloud_backend.health().status == ServiceStatus.HEALTHY:
                backends["cloud"] = cloud_backend

        if backends:
            backend_names = ", ".join(sorted(backends))
            detail = f"Available backends: {backend_names}. Local: {local_problem}"
            return backends, ComponentStatus(
                name="AI Inference",
                backend=backend_names,
                state="READY",
                detail=detail,
            )

        state = "MISSING_MODEL" if healthy_runtimes else "NOT_RUNNING"
        return {}, ComponentStatus(
            name="AI Inference",
            backend=healthy_runtimes[0].runtime_type.value if healthy_runtimes else "None",
            state=state,
            detail=local_problem,
            remediation=(
                "Configure an explicit runtime model mapping or prepare/start the verified AILEN model"
                if healthy_runtimes
                else "Start a configured local/LAN/cloud backend or run with --no-ai"
            ),
        )


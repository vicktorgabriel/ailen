"""Dedicated non-invasive runner for AILEN Lab Mode with live hardware and interaction wiring."""

import json
import logging
import os
import queue
import signal
import threading
import time
import uuid
from pathlib import Path
from types import FrameType
from typing import Any

from ailen.ai.budget import BudgetPolicy
from ailen.ai.context import AiContextBuilder
from ailen.ai.contracts import AiBackend
from ailen.ai.ollama_backend import OllamaNativeBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.router import RuleBasedRouter
from ailen.audio.contracts import (
    AudioInputBackend,
    AudioOutputBackend,
    SttBackend,
    TtsBackend,
    VoiceActivityDetector,
)
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.noise import WebRtcNoiseProcessor
from ailen.audio.stt_quality import SttQualityEvaluator
from ailen.audio.vad import EnergyVad, UtteranceCollector, WebRtcVad
from ailen.core.capabilities import CapabilityDescriptor, CapabilityProvider, CapabilityRegistry
from ailen.core.config import AILENConfig
from ailen.core.conversation import ConversationCoordinator
from ailen.core.coordinator import InteractionCoordinator
from ailen.core.events import EventBus
from ailen.core.personality import PersonalityService, PersonalityTraits
from ailen.core.social import SocialEngine
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState, EventType, PrivacyLevel, ServiceStatus
from ailen.face.contracts import FaceController
from ailen.face.null import NullFaceController
from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.hardware.detector import HardwareDetector
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.models.catalog import ModelCatalog, ModelPurpose
from ailen.models.inference_profile import InferenceRecommendation, recommend_inference_profile
from ailen.models.planner import ModelPlan, ModelPlanner
from ailen.models.store import ModelStore
from ailen.runtime.contracts import ExternalRuntimeDescriptor, RuntimeStatus, RuntimeType
from ailen.runtime.factory import ComponentStatus, LabComponentFactory
from ailen.runtime.inventory import RuntimeModelInventory
from ailen.runtime.managed import ManagedLlamaRuntime
from ailen.runtime.manager import LocalRuntimeManager
from ailen.runtime.metrics import LabSessionMetrics
from ailen.tools.builtin import (
    CameraTool,
    ClockTool,
    FaceExpressionTool,
    MprisMusicService,
    MusicTool,
    NotesTool,
    ReminderService,
    RemindersTool,
    SystemStatusTool,
    TimerTool,
    VolumeTool,
    WebFetchTool,
    WebSearchTool,
)
from ailen.tools.builtin.web_search import create_web_search_provider
from ailen.tools.executor import ToolExecutor
from ailen.tools.registry import ToolRegistry
from ailen.tools.semantic_intent import SemanticToolIntentResolver
from ailen.vision.contracts import PresenceObservation, VisionBackend
from ailen.vision.control import CameraControl, create_camera_control
from ailen.vision.debouncer import VisionDebouncer

logger = logging.getLogger("ailen.runtime.runner")


class LabRunner:
    """Orchestrates non-invasive Lab Mode runtime for physical development workstations."""

    def __init__(
        self,
        config: AILENConfig,
        dry_run: bool = False,
        headless: bool = False,
        no_camera: bool = False,
        no_audio: bool = False,
        no_ai: bool = False,
        simulate: bool = False,
        fullscreen: bool = False,
        duration: float | None = None,
        log_dir: Path | str | None = None,
        managed_runtime: ManagedLlamaRuntime | None = None,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.headless = headless
        self.no_camera = no_camera
        self.no_audio = no_audio
        self.no_ai = no_ai
        self.simulate = simulate
        self.fullscreen = fullscreen
        self.duration = duration

        self.log_dir = Path(log_dir) if log_dir else Path("runtime/lab")
        self._session_id = f"lab_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        self.metrics = LabSessionMetrics(session_id=self._session_id)

        self._is_running = False
        self._shutdown_requested = False
        self._interaction_lock = threading.Lock()
        self._is_processing_interaction = False
        self._processed_transcript_event_ids: set[str] = set()
        self._last_voice_ended_monotonic: float | None = None
        self.stt_quality_evaluator = SttQualityEvaluator()

        # Core infrastructure
        self.event_bus = EventBus()
        self.state_manager = StateManager(initial_state=AssistantState.IDLE)
        self.db_mgr: SQLiteManager | None = None
        self.memory_repo: MemoryRepository | None = None
        self._conversation_session_id: str | None = None

        # Hardware & Model Planning
        self.hardware_report: HardwareCapabilityReport | None = None
        self.detected_profile = config.node.profile
        self.model_plan: ModelPlan | None = None
        self.inference_recommendation: InferenceRecommendation | None = None
        self.runtime_descriptors: list[ExternalRuntimeDescriptor] = []
        self.component_statuses: list[ComponentStatus] = []

        # Components
        self.face_controller: FaceController = NullFaceController()
        self.vision_backend: VisionBackend | None = None
        self.camera_control: CameraControl | None = None
        self.vision_debouncer = VisionDebouncer(
            presence_confirm_seconds=config.vision.presence_confirm_seconds,
            absence_confirm_seconds=config.vision.absence_confirm_seconds,
            dropout_grace_seconds=config.vision.dropout_grace_seconds,
        )
        self.audio_in: AudioInputBackend | None = None
        self.audio_out: AudioOutputBackend | None = None
        self.stt_backend: SttBackend | None = None
        self.tts_backend: TtsBackend | None = None
        self.ai_backends: dict[str, AiBackend] = {}

        # Coordinators & Tools
        self.social_engine: SocialEngine | None = None
        self.interaction_coordinator: InteractionCoordinator | None = None
        self.audio_coordinator: AudioInteractionCoordinator | None = None
        self.tool_registry: ToolRegistry | None = None
        self.capability_registry: CapabilityRegistry | None = None
        self.tool_executor: ToolExecutor | None = None
        self.conversation_coordinator: ConversationCoordinator | None = None
        self.personality_service: PersonalityService | None = None
        self.reminder_service: ReminderService | None = None
        self._pending_reminder_announcements: queue.Queue[dict[str, str]] = queue.Queue()
        self.managed_runtime = managed_runtime

        self._vision_thread: threading.Thread | None = None
        self._vision_observations_delivered = 0

    def inspect_and_plan(self) -> tuple[HardwareCapabilityReport, ModelPlan]:
        """Detect hardware capabilities, discover runtimes, and compute optimal model plan."""
        store = ModelStore()
        detector = HardwareDetector()
        self.hardware_report = detector.detect(str(store.base_dir))
        rec = detector.recommend_profile(self.hardware_report)
        self.detected_profile = rec.profile

        runtime_mgr = LocalRuntimeManager()
        self.runtime_descriptors = runtime_mgr.detect_available_runtimes()

        self.inference_recommendation = recommend_inference_profile(
            self.hardware_report,
            device_profile=rec.profile,
        )
        catalog = ModelCatalog()
        planner = ModelPlanner(catalog=catalog)
        self.model_plan = planner.plan(
            self.hardware_report,
            profile=rec.profile,
            purpose=ModelPurpose.BALANCED,
            desired_context=self.inference_recommendation.recommended_context,
            inference_profile=self.inference_recommendation.profile,
        )
        return self.hardware_report, self.model_plan

    def init_components(self) -> list[ComponentStatus]:
        """Build and wire all subsystem components via LabComponentFactory."""
        self.component_statuses.clear()
        factory = LabComponentFactory(config=self.config, hardware_report=self.hardware_report)

        # 1. Face
        self.face_controller, face_st = factory.build_face(
            headless=self.headless,
            simulate=self.simulate,
            fullscreen=self.fullscreen,
        )
        self.component_statuses.append(face_st)

        # 2. Vision
        self.vision_backend, vision_st = factory.build_vision(
            no_camera=self.no_camera,
            simulate=self.simulate,
        )
        self.component_statuses.append(vision_st)

        camera_password = os.getenv(self.config.vision.network_camera_password_env, "")
        self.camera_control = create_camera_control(
            self.config.vision.camera_control_driver,
            host=self.config.vision.network_camera_host,
            username=self.config.vision.network_camera_username,
            password=camera_password,
            port=self.config.vision.network_camera_http_port,
            timeout_seconds=self.config.vision.camera_control_timeout_seconds,
        )
        if self.config.vision.camera_control_driver != "none":
            control_configured = bool(self.camera_control and self.camera_control.is_configured)
            self.component_statuses.append(
                ComponentStatus(
                    name="CameraControl",
                    backend=self.config.vision.camera_control_driver,
                    state="PENDING" if control_configured else "UNAVAILABLE",
                    detail=(
                        "Configured; management endpoint not verified yet"
                        if control_configured
                        else f"Missing {self.config.vision.network_camera_password_env} or camera control settings"
                    ),
                )
            )

        # 3. Audio I/O
        self.audio_in, self.audio_out, audio_st = factory.build_audio_io(
            no_audio=self.no_audio,
            simulate=self.simulate,
        )
        self.component_statuses.append(audio_st)

        # 4. STT
        self.stt_backend, stt_st = factory.build_stt(
            no_audio=self.no_audio,
            simulate=self.simulate,
        )
        self.component_statuses.append(stt_st)

        # 5. TTS
        self.tts_backend, tts_st = factory.build_tts(
            no_audio=self.no_audio,
            simulate=self.simulate,
        )
        self.component_statuses.append(tts_st)

        # 6. AI Backends. If the verified planned GGUF is already installed and
        # no matching local runtime is active, LabRunner may start an AILEN-owned
        # llama.cpp server for this session. It never downloads here.
        self.ai_backends, ai_st = factory.build_ai_backends(
            no_ai=self.no_ai,
            simulate=self.simulate,
            model_plan=self.model_plan,
            runtime_descriptors=self.runtime_descriptors,
            inference_profile=(
                self.inference_recommendation.profile if self.inference_recommendation else None
            ),
        )

        if (
            not self.no_ai
            and not self.dry_run
            and not self.simulate
            and "local" not in self.ai_backends
            and self.model_plan
            and self.model_plan.is_viable
            and self.model_plan.selected_model_id
            and self.model_plan.model_descriptor
        ):
            store = ModelStore()
            model_id = self.model_plan.selected_model_id
            descriptor = self.model_plan.model_descriptor
            if store.exists(model_id) and store.verify(model_id, descriptor.sha256):
                runtime = self.managed_runtime or ManagedLlamaRuntime()
                started = runtime.start(
                    model_path=store.get_model_path(model_id),
                    host="127.0.0.1",
                    port=8080,
                    context_size=self.model_plan.context_size,
                    gpu_layers=self.model_plan.gpu_layers,
                    model_alias=model_id,
                )
                if started:
                    self.managed_runtime = runtime
                    self.runtime_descriptors = LocalRuntimeManager().detect_available_runtimes()
                    self.ai_backends, ai_st = factory.build_ai_backends(
                        no_ai=False,
                        simulate=False,
                        model_plan=self.model_plan,
                        runtime_descriptors=self.runtime_descriptors,
                        inference_profile=(
                            self.inference_recommendation.profile if self.inference_recommendation else None
                        ),
                    )

        self.component_statuses.append(ai_st)

        # 7. Wire Database & Memory
        try:
            db_path = Path(self.config.memory.sqlite_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_mgr = SQLiteManager(str(db_path))
            MigrationRunner(self.db_mgr).run_migrations()
            self.memory_repo = MemoryRepository(self.db_mgr)
            recovered_sessions = self.memory_repo.close_open_sessions(
                source_node_id=self.config.node.node_id
            )
            if recovered_sessions:
                logger.info(
                    "Closed %d orphan conversation session(s) from a previous unclean exit",
                    recovered_sessions,
                )
            conversation_session = self.memory_repo.create_session(
                mode=self.config.social.default_mode,
                source_node_id=self.config.node.node_id,
            )
            self._conversation_session_id = conversation_session.session_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not initialize SQLite memory: %s", exc)

        # 8. Build bounded persistent personality profile. Existing SQLite
        # tables from migration 0001 store only safe stylistic traits/events.
        self.personality_service = PersonalityService(
            identity_id=self.config.personality.seed,
            defaults=PersonalityTraits(
                humor=self.config.personality.base_humor,
                formality=self.config.personality.base_formality,
                curiosity=self.config.personality.base_curiosity,
                initiative=self.config.personality.base_sociability,
                verbosity=self.config.personality.base_verbosity,
                patience=self.config.personality.base_patience,
                expressiveness=self.config.personality.base_expressiveness,
            ),
            repository=self.memory_repo,
            enabled=self.config.personality.evolution_enabled,
            evolution_rate=self.config.personality.evolution_rate,
        )

        # 9. Wire Social & Interaction Coordinators
        self.social_engine = SocialEngine(
            default_cooldown_seconds=self.config.social.greeting_cooldown_seconds,
            allow_greetings=self.config.social.auto_greeting_enabled,
        )
        self.interaction_coordinator = InteractionCoordinator(
            state_manager=self.state_manager,
            social_engine=self.social_engine,
            event_bus=self.event_bus,
            mode=self.config.social.default_mode,
            face_controller=self.face_controller,
            debouncer=self.vision_debouncer,
        )

        # 9. Wire live Audio Interaction Coordinator only when the complete real
        # speech chain is available. Passing None here would trigger the generic
        # coordinator's Fake defaults, which is forbidden outside --simulate.
        if self.audio_in and self.audio_out and self.stt_backend and self.tts_backend:
            frame_ms = self.config.audio.frame_ms
            hangover_frames = max(0, round(self.config.speech.vad_hangover_ms / frame_ms))
            listening_vad: VoiceActivityDetector
            if self.config.speech.vad_engine == "webrtc":
                listening_vad = WebRtcVad(
                    sample_rate=self.config.audio.sample_rate,
                    frame_ms=frame_ms,
                    mode=self.config.speech.vad_webrtc_mode,
                    hangover_frames=hangover_frames,
                    min_rms=self.config.speech.vad_threshold,
                )
                interruption_vad = WebRtcVad(
                    sample_rate=self.config.audio.sample_rate,
                    frame_ms=frame_ms,
                    mode=min(3, self.config.speech.vad_webrtc_mode + 1),
                    hangover_frames=0,
                )
            elif self.config.speech.vad_engine == "energy":
                listening_vad = EnergyVad(
                    threshold_rms=self.config.speech.vad_threshold,
                    hangover_frames=hangover_frames,
                )
                interruption_vad = None
            else:
                raise RuntimeError(
                    f"Live Lab requires speech.vad_engine=energy/webrtc, got {self.config.speech.vad_engine!r}"
                )
            frame_processor = None
            if self.config.speech.noise_suppression_engine == "webrtc":
                frame_processor = WebRtcNoiseProcessor(
                    sample_rate=self.config.audio.sample_rate,
                    channels=self.config.audio.channels,
                    noise_suppression=self.config.speech.noise_suppression_level,
                    auto_gain=0,
                )

            collector = UtteranceCollector(
                vad=listening_vad,
                sample_rate=self.config.audio.sample_rate,
                channels=self.config.audio.channels,
                frame_ms=frame_ms,
                min_speech_ms=self.config.speech.min_speech_ms,
                silence_timeout_ms=self.config.speech.silence_timeout_ms,
                max_utterance_seconds=self.config.speech.max_utterance_seconds,
                pre_roll_ms=self.config.speech.pre_roll_ms,
            )
            self.audio_coordinator = AudioInteractionCoordinator(
                audio_input=self.audio_in,
                audio_output=self.audio_out,
                frame_processor=frame_processor,
                stt=self.stt_backend,
                tts=self.tts_backend,
                utterance_collector=collector,
                state_manager=self.state_manager,
                face_controller=self.face_controller,
                event_bus=self.event_bus,
                auto_reset_after_stt=not bool(self.ai_backends),
                interruption_enabled=self.config.speech.interruption_enabled,
                interruption_threshold_rms=self.config.speech.interruption_threshold_rms,
                interruption_min_ms=self.config.speech.interruption_min_ms,
                interruption_calibration_ms=self.config.speech.interruption_calibration_ms,
                interruption_leak_multiplier=self.config.speech.interruption_leak_multiplier,
                interruption_vad=interruption_vad,
                default_speech_rate=self.config.speech.tts_rate,
                frame_ms=frame_ms,
            )

        # 10. Wire Tool Registry & Controlled Executor. Reminders persist in
        # SQLite; when memory is unavailable the tool fails closed rather than
        # degrading into a volatile timer.
        if self.memory_repo is not None:
            self.reminder_service = ReminderService(
                repository=self.memory_repo,
                event_bus=self.event_bus,
            )
        self.tool_registry = ToolRegistry([
            CameraTool(self.camera_control),
            ClockTool(),
            FaceExpressionTool(self.face_controller),
            TimerTool(),
            RemindersTool(repository=self.memory_repo),
            VolumeTool(),
            MusicTool(service=MprisMusicService()),
            NotesTool(repository=self.memory_repo),
            SystemStatusTool(),
            WebSearchTool(
                provider=create_web_search_provider(
                    self.config.network.web_search_provider,
                    region=self.config.network.web_search_region,
                )
            ),
            WebFetchTool(),
        ])
        self.tool_executor = ToolExecutor(
            registry=self.tool_registry,
            event_bus=self.event_bus,
            repository=self.memory_repo,
        )
        self.capability_registry = CapabilityRegistry(
            self.tool_registry,
            network_access_allowed=self.config.network.outbound_web_enabled,
        )
        self.capability_registry.register(
            CapabilityDescriptor(
                key="ai.conversation",
                description="conversar usando el modelo de IA disponible",
                available=bool(self.ai_backends),
                source="ai",
            )
        )
        for provider in (
            self.face_controller,
            self.vision_backend,
            self.camera_control,
            self.audio_coordinator,
        ):
            if isinstance(provider, CapabilityProvider):
                self.capability_registry.register_provider(provider)

        # 11. Wire Conversation Coordinator. Cloud/LAN policies are the same
        # audited policies used by normal Core, including budget enforcement.
        if self.ai_backends:
            context_builder = AiContextBuilder(
                repository=self.memory_repo,
                request_timeout_seconds=self.config.ai.local.timeout_seconds,
                max_recent_messages=self.config.ai.context_recent_messages,
                max_char_budget=self.config.ai.context_char_budget,
                max_output_tokens=min(self.config.ai.max_tokens, 128),
                temperature=self.config.ai.temperature,
            )
            router = RuleBasedRouter()
            orchestrator = AiOrchestrator(
                backends=self.ai_backends,
                router=router,
                repository=self.memory_repo,
                event_bus=self.event_bus,
            )
            budget_policy = BudgetPolicy(
                repository=self.memory_repo,
                daily_budget_usd=self.config.ai.cloud.daily_budget_usd,
                monthly_budget_usd=self.config.ai.cloud.monthly_budget_usd,
            )
            semantic_intent_backend = self._build_semantic_intent_backend()
            semantic_intent_resolver = SemanticToolIntentResolver(
                backend=semantic_intent_backend,
                registry=self.tool_registry,
                repository=self.memory_repo,
                request_timeout_seconds=self.config.ai.local.intent_timeout_seconds,
                allow_network_tools=self.config.network.outbound_web_enabled,
            )
            self.conversation_coordinator = ConversationCoordinator(
                context_builder=context_builder,
                router=router,
                orchestrator=orchestrator,
                semantic_intent_resolver=semantic_intent_resolver,
                audio_coordinator=self.audio_coordinator,
                face_controller=self.face_controller,
                tool_executor=self.tool_executor,
                profile=self.detected_profile,
                mode=self.config.social.default_mode,
                privacy_level=PrivacyLevel.PRIVATE,
                identity_name=self.config.identity.display_name,
                tts_voice_id=self.config.speech.tts_voice,
                internet_available=self.config.network.outbound_web_enabled,
                tool_network_allowed=self.config.network.outbound_web_enabled,
                cloud_allowed=self.config.ai.cloud.enabled and self.config.ai.allow_cloud,
                lan_brain_trusted=self.config.ai.lan.trusted,
                preferred_backend=self.config.ai.provider,
                budget_policy=budget_policy,
                runtime_context_provider=self._runtime_context_snapshot,
                repository=self.memory_repo,
                personality_service=self.personality_service,
                persona_description=self.config.personality.description,
                capability_registry=self.capability_registry,
            )

        # 12. Subscribe to lightweight events for single-flight conversation and
        # measured lab telemetry. No PCM or camera frames enter the EventBus.
        self.event_bus.subscribe(EventType.TRANSCRIPT_READY, self._on_transcript_event)
        self.event_bus.subscribe(EventType.VOICE_ENDED, self._on_voice_ended_event)
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self._on_speech_started_event)
        self.event_bus.subscribe(EventType.SPEECH_FINISHED, self._on_speech_finished_event)
        self.event_bus.subscribe(EventType.PRESENCE_DETECTED, self._on_presence_transition_event)
        self.event_bus.subscribe(EventType.PRESENCE_LOST, self._on_presence_transition_event)
        self.event_bus.subscribe(EventType.REMINDER_DUE, self._on_reminder_due_event)

        return self.component_statuses


    def _build_semantic_intent_backend(self) -> AiBackend | None:
        """Resolve an optional lightweight local backend for tool intent parsing.

        No model is downloaded or started here. The configured intent model must
        already exist in the healthy local Ollama inventory; otherwise the main
        local conversational backend is reused.
        """
        fallback = self.ai_backends.get("local")
        intent_model = self.config.ai.local.intent_model.strip()
        if not intent_model:
            return fallback

        inventory = RuntimeModelInventory()
        for runtime in self.runtime_descriptors:
            if (
                runtime.runtime_type != RuntimeType.OLLAMA
                or runtime.health is None
                or runtime.health.status != RuntimeStatus.HEALTHY
            ):
                continue
            resolved = inventory.resolve_model(runtime.endpoint, intent_model, aliases=[])
            if not resolved:
                continue
            logger.info(
                "Using dedicated local intent model '%s' on Ollama; conversational model remains separate",
                resolved,
            )
            return OllamaNativeBackend(
                endpoint=runtime.endpoint,
                model=resolved,
                timeout_seconds=self.config.ai.local.intent_timeout_seconds,
                think=False,
                keep_alive="10m",
            )

        logger.warning(
            "Configured intent model '%s' is not available; reusing main local backend",
            intent_model,
        )
        return fallback

    def _prewarm_ai_models(self) -> None:
        """Load local conversational/intent models before live microphone capture."""
        if self.simulate or self.no_ai:
            return
        candidates: list[Any] = list(self.ai_backends.values())
        if self.conversation_coordinator and self.conversation_coordinator.semantic_intent_resolver:
            semantic_backend = self.conversation_coordinator.semantic_intent_resolver.backend
            if semantic_backend is not None:
                candidates.append(semantic_backend)

        seen: set[int] = set()
        for backend in candidates:
            if id(backend) in seen or not hasattr(backend, "warmup"):
                continue
            seen.add(id(backend))
            model = str(getattr(backend, "model", backend.__class__.__name__))
            try:
                warmed = bool(backend.warmup())
                logger.info("AI prewarm %s for %s", "completed" if warmed else "not available", model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AI prewarm failed for %s: %s", model, exc)

    def _runtime_context_snapshot(self) -> dict[str, Any]:
        """Return bounded physical state for trusted/local AI context."""
        camera_active = False
        if self.vision_backend is not None:
            try:
                camera_active = self.vision_backend.health().status == ServiceStatus.HEALTHY
            except Exception:  # noqa: BLE001
                camera_active = False

        stable = self.vision_debouncer.latest_stable
        face_detection_verified = bool(
            camera_active
            and self.vision_backend is not None
            and getattr(self.vision_backend, "provides_face_confidence", False)
        )
        face_display_active = self.face_controller.__class__.__name__ == "TkinterFaceController"
        microphone_active = False
        speech_output_active = False
        if self.audio_in is not None:
            try:
                microphone_active = self.audio_in.health().status in {
                    ServiceStatus.HEALTHY,
                    ServiceStatus.DEGRADED,
                }
            except Exception:  # noqa: BLE001
                microphone_active = False
        if self.audio_out is not None:
            try:
                speech_output_active = self.audio_out.health().status in {
                    ServiceStatus.HEALTHY,
                    ServiceStatus.DEGRADED,
                }
            except Exception:  # noqa: BLE001
                speech_output_active = False
        return {
            "microphone_active": microphone_active,
            "speech_output_active": speech_output_active,
            "camera_active": camera_active,
            "face_display_active": face_display_active,
            "presence_detected": bool(camera_active and stable.present),
            "faces_count": stable.faces_count if camera_active and stable.present else 0,
            "face_detection_verified": face_detection_verified,
            "visual_capability": (
                "face_detection_with_confidence"
                if face_detection_verified
                else "experimental_presence_only"
            ),
        }

    def _on_voice_ended_event(self, event: Any) -> None:
        """Mark end-of-user-speech for measured TTFAR on the next audible response."""
        del event
        self._last_voice_ended_monotonic = time.monotonic()

    def _on_speech_started_event(self, event: Any) -> None:
        """Record TTFAR when the first playable PCM buffer is submitted."""
        del event
        if self._last_voice_ended_monotonic is None:
            return
        latency_ms = (time.monotonic() - self._last_voice_ended_monotonic) * 1000.0
        self.metrics.record_ttfar(latency_ms)
        self._last_voice_ended_monotonic = None

    def _run_stt_reprompt(self, message: str) -> None:
        """Speak deterministic STT reprompt without invoking the LLM."""
        try:
            if self.audio_coordinator:
                self.state_manager.transition_to(AssistantState.PROCESSING, reason="stt_reprompt")
                self.audio_coordinator.speak(message, voice_id=self.config.speech.tts_voice)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not speak STT reprompt: %s", exc)
        finally:
            if self.audio_coordinator:
                self.audio_coordinator.turn_gate.stop_processing()
            with self._interaction_lock:
                self._is_processing_interaction = False
            self.state_manager.transition_to(AssistantState.IDLE, reason="stt_reprompt_complete")
            self.face_controller.set_state(AssistantState.IDLE)

    def _on_transcript_event(self, event: Any) -> None:
        """Handle one STT transcript exactly once with single-flight serialization."""
        event_id = str(getattr(event, "event_id", "") or "")
        if event_id:
            with self._interaction_lock:
                if event_id in self._processed_transcript_event_ids:
                    logger.debug("Ignoring duplicate transcript event %s", event_id)
                    return
                self._processed_transcript_event_ids.add(event_id)
                if len(self._processed_transcript_event_ids) > 256:
                    self._processed_transcript_event_ids.clear()
                    self._processed_transcript_event_ids.add(event_id)

        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else {}
        text = str(payload.get("text", "")).strip()
        trace_id = str(payload.get("utterance_id", "")).strip() or None
        latency_raw = payload.get("latency_ms")
        latency_ms = float(latency_raw) if isinstance(latency_raw, (int, float)) else 0.0
        confidence_raw = payload.get("confidence")
        confidence = (
            float(confidence_raw)
            if isinstance(confidence_raw, (int, float))
            else None
        )

        assessment = self.stt_quality_evaluator.evaluate(text, confidence=confidence)
        if assessment.should_drop_silently:
            self.metrics.record_utterance(success=False, latency_ms=latency_ms)
            logger.info(
                "Dropping probable STT noise text=%r confidence=%s reason=%s",
                text,
                "unknown" if confidence is None else f"{confidence:.3f}",
                assessment.reprompt_reason,
            )
            return
        if assessment.should_reprompt:
            self.metrics.record_utterance(success=False, latency_ms=latency_ms)
            print(f"\n[stt] Reprompt required ({assessment.reprompt_reason})")
            if self.audio_coordinator:
                with self._interaction_lock:
                    if self._is_processing_interaction:
                        return
                    self._is_processing_interaction = True
                self.audio_coordinator.turn_gate.start_processing()
                self.audio_coordinator.collector.reset()
                threading.Thread(
                    target=self._run_stt_reprompt,
                    args=(self.stt_quality_evaluator.DEFAULT_REPROMPT_MESSAGE,),
                    daemon=True,
                ).start()
            return

        self.metrics.record_utterance(success=True, latency_ms=latency_ms)
        print(f"\n[stt] Transcript ready (len={len(text)}, latency={latency_ms:.1f}ms)")

        with self._interaction_lock:
            if self._is_processing_interaction:
                logger.info("Ignoring overlapping transcript; interaction currently active")
                return
            self._is_processing_interaction = True

        if self.audio_coordinator:
            self.audio_coordinator.turn_gate.start_processing()
            self.audio_coordinator.collector.reset()

        threading.Thread(
            target=self._process_conversation,
            args=(text, trace_id),
            daemon=True,
        ).start()

    def _on_speech_finished_event(self, event: Any) -> None:
        """Record measured TTS synthesis latency when the audio layer reports it."""
        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else {}
        latency = payload.get("latency_ms")
        if isinstance(latency, (int, float)) and latency >= 0:
            self.metrics.record_tts_call(latency_ms=float(latency))

    def _on_presence_transition_event(self, event: Any) -> None:
        """Count stable presence transitions emitted by InteractionCoordinator."""
        del event
        self.metrics.record_presence_transition()

    def _on_reminder_due_event(self, event: Any) -> None:
        """Queue a due reminder; never perform TTS inside the scheduler thread."""
        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else {}
        reminder_id = str(payload.get("reminder_id", "")).strip()
        content = str(payload.get("content", "")).strip()
        due_at = str(payload.get("due_at", "")).strip()
        if not content:
            return
        print(f"\n[reminder] {content}")
        if self.audio_coordinator is not None:
            self._pending_reminder_announcements.put(
                {"reminder_id": reminder_id, "content": content, "due_at": due_at}
            )

    def _try_start_pending_reminder_announcement(self) -> None:
        """Start one queued reminder only when the interaction channel is idle."""
        if self.audio_coordinator is None or self._pending_reminder_announcements.empty():
            return
        if self.state_manager.current_state not in {AssistantState.IDLE, AssistantState.ATTENTION}:
            return
        with self._interaction_lock:
            if self._is_processing_interaction:
                return
            try:
                payload = self._pending_reminder_announcements.get_nowait()
            except queue.Empty:
                return
            self._is_processing_interaction = True

        self.audio_coordinator.turn_gate.start_processing()
        self.audio_coordinator.collector.reset()
        threading.Thread(
            target=self._announce_reminder,
            args=(payload,),
            name="ailen-reminder-tts",
            daemon=True,
        ).start()

    def _announce_reminder(self, payload: dict[str, str]) -> None:
        """Speak one reminder with half-duplex protection, then release the turn."""
        content = payload.get("content", "").strip()
        try:
            if self.audio_coordinator is not None and content:
                self.audio_coordinator.speak(
                    f"Recordatorio: {content}",
                    voice_id=self.config.speech.tts_voice,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not announce reminder: %s", exc)
        finally:
            if self.audio_coordinator is not None:
                self.audio_coordinator.turn_gate.stop_processing()
            with self._interaction_lock:
                self._is_processing_interaction = False

    def _process_conversation(self, text: str, trace_id: str | None = None) -> None:
        """Process conversational turn from transcript to AI response and vocal speech."""
        try:
            if not self.conversation_coordinator:
                logger.warning("No conversation coordinator configured to handle input")
                return

            try:
                self.state_manager.transition_to(AssistantState.PROCESSING, reason="ai_processing")
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not transition to PROCESSING: %s", exc)
            self.face_controller.set_state(AssistantState.PROCESSING)

            print(f"[router] Routing prompt for '{self.config.identity.display_name}'...")
            input_kwargs: dict[str, Any] = {"session_id": self._conversation_session_id}
            if trace_id is not None:
                input_kwargs["trace_id"] = trace_id
            input_kwargs["input_modality"] = "voice"
            resp, _plan = self.conversation_coordinator.handle_user_input(text, **input_kwargs)

            in_tok = resp.usage.input_tokens if resp.usage else None
            out_tok = resp.usage.output_tokens if resp.usage else None
            self.metrics.record_ai_call(
                latency_ms=resp.latency_ms,
                in_tokens=in_tok,
                out_tokens=out_tok,
                prompt_eval_ms=resp.usage.prompt_eval_ms if resp.usage else None,
                generation_ms=resp.usage.generation_ms if resp.usage else None,
                load_ms=resp.usage.load_ms if resp.usage else None,
            )

            print(
                f"[ai] Response ready provider={resp.provider} model={resp.model} "
                f"latency={resp.latency_ms:.1f}ms len={len(resp.text)}"
            )

        except Exception as exc:  # noqa: BLE001
            logger.error("Error processing conversation turn: %s", exc)
        finally:
            if self.audio_coordinator:
                self.audio_coordinator.turn_gate.stop_processing()

            with self._interaction_lock:
                self._is_processing_interaction = False

            # Return to ATTENTION if presence remains, otherwise IDLE. Keep Core
            # state and visual state aligned after AI/TTS completes.
            final_state = AssistantState.ATTENTION if self.vision_debouncer.stable_presence else AssistantState.IDLE
            try:
                self.state_manager.transition_to(final_state, reason="conversation_complete")
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not transition after conversation: %s", exc)
            self.face_controller.set_state(final_state)

    def _vision_loop(self) -> None:
        """Background loop reading camera presence observations and updating gaze/social engine."""
        last_observation_timestamp: str | None = None
        last_report_monotonic = 0.0
        last_raw_presence: bool | None = None
        last_stable_presence: bool | None = None
        last_health_status: ServiceStatus | None = None
        while self._is_running and self.vision_backend:
            try:
                obs = self.vision_backend.get_latest_presence()
                health = self.vision_backend.health()
                self.metrics.record_vision_poll()
                is_new_frame = bool(
                    health.stream_has_frames
                    and obs.timestamp != last_observation_timestamp
                )
                if is_new_frame:
                    last_observation_timestamp = obs.timestamp
                    self.metrics.record_vision_frame()

                if self.interaction_coordinator and is_new_frame:
                    self.interaction_coordinator.handle_raw_presence_observation(
                        obs
                    )
                    self._vision_observations_delivered += 1
                elif (
                    self.interaction_coordinator
                    and health.status != ServiceStatus.HEALTHY
                ):
                    self.interaction_coordinator.handle_raw_presence_observation(
                        PresenceObservation(present=False)
                    )
                    self._vision_observations_delivered += 1

                if is_new_frame and obs.present and self.face_controller:
                    self.face_controller.set_gaze(
                        obs.primary_x_normalized or 0.0,
                        obs.primary_y_normalized or 0.0,
                    )

                stable = self.vision_debouncer.latest_stable
                now = time.monotonic()
                report_due = now - last_report_monotonic >= 5.0
                state_changed = (
                    obs.present != last_raw_presence
                    or stable.present != last_stable_presence
                    or health.status != last_health_status
                )
                if report_due or state_changed:
                    frame_age_ms = (
                        None
                        if health.last_valid_frame_age_seconds is None
                        else health.last_valid_frame_age_seconds * 1000.0
                    )
                    logger.info(
                        "vision_timing timestamp_monotonic=%.6f health=%s "
                        "stream_has_frames=%s capture_thread_alive=%s valid_frames=%d "
                        "read_failures=%d last_valid_frame_age_ms=%s "
                        "yunet_inference_ms=%s raw_present=%s raw_faces=%d "
                        "raw_confidence=%s stable_present=%s stable_faces=%d "
                        "core_present=%s observations_delivered=%d new_frame=%s",
                        now,
                        health.status.value,
                        health.stream_has_frames,
                        health.capture_thread_alive,
                        health.frames_processed,
                        health.frame_read_failures,
                        "unknown" if frame_age_ms is None else f"{frame_age_ms:.1f}",
                        (
                            "unknown"
                            if health.last_inference_ms is None
                            else f"{health.last_inference_ms:.1f}"
                        ),
                        obs.present,
                        obs.faces_count,
                        "unknown" if obs.confidence is None else f"{obs.confidence:.3f}",
                        stable.present,
                        stable.faces_count,
                        (
                            self.interaction_coordinator.current_presence
                            if self.interaction_coordinator
                            else False
                        ),
                        self._vision_observations_delivered,
                        is_new_frame,
                    )
                    last_report_monotonic = now
                    last_raw_presence = obs.present
                    last_stable_presence = stable.present
                    last_health_status = health.status

                time.sleep(0.05)  # 20 Hz poll
            except Exception as exc:  # noqa: BLE001
                logger.debug("Vision loop exception: %s", exc)
                time.sleep(0.1)

    def print_status_table(self) -> None:
        """Render standard lab component status table."""
        print("==================================================================")
        mode_label = "AILEN LAB COMPONENT STATUS (SIMULATION MODE)" if self.simulate else "AILEN LAB COMPONENT STATUS"
        print(f"{mode_label:^66}")
        print("==================================================================")
        print(f"{'COMPONENT':<14} {'BACKEND':<26} {'STATE':<14} {'DETAIL'}")
        print("------------------------------------------------------------------")
        for s in self.component_statuses:
            print(f"{s.name:<14} {s.backend:<26} {s.state:<14} {s.detail}")
        print("==================================================================")

        if self.simulate:
            print("STATUS: AILEN LAB SIMULATED (Running with synthetic test backends)")
        else:
            active = [s for s in self.component_statuses if s.state != "DISABLED"]
            all_ready = bool(active) and all(s.state == "READY" for s in active)
            if all_ready:
                print("STATUS: AILEN LAB READY (All enabled live components are ready)")
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
        """Start the lab session, verify live startup, and terminate cleanly."""
        self.inspect_and_plan()
        self.init_components()

        if self.dry_run:
            self.print_status_table()
            print("Dry-run complete: components resolved without opening the live session.")
            return 0

        self._setup_signal_handlers()
        self._is_running = True
        start_time = time.time()

        # Open a real face window when the selected controller supports it.
        # Tk events are then pumped by the existing main runtime loop.
        if hasattr(self.face_controller, "start_window"):
            try:
                self.face_controller.start_window(interactive_keys=False)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not open face window: %s", exc)
                for status in self.component_statuses:
                    if status.name == "Face":
                        status.state = "DEGRADED"
                        status.detail = f"Face window failed: {exc}"

        # 1. Apply explicit camera-management state before opening its video stream.
        if self.camera_control is not None:
            try:
                camera_status = self.camera_control.set_daynight_mode(
                    self.config.vision.camera_startup_daynight_mode
                )
                logger.info("Camera day/night mode applied: %s", camera_status.daynight_mode)
                for component in self.component_statuses:
                    if component.name == "CameraControl":
                        component.state = "READY"
                        component.detail = f"Management verified; day/night={camera_status.daynight_mode}"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Camera day/night control failed: %s", type(exc).__name__)
                for component in self.component_statuses:
                    if component.name == "CameraControl":
                        component.state = "DEGRADED"
                        component.detail = f"Day/night control failed: {type(exc).__name__}"

        # 2. Start Vision Backend & Thread, then turn startup failures into
        # explicit component state instead of leaving an optimistic READY row.
        if self.vision_backend:
            try:
                self.vision_backend.start()
                vision_health = self.vision_backend.health()
                if not self.simulate:
                    for status in self.component_statuses:
                        if status.name == "Vision":
                            status.state = (
                                "READY"
                                if vision_health.status == ServiceStatus.HEALTHY
                                else "DEGRADED"
                            )
                            status.detail = vision_health.detail
                self._vision_thread = threading.Thread(target=self._vision_loop, daemon=True)
                self._vision_thread.start()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not start vision backend: %s", exc)
                for status in self.component_statuses:
                    if status.name == "Vision":
                        status.state = "UNAVAILABLE"
                        status.detail = f"Vision startup failed: {exc}"

        # 2. Prewarm local AI models and optional TTS before microphone capture.
        # This moves cold model-load cost to startup instead of the first spoken turn.
        self._prewarm_ai_models()

        # 3. Prewarm optional TTS runtime before microphone capture starts. This
        # avoids charging Piper model-load time to the first user response. The
        # Python API is the only canonical Piper synthesis route.
        if not self.simulate and self.tts_backend and hasattr(self.tts_backend, "warmup"):
            try:
                warmed = bool(self.tts_backend.warmup())  # type: ignore[attr-defined]
                logger.info("TTS prewarm %s", "completed" if warmed else "not available")
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTS prewarm failed: %s", exc)

        # 4. Start Audio Coordinator only when the complete speech chain was
        # wired. Missing STT/TTS never silently activates fake defaults.
        if self.audio_coordinator:
            try:
                self.audio_coordinator.start()
                if not self.simulate and self.audio_in:
                    audio_health = self.audio_in.health()
                    if audio_health.status in {ServiceStatus.UNHEALTHY, ServiceStatus.DISABLED}:
                        for status in self.component_statuses:
                            if status.name == "Audio":
                                status.state = "UNAVAILABLE"
                                status.detail = audio_health.detail
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not start audio coordinator: %s", exc)
                for status in self.component_statuses:
                    if status.name == "Audio":
                        status.state = "UNAVAILABLE"
                        status.detail = f"Audio startup failed: {exc}"

        # 5. Start the persistent reminder scheduler only after event handlers
        # and audio coordination are ready. Dry-run never starts background work.
        if self.reminder_service is not None:
            try:
                self.reminder_service.start()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not start reminder scheduler: %s", exc)

        self.print_status_table()
        print("\nAILEN Lab Mode running. Speak or interact. Press Ctrl+C to terminate cleanly.\n")

        # 3. Main Event / Face Animation Loop
        try:
            while self._is_running and not self._shutdown_requested:
                if self.duration and (time.time() - start_time) >= self.duration:
                    logger.info("Duration limit reached (%s s). Stopping...", self.duration)
                    break

                self._try_start_pending_reminder_announcement()

                if self.face_controller and hasattr(self.face_controller, "update"):
                    try:
                        self.face_controller.update()
                        self.metrics.record_face_frame()
                    except Exception:  # noqa: BLE001, S110
                        pass

                time.sleep(0.016)  # ~60 FPS
        except KeyboardInterrupt:
            print("\nCtrl+C detected.")
        finally:
            self.stop()

        print("AILEN Lab shutdown cleanly completed.")
        return 0

    def stop(self) -> None:
        """Stop all managed components safely and write session metrics log."""
        if not self._is_running:
            return
        self._is_running = False

        # Let an in-flight conversation/reprompt/reminder finish before tearing
        # down native audio/TTS resources. This avoids process aborts when a
        # duration limit or signal lands in the middle of a spoken turn.
        interaction_deadline = time.monotonic() + 8.0
        while True:
            with self._interaction_lock:
                interaction_active = self._is_processing_interaction
            if not interaction_active or time.monotonic() >= interaction_deadline:
                break
            time.sleep(0.05)
        if interaction_active:
            logger.warning(
                "Shutdown grace expired with an interaction still active; continuing teardown"
            )

        self.metrics.finalize()

        # Stop scheduler before audio/database teardown so no new due events are
        # emitted while the runtime is shutting down.
        if self.reminder_service is not None:
            try:
                self.reminder_service.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error stopping reminder scheduler: %s", exc)
            self.reminder_service = None

        # Stop Vision
        if self.vision_backend:
            try:
                self.vision_backend.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error stopping vision backend: %s", exc)
            self.vision_backend = None

        if self._vision_thread and self._vision_thread.is_alive():
            self._vision_thread.join(timeout=0.5)
            self._vision_thread = None

        # Stop Audio
        if self.audio_coordinator:
            try:
                self.audio_coordinator.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error stopping audio coordinator: %s", exc)
            self.audio_coordinator = None

        # Close Face Window
        if self.face_controller:
            try:
                if hasattr(self.face_controller, "close"):
                    self.face_controller.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing face controller: %s", exc)

        # Close persisted conversation session after all turn-producing components stop.
        if self.memory_repo and self._conversation_session_id:
            try:
                self.memory_repo.end_session(self._conversation_session_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not close conversation session: %s", exc)
            self._conversation_session_id = None

        # Stop AILEN-owned Managed Runtime (never touch external runtimes)
        if self.managed_runtime and self.managed_runtime.owned_by_ailen:
            try:
                self.managed_runtime.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error stopping managed llama.cpp runtime: %s", exc)

        # Export session metrics log
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / f"session_{int(time.time())}.json"
            log_file.write_text(json.dumps(self.metrics.to_dict(), indent=2), encoding="utf-8")
            logger.info("Session metrics saved to %s", log_file)
        except OSError as exc:
            logger.warning("Could not save session log: %s", exc)

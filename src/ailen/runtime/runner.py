"""Dedicated non-invasive runner for AILEN Lab Mode with live hardware and interaction wiring."""

import json
import logging
import os
import queue
import signal
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from types import FrameType
from typing import Any

from ailen.ai.agent_planner import OrchestratorPlanner
from ailen.ai.budget import BudgetPolicy
from ailen.ai.context import AiContextBuilder
from ailen.ai.contracts import AiBackend
from ailen.ai.managed_local_backend import ManagedLocalAiBackend
from ailen.ai.ollama_backend import OllamaNativeBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.residency import ModelResidencyPolicy
from ailen.ai.router import RuleBasedRouter
from ailen.audio.contracts import (
    AudioInputBackend,
    AudioOutputBackend,
    SttBackend,
    Transcript,
    TranscriptAlternative,
    TtsBackend,
)
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.stt_quality import SttQualityEvaluator
from ailen.core.agent_loop import AgentBudget, AgentLoop
from ailen.core.agent_service import AgentService, AgentTaskStatus, AgentTaskView
from ailen.core.agent_trigger import parse_agent_command
from ailen.core.capabilities import CapabilityDescriptor, CapabilityProvider, CapabilityRegistry
from ailen.core.config import AILENConfig
from ailen.core.confirmation import ConfirmationService, ConfirmationState
from ailen.core.conversation import ConversationCoordinator
from ailen.core.coordinator import InteractionCoordinator
from ailen.core.events import EventBus
from ailen.core.personality import PersonalityService, PersonalityTraits
from ailen.core.social import SocialEngine
from ailen.core.state import StateManager
from ailen.domain.enums import (
    AssistantState,
    EventType,
    InferenceProfile,
    PrivacyLevel,
    ServiceStatus,
    SocialMode,
)
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
from ailen.provisioning.activation import (
    LocalAiSelectionError,
    LocalAiSelectionStore,
)
from ailen.runtime.contracts import ExternalRuntimeDescriptor, RuntimeStatus, RuntimeType
from ailen.runtime.factory import ComponentStatus, LabComponentFactory
from ailen.runtime.inventory import RuntimeModelInventory
from ailen.runtime.managed import ManagedLlamaRuntime
from ailen.runtime.manager import LocalRuntimeManager
from ailen.runtime.metrics import LabSessionMetrics
from ailen.tools.builtin import (
    CameraTool,
    ClockTool,
    DesktopMusicService,
    FaceExpressionTool,
    FilesTool,
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
from ailen.tools.contracts import AutonomyLevel, ToolContext, autonomy_level_of
from ailen.tools.executor import ToolExecutor
from ailen.tools.registry import ToolRegistry
from ailen.tools.semantic_intent import SemanticToolIntentResolver
from ailen.vision.contracts import PresenceObservation, VisionBackend
from ailen.vision.control import CameraControl, create_camera_control
from ailen.vision.debouncer import VisionDebouncer

logger = logging.getLogger("ailen.runtime.runner")
_AGENT_CONFIRMATION_VOICE_WINDOW_SECONDS = 60.0


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
        local_selection_store: LocalAiSelectionStore | None = None,
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
        self.metrics = LabSessionMetrics(
            session_id=self._session_id,
            execution_mode=(
                "dry_run"
                if dry_run
                else "simulation"
                if simulate
                else "no_backends"
                if no_camera and no_audio and no_ai
                else "real"
            ),
        )

        self._is_running = False
        self._shutdown_requested = False
        self._interaction_lock = threading.Lock()
        self._is_processing_interaction = False
        self._processed_transcript_event_ids: set[str] = set()
        self._last_voice_ended_monotonic: float | None = None
        self.stt_quality_evaluator = SttQualityEvaluator(
            noise_confidence_max=config.speech.stt_noise_confidence_max,
            conversation_min_confidence=config.speech.stt_conversation_min_confidence,
            action_min_confidence=config.speech.voice_action_min_confidence,
        )

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
        self.ai_orchestrator: AiOrchestrator | None = None

        # Coordinators & Tools
        self.social_engine: SocialEngine | None = None
        self.interaction_coordinator: InteractionCoordinator | None = None
        self.audio_coordinator: AudioInteractionCoordinator | None = None
        self.tool_registry: ToolRegistry | None = None
        self.capability_registry: CapabilityRegistry | None = None
        self.tool_executor: ToolExecutor | None = None
        self.agent_service: AgentService | None = None
        self.conversation_coordinator: ConversationCoordinator | None = None
        self.personality_service: PersonalityService | None = None
        self.reminder_service: ReminderService | None = None
        self._pending_reminder_announcements: queue.Queue[dict[str, str]] = queue.Queue()
        self._pending_agent_confirmation_announcements: queue.Queue[tuple[str, str]] = queue.Queue()
        self._queued_agent_confirmation_ids: set[str] = set()
        self._agent_announcement_lock = threading.Lock()
        self._announced_agent_confirmations: dict[str, float] = {}
        self._agent_announcement_thread: threading.Thread | None = None
        self.managed_runtime = managed_runtime
        self.local_selection_store = local_selection_store or LocalAiSelectionStore(
            Path(config.node.data_dir) / "provisioning" / "local-ai-selection.json"
        )

        self._vision_thread: threading.Thread | None = None
        self._vision_observations_delivered = 0
        self._memory_pressure_thread: threading.Thread | None = None
        self._memory_pressure_stop = threading.Event()

    def inspect_and_plan(self) -> tuple[HardwareCapabilityReport, ModelPlan]:
        """Detect hardware capabilities, discover runtimes, and compute optimal model plan."""
        store = ModelStore()
        detector = HardwareDetector()
        self.hardware_report = detector.detect(str(store.base_dir))
        rec = detector.recommend_profile(self.hardware_report)
        self.detected_profile = rec.profile

        # A disabled local provider is a hard boundary: do not even probe local
        # inference endpoints. Detection can wake socket-activated runtimes and
        # used to make ``ai.local.enabled=false`` observably false.
        if self.config.ai.local.enabled:
            runtime_mgr = LocalRuntimeManager()
            self.runtime_descriptors = runtime_mgr.detect_available_runtimes()
        else:
            self.runtime_descriptors = []

        self.inference_recommendation = recommend_inference_profile(
            self.hardware_report,
            device_profile=rec.profile,
        )
        catalog = ModelCatalog()
        planner = ModelPlanner(catalog=catalog)
        diagnostic_plan = planner.plan(
            self.hardware_report,
            profile=rec.profile,
            purpose=ModelPurpose.BALANCED,
            desired_context=self.inference_recommendation.recommended_context,
            inference_profile=self.inference_recommendation.profile,
        )
        self.model_plan = diagnostic_plan
        if self.config.ai.local.enabled and not self.config.ai.local.model.strip():
            try:
                selection = self.local_selection_store.load(
                    self.hardware_report,
                    catalog=catalog,
                    model_store=store,
                )
                if selection is not None:
                    self.model_plan = selection.to_model_plan(catalog)
            except LocalAiSelectionError as exc:
                # Fail closed.  The diagnostic candidate remains visible, but
                # Factory will not activate it because it is not qualified.
                logger.warning("Ignoring invalid local AI activation: %s", exc)
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

        # 6. AI Backends. A verified planned GGUF may be exposed through an
        # AILEN-owned llama.cpp adapter that loads only on first inference.
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
            and self.config.ai.local.enabled
            and "local" not in self.ai_backends
            and self.model_plan
            and self.model_plan.is_viable
            and self.model_plan.selected_model_id
            and self.model_plan.model_descriptor
            and self.model_plan.model_descriptor.qualification_status.value
            == "qualified"
            and self.model_plan.runtime == "llama.cpp"
        ):
            store = ModelStore()
            model_id = self.model_plan.selected_model_id
            descriptor = self.model_plan.model_descriptor
            if store.exists(model_id) and store.verify(model_id, descriptor.sha256):
                runtime = self.managed_runtime or ManagedLlamaRuntime()
                self.managed_runtime = runtime
                self.ai_backends["local"] = ManagedLocalAiBackend(
                    runtime=runtime,
                    model_path=store.get_model_path(model_id),
                    model_alias=model_id,
                    context_size=self.model_plan.context_size,
                    gpu_layers=self.model_plan.gpu_layers,
                    timeout_seconds=self.config.ai.local.timeout_seconds,
                )
                backend_names = ", ".join(sorted(self.ai_backends))
                ai_st = ComponentStatus(
                    name="AI Inference",
                    backend=backend_names,
                    state="READY",
                    detail=(
                        f"Available backends: {backend_names}. Verified llama.cpp model "
                        f"'{model_id}' loads on first local route."
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
        self.audio_coordinator = factory.build_audio_coordinator(
            audio_input=self.audio_in,
            audio_output=self.audio_out,
            stt=self.stt_backend,
            tts=self.tts_backend,
            state_manager=self.state_manager,
            face_controller=self.face_controller,
            event_bus=self.event_bus,
            auto_reset_after_stt=not bool(self.ai_backends),
        )

        # 10. Wire Tool Registry & Controlled Executor. Reminders persist in
        # SQLite; when memory is unavailable the tool fails closed rather than
        # degrading into a volatile timer.
        if self.memory_repo is not None:
            self.reminder_service = ReminderService(
                repository=self.memory_repo,
                event_bus=self.event_bus,
            )
        tools: list[Any] = [
            CameraTool(self.camera_control),
            ClockTool(),
            FaceExpressionTool(self.face_controller),
            TimerTool(),
            RemindersTool(repository=self.memory_repo),
            VolumeTool(),
            MusicTool(service=DesktopMusicService()),
            NotesTool(repository=self.memory_repo),
            SystemStatusTool(),
            WebSearchTool(
                provider=create_web_search_provider(
                    self.config.network.web_search_provider,
                    region=self.config.network.web_search_region,
                )
            ),
            WebFetchTool(),
        ]
        if self.config.agent.file_roots:
            # N2 (ADR-014): inert unless agent.max_autonomy_level >= 2 as well.
            tools.append(FilesTool(self.config.agent.file_roots))
        self.tool_registry = ToolRegistry(tools)
        self.confirmation_service = ConfirmationService()
        self.tool_executor = ToolExecutor(
            registry=self.tool_registry,
            event_bus=self.event_bus,
            repository=self.memory_repo,
            confirmation_service=self.confirmation_service,
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

        router = RuleBasedRouter()
        orchestrator = AiOrchestrator(
            backends=self.ai_backends,
            router=router,
            repository=self.memory_repo,
            event_bus=self.event_bus,
        )
        self.ai_orchestrator = orchestrator

        # Default N1 does not allocate an agent service or worker. Raising the
        # autonomy cap or configuring roots is an explicit administrator opt-in.
        if self._agent_enabled() and self.tool_registry is not None and self.tool_executor is not None:
            registry = self.tool_registry
            executor = self.tool_executor
            self.agent_service = AgentService(
                loop_factory=lambda cancel_event: AgentLoop(
                    planner=OrchestratorPlanner(
                        orchestrator=orchestrator,
                        registry=registry,
                        tool_filter=self._agent_tool_filter,
                        router=router,
                        max_output_tokens=min(self.config.ai.max_tokens, 256),
                        timeout=self.config.ai.timeout_seconds,
                    ),
                    executor=executor,
                    budget=AgentBudget(),
                    context_factory=self._agent_tool_context,
                    cancel_event=cancel_event,
                ),
                confirmations=self.confirmation_service,
                on_event=self._on_agent_task_event,
            )

        # 11. Wire Conversation Coordinator. Named-remote/LAN policies are the same
        # audited policies used by normal Core, including budget enforcement.
        if self.ai_backends:
            context_builder = AiContextBuilder(
                repository=self.memory_repo,
                request_timeout_seconds=self.config.ai.timeout_seconds,
                max_recent_messages=self.config.ai.context_recent_messages,
                max_char_budget=self.config.ai.context_char_budget,
                max_output_tokens=min(self.config.ai.max_tokens, 128),
                temperature=self.config.ai.temperature,
            )
            remote_budget_policies = {
                f"remote:{provider_id}": BudgetPolicy(
                    repository=self.memory_repo,
                    daily_budget_usd=provider.daily_budget_usd,
                    monthly_budget_usd=provider.monthly_budget_usd,
                    provider=f"remote:{provider_id}",
                )
                for provider_id, provider in self.config.ai.remote.providers.items()
                if provider.enabled
            }
            backend_priorities = {
                "lan_brain": self.config.ai.lan.priority,
                "local": self.config.ai.local.priority,
                **{
                    f"remote:{provider_id}": provider.priority
                    for provider_id, provider in self.config.ai.remote.providers.items()
                    if provider.enabled
                },
            }
            backend_timeouts = {
                f"remote:{provider_id}": provider.timeout_seconds
                for provider_id, provider in self.config.ai.remote.providers.items()
                if provider.enabled
            }
            backend_realtime = {
                f"remote:{provider_id}": provider.voice_realtime_eligible
                for provider_id, provider in self.config.ai.remote.providers.items()
                if provider.enabled
            }
            semantic_intent_backend = self._build_semantic_intent_backend()
            semantic_intent_resolver = (
                SemanticToolIntentResolver(
                    backend=semantic_intent_backend,
                    registry=self.tool_registry,
                    repository=self.memory_repo,
                    request_timeout_seconds=self.config.ai.local.intent_timeout_seconds,
                    allow_network_tools=self.config.network.outbound_web_enabled,
                )
                if semantic_intent_backend is not None
                else None
            )
            # Core keeps conversation/memory PRIVATE. Remote AI receives only
            # the current turn when explicit sanitized-external mode is enabled.
            conversation_privacy = PrivacyLevel.PRIVATE
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
                privacy_level=conversation_privacy,
                identity_name=self.config.identity.display_name,
                tts_voice_id=self.config.speech.tts_voice,
                internet_available=(
                    self.config.network.outbound_web_enabled
                    or any(name.startswith("remote:") for name in self.ai_backends)
                ),
                tool_network_allowed=self.config.network.outbound_web_enabled,
                tool_max_autonomy=AutonomyLevel(min(max(self.config.agent.max_autonomy_level, 1), 3)),
                external_allowed=(
                    self.config.ai.allow_remote and self.config.ai.remote.enabled
                ),
                allow_sanitized_external_prompts=self.config.ai.allow_sanitized_external_prompts,
                lan_brain_trusted=self.config.ai.lan.trusted,
                preferred_backend=self.config.ai.provider,
                backend_priorities=backend_priorities,
                backend_timeouts=backend_timeouts,
                backend_realtime_eligibility=backend_realtime,
                backend_budget_policies=remote_budget_policies,
                runtime_context_provider=self._runtime_context_snapshot,
                repository=self.memory_repo,
                personality_service=self.personality_service,
                persona_description=self.config.personality.description,
                voice_action_min_confidence=self.config.speech.voice_action_min_confidence,
                capability_registry=self.capability_registry,
                telemetry_sink=self.metrics.record_turn_stage,
                agent_command_handler=(
                    self._handle_agent_command if self.agent_service is not None else None
                ),
            )

        # 12. Subscribe to lightweight events for single-flight conversation and
        # measured lab telemetry. No PCM or camera frames enter the EventBus.
        self.event_bus.subscribe(EventType.TRANSCRIPT_READY, self._on_transcript_event)
        self.event_bus.subscribe(EventType.VOICE_ENDED, self._on_voice_ended_event)
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self._on_speech_started_event)
        self.event_bus.subscribe(EventType.SPEECH_INTERRUPTED, self._on_speech_interrupted_event)
        self.event_bus.subscribe(EventType.SPEECH_FINISHED, self._on_speech_finished_event)
        self.event_bus.subscribe(
            EventType.SPEECH_SYNTHESIS_DRAINED,
            self._on_speech_synthesis_drained_event,
        )
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
        if not self.config.ai.local.enabled:
            return None

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

    def _agent_enabled(self) -> bool:
        """Whether the administrator explicitly enabled Agent N2/N3 capability."""
        return self.config.agent.max_autonomy_level >= 2 or bool(self.config.agent.file_roots)

    def _agent_social_mode(self) -> SocialMode:
        """Read the live mode, including changes made by Core's interaction coordinator."""
        if self.interaction_coordinator is not None:
            return self.interaction_coordinator.mode
        return self.config.social.default_mode

    def _agent_autonomy(self) -> AutonomyLevel:
        """Return the live autonomy cap; SHOP/PUBLIC always constrain tools to N1."""
        if self._agent_social_mode() in {SocialMode.SHOP, SocialMode.PUBLIC}:
            return AutonomyLevel.N1
        level = self.config.agent.max_autonomy_level
        if isinstance(level, bool) or not isinstance(level, int):
            return AutonomyLevel.N1
        return AutonomyLevel(min(max(level, int(AutonomyLevel.N1)), int(AutonomyLevel.N3)))

    def _agent_tool_filter(self) -> tuple[str, ...]:
        """Expose only tools currently allowed by mode, autonomy and network policy."""
        registry = self.tool_registry
        if registry is None:
            return ()
        mode = self._agent_social_mode()
        autonomy = self._agent_autonomy()
        allowed: list[str] = []
        for tool in registry.list_tools():
            declared_level = autonomy_level_of(tool)
            if declared_level is None or declared_level > autonomy:
                continue
            if mode not in getattr(tool, "allowed_modes", set()):
                continue
            if bool(getattr(tool, "requires_network", False)) and not self.config.network.outbound_web_enabled:
                continue
            allowed.append(tool.name)
        return tuple(allowed)

    def _agent_tool_context(self) -> ToolContext:
        """Build each action context from current Core mode/config, not a startup snapshot."""
        mode = self._agent_social_mode()
        return ToolContext(
            mode=mode,
            privacy_level=PrivacyLevel.PRIVATE,
            internet_available=(
                self.config.network.outbound_web_enabled
                or any(name.startswith("remote:") for name in self.ai_backends)
            ),
            network_access_allowed=self.config.network.outbound_web_enabled,
            max_autonomy=self._agent_autonomy(),
        )

    def _handle_agent_command(self, transcript: Transcript, text: str) -> str | None:
        """Execute an explicit, bounded voice control for the supervised agent."""
        command = parse_agent_command(text)
        service = self.agent_service
        if command is None or service is None:
            return None
        mode = self._agent_social_mode()
        if mode in {SocialMode.SHOP, SocialMode.PUBLIC} and command.kind in {
            "submit", "confirm", "deny"
        }:
            return "En este modo, las acciones del agente se gestionan desde el panel."
        if command.kind == "submit":
            if (
                transcript.truncated
                or transcript.confidence is None
                or transcript.confidence < self.config.speech.voice_action_min_confidence
            ):
                return "No escuché la tarea completa con suficiente claridad. ¿Podés repetirla?"
            assert command.task is not None
            handle = service.submit(command.task, mode=mode)
            if handle.status is AgentTaskStatus.REJECTED:
                return handle.reason or "No pude iniciar esa tarea del agente."
            return "Entendido, trabajando en eso."

        if command.kind == "cancel":
            active = next(
                (
                    task for task in service.recent()
                    if task.status in {
                        AgentTaskStatus.RUNNING, AgentTaskStatus.AWAITING_CONFIRMATION
                    }
                ),
                None,
            )
            if active is None:
                return "No hay una tarea del agente en curso."
            return "Tarea cancelada." if service.cancel(active.id) else "No pude cancelar la tarea."

        now = time.monotonic()
        eligible: list[tuple[Any, AgentTaskView]] = []
        for task in service.recent():
            if task.status is not AgentTaskStatus.AWAITING_CONFIRMATION or not task.confirmation_id:
                continue
            announced_at = self._announced_agent_confirmations.get(task.confirmation_id)
            if (
                announced_at is None
                or now - announced_at > _AGENT_CONFIRMATION_VOICE_WINDOW_SECONDS
            ):
                self._announced_agent_confirmations.pop(task.confirmation_id, None)
                continue
            request = self.confirmation_service.status(task.confirmation_id)
            if request is not None and request.state is ConfirmationState.PENDING:
                eligible.append((request.created_at, task))
        eligible.sort(key=lambda pair: pair[0])
        if not eligible:
            return "No hay nada pendiente de confirmar."
        if len(eligible) > 1:
            return "Hay varias acciones pendientes; para evitar confusiones, usá el panel."
        task = eligible[0][1]
        confirmation_id = task.confirmation_id
        if confirmation_id is None:
            return "No hay nada pendiente de confirmar."
        request = self.confirmation_service.status(confirmation_id)
        if request is None or request.state is not ConfirmationState.PENDING:
            self._announced_agent_confirmations.pop(confirmation_id, None)
            return "No hay nada pendiente de confirmar."

        approved = command.kind == "confirm"
        resolved = self.confirmation_service.resolve(
            confirmation_id,
            approved,
            source="voice",
            stt_confidence=transcript.confidence,
            truncated=transcript.truncated,
        )
        if not resolved:
            return (
                f"Necesito tu confirmación para {request.summary}. "
                "Repetí la confirmación con claridad o usá el panel."
            )
        return (
            "Confirmación recibida; sigo con la tarea."
            if approved
            else "Tarea cancelada."
        )

    def _prewarm_ai_models(self) -> None:
        """Load local conversational/intent models before live microphone capture."""
        if self.simulate or self.no_ai:
            return
        on_demand_local = bool(
            self.inference_recommendation
            and self.inference_recommendation.profile == InferenceProfile.FAST
        )
        candidates: list[Any] = []
        for name, backend in self.ai_backends.items():
            if name == "local" and not self.config.ai.local.enabled:
                continue
            if name == "local" and on_demand_local:
                logger.info("FAST memory tier keeps local AI on demand; skipping prewarm")
                continue
            candidates.append(backend)
        if self.conversation_coordinator and self.conversation_coordinator.semantic_intent_resolver:
            semantic_backend = self.conversation_coordinator.semantic_intent_resolver.backend
            if semantic_backend is not None and not on_demand_local:
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

        # Warm the real conversational prefix as well. Loading the model alone
        # still leaves the first live turn paying prompt-evaluation/cache costs.
        local_backend = (
            self.ai_backends.get("local") if self.config.ai.local.enabled else None
        )
        coordinator = self.conversation_coordinator
        if local_backend is not None and coordinator is not None and not on_demand_local:
            try:
                runtime_context = self._runtime_context_snapshot()
                request = coordinator.context_builder.build_request(
                    user_message="Hola.",
                    mode=coordinator.mode,
                    privacy_level=coordinator.privacy_level,
                    identity_name=coordinator.identity_name,
                    destination="local",
                    lan_trusted=coordinator.lan_brain_trusted,
                    metadata={
                        "voice_output": coordinator.audio_coordinator is not None,
                        "input_modality": "voice",
                        "runtime_context": runtime_context,
                        "personality_style": (
                            coordinator.personality_service.prompt_style()
                            if coordinator.personality_service is not None
                            else ""
                        ),
                        "persona_description": coordinator.persona_description,
                        "conversational_expressions": list(
                            coordinator.conversational_expressions
                        ),
                        "capabilities": [],
                    },
                )
                request.max_output_tokens = 1
                started = time.monotonic()
                response = local_backend.generate(request)
                logger.info(
                    "AI conversational-prefix prewarm completed model=%s latency_ms=%.1f finish=%s",
                    getattr(local_backend, "model", local_backend.__class__.__name__),
                    (time.monotonic() - started) * 1000.0,
                    response.finish_reason,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("AI conversational-prefix prewarm failed: %s", exc)

    def _release_local_model_under_pressure(self, available_memory_mb: int) -> bool:
        """Release only the configured local model when the tier floor is crossed."""
        if not self.config.ai.local.enabled or self.inference_recommendation is None:
            return False
        policy = ModelResidencyPolicy(
            inference_profile=self.inference_recommendation.profile,
        )
        if not policy.should_release(available_memory_mb):
            return False
        backend = self.ai_backends.get("local")
        release = getattr(backend, "release_if_idle", None)
        if not callable(release):
            return False
        released = bool(release())
        logger.warning(
            "Local model memory-pressure release requested available_mb=%d floor_mb=%d released=%s",
            available_memory_mb,
            policy.minimum_free_memory_mb,
            released,
        )
        return released

    def _memory_pressure_loop(self) -> None:
        """Observe RAM at low frequency without touching unrelated processes."""
        detector = HardwareDetector()
        while not self._memory_pressure_stop.wait(5.0):
            try:
                available_mb = detector.adapter.detect_ram().available_mb
                self._release_local_model_under_pressure(available_mb)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Memory-pressure observation unavailable: %s", exc)

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
        face_display_active = self.face_controller.is_display_active()
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
        self._last_voice_ended_monotonic = time.monotonic()
        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else {}
        utterance_id = str(payload.get("utterance_id", "") or "").strip()
        if utterance_id:
            self.metrics.record_turn_stage(
                utterance_id,
                "voice_end",
                utterance_id=utterance_id,
                audio_duration_ms=payload.get("duration_ms"),
            )

    def _on_speech_started_event(self, event: Any) -> None:
        """Record TTFAR when the first playable PCM buffer is submitted."""
        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else {}
        turn_id = str(payload.get("turn_id", "") or "").strip()
        if turn_id:
            self.metrics.record_turn_stage(
                turn_id,
                "first_pcm_submit",
                generation_id=payload.get("speech_generation"),
                request_to_pcm_ms=payload.get("request_to_pcm_ms"),
                expression_requested=payload.get("expression_requested"),
            )
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
        alternatives: list[TranscriptAlternative] = []
        raw_alternatives = payload.get("alternatives")
        if isinstance(raw_alternatives, list):
            for raw_alternative in raw_alternatives:
                if not isinstance(raw_alternative, dict):
                    continue
                alternative_text = str(raw_alternative.get("text", "")).strip()
                if not alternative_text:
                    continue
                alternative_confidence_raw = raw_alternative.get("confidence")
                alternative_confidence = (
                    float(alternative_confidence_raw)
                    if isinstance(alternative_confidence_raw, (int, float))
                    else None
                )
                alternatives.append(
                    TranscriptAlternative(
                        text=alternative_text,
                        confidence=alternative_confidence,
                    )
                )
        audio_duration_raw = payload.get("audio_duration_ms")
        audio_duration_ms = (
            float(audio_duration_raw)
            if isinstance(audio_duration_raw, (int, float))
            else 0.0
        )
        transcript = Transcript(
            text=text,
            language=str(payload.get("language", "es") or "es"),
            confidence=confidence,
            latency_ms=latency_ms,
            engine=str(payload.get("engine", "unknown") or "unknown"),
            audio_duration_ms=audio_duration_ms,
            utterance_id=trace_id,
            interrupted=bool(payload.get("interrupted", False)),
            truncated=bool(payload.get("truncated", False)),
            alternatives=tuple(alternatives),
        )

        assessment = self.stt_quality_evaluator.evaluate(
            text,
            confidence=confidence,
            alternatives=transcript.alternatives,
        )
        self.metrics.record_turn_stage(
            trace_id or "unknown",
            "stt_result",
            utterance_id=trace_id,
            engine=transcript.engine,
            confidence=assessment.acoustic_confidence,
            confidence_band=assessment.confidence_band.value,
            audio_duration_ms=transcript.audio_duration_ms,
            interrupted=transcript.interrupted,
            truncated=transcript.truncated,
            duration_ms=latency_ms,
            accepted=not (
                assessment.should_drop_silently or assessment.should_reprompt
            ),
            reason_code=assessment.reprompt_reason,
        )
        if assessment.selected_alternative:
            transcript = replace(
                transcript,
                text=assessment.cleaned_text,
                confidence=assessment.acoustic_confidence,
            )
            text = transcript.text
            confidence = transcript.confidence
            logger.info(
                "stt_quality selected_real_alternative utterance_id=%s "
                "confidence=%s band=%s chars=%d",
                trace_id or "unknown",
                "unknown" if confidence is None else f"{confidence:.3f}",
                assessment.confidence_band.value,
                len(text),
            )
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
            print(
                f"\n[stt] Reprompt required ({assessment.reprompt_reason}, "
                f"band={assessment.confidence_band.value})"
            )
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
            args=(transcript,),
            daemon=True,
        ).start()

    def _on_speech_finished_event(self, event: Any) -> None:
        """Record measured TTS synthesis latency when the audio layer reports it."""
        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else {}
        latency = payload.get("latency_ms")
        if isinstance(latency, (int, float)) and latency >= 0:
            self.metrics.record_tts_call(latency_ms=float(latency))
        turn_id = str(payload.get("turn_id", "") or "").strip()
        if turn_id:
            self.metrics.record_turn_stage(
                turn_id,
                "speech_end",
                generation_id=payload.get("speech_generation"),
                audio_duration_ms=payload.get("duration_ms"),
                tts_latency_ms=latency,
                interrupted=payload.get("interrupted"),
                status=("success" if payload.get("success") else "incomplete"),
                synthesizer_draining=payload.get("synthesizer_draining"),
            )

    def _on_speech_interrupted_event(self, event: Any) -> None:
        """Record real barge-in stop timing without PCM or transcript content."""
        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else {}
        turn_id = str(payload.get("turn_id", "") or "").strip()
        if not turn_id:
            return
        self.metrics.record_turn_stage(
            turn_id,
            "barge_in",
            generation_id=payload.get("speech_generation"),
            frame_count=payload.get("buffered_frames"),
            playback_stop_ms=payload.get("playback_stop_ms"),
            generation_cancelled=payload.get("logical_generation_cancelled"),
            synthesizer_draining=payload.get("synthesizer_draining"),
            interrupted=True,
        )

    def _on_speech_synthesis_drained_event(self, event: Any) -> None:
        """Record when an uncancellable TTS call has actually returned."""
        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else {}
        turn_id = str(payload.get("turn_id", "") or "").strip()
        if not turn_id:
            return
        self.metrics.record_turn_stage(
            turn_id,
            "stale_tts_drain_complete",
            generation_id=payload.get("speech_generation"),
            cancelled=payload.get("cancelled"),
            stale=payload.get("stale"),
        )

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

    def _on_agent_task_event(self, event_name: str, task: AgentTaskView) -> None:
        """Queue only the tool-authored safe confirmation summary for main-loop TTS."""
        if event_name != "TASK_AWAITING_CONFIRMATION" or not task.confirmation_id:
            return
        confirmation = self.confirmation_service.status(task.confirmation_id)
        if confirmation is None or confirmation.state is not ConfirmationState.PENDING:
            return
        with self._agent_announcement_lock:
            if task.confirmation_id in self._queued_agent_confirmation_ids:
                return
            self._queued_agent_confirmation_ids.add(task.confirmation_id)
        self._pending_agent_confirmation_announcements.put(
            (task.confirmation_id, confirmation.summary)
        )

    def _try_start_pending_agent_confirmation_announcement(self) -> None:
        """Speak a pending request only after the current interaction releases audio."""
        if self.audio_coordinator is None or self._pending_agent_confirmation_announcements.empty():
            return
        if self.state_manager.current_state not in {AssistantState.IDLE, AssistantState.ATTENTION}:
            return
        with self._interaction_lock:
            if self._is_processing_interaction:
                return
            try:
                confirmation_id, summary = self._pending_agent_confirmation_announcements.get_nowait()
            except queue.Empty:
                return
            self._is_processing_interaction = True
        gate_started = False
        worker_started = False
        announcement_thread: threading.Thread | None = None
        try:
            confirmation = self.confirmation_service.status(confirmation_id)
            if confirmation is None or confirmation.state is not ConfirmationState.PENDING:
                with self._agent_announcement_lock:
                    self._queued_agent_confirmation_ids.discard(confirmation_id)
                return
            gate_started = True
            self.audio_coordinator.turn_gate.start_processing()
            self.audio_coordinator.collector.reset()
            announcement_thread = threading.Thread(
                target=self._announce_agent_confirmation,
                args=(confirmation_id, summary),
                name="ailen-agent-confirmation-tts",
                daemon=True,
            )
            self._agent_announcement_thread = announcement_thread
            announcement_thread.start()
            worker_started = True
            gate_started = False  # The announcement worker now owns the gate.
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not schedule agent confirmation announcement: %s", exc)
            with self._agent_announcement_lock:
                self._queued_agent_confirmation_ids.discard(confirmation_id)
            self._requeue_agent_confirmation_if_pending(confirmation_id, summary)
        finally:
            if gate_started and self.audio_coordinator is not None:
                try:
                    self.audio_coordinator.turn_gate.stop_processing()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not release audio turn gate after announcement setup: %s", exc)
            if not worker_started:
                if self._agent_announcement_thread is announcement_thread:
                    self._agent_announcement_thread = None
                with self._interaction_lock:
                    self._is_processing_interaction = False

    def _announce_agent_confirmation(self, confirmation_id: str, summary: str) -> None:
        """Announce a bounded confirmation summary, then return the audio turn gate."""
        completed = False
        try:
            if self.audio_coordinator is not None:
                mode = self._agent_social_mode()
                if mode in {SocialMode.SHOP, SocialMode.PUBLIC}:
                    text = "Hay una acción pendiente en el panel."
                else:
                    text = (
                        f"Necesito tu confirmación para {summary}. "
                        "Decí confirmo o denegá, o usá el panel."
                    )
                self.audio_coordinator.speak(
                    text,
                    voice_id=self.config.speech.tts_voice,
                )
                completed = not self.audio_coordinator.last_speech_interrupted
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not announce agent confirmation: %s", exc)
        finally:
            try:
                request = self.confirmation_service.status(confirmation_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not inspect confirmation after announcement: %s", exc)
                request = None
            still_pending = request is not None and request.state is ConfirmationState.PENDING
            if completed and still_pending and self._agent_social_mode() not in {
                SocialMode.SHOP, SocialMode.PUBLIC
            }:
                self._announced_agent_confirmations[confirmation_id] = time.monotonic()
            with self._agent_announcement_lock:
                self._queued_agent_confirmation_ids.discard(confirmation_id)
            if self.audio_coordinator is not None:
                try:
                    self.audio_coordinator.turn_gate.stop_processing()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not release audio turn gate after announcement: %s", exc)
            with self._interaction_lock:
                self._is_processing_interaction = False
            current = threading.current_thread()
            if self._agent_announcement_thread is current:
                self._agent_announcement_thread = None
            if still_pending and not completed and request is not None:
                self._requeue_agent_confirmation_if_pending(confirmation_id, request.summary)

    def _requeue_agent_confirmation_if_pending(self, confirmation_id: str, summary: str) -> None:
        """Keep unresolved requests queued after an interrupted/failed announcement."""
        request = self.confirmation_service.status(confirmation_id)
        if request is None or request.state is not ConfirmationState.PENDING:
            with self._agent_announcement_lock:
                self._queued_agent_confirmation_ids.discard(confirmation_id)
            return
        with self._agent_announcement_lock:
            if confirmation_id in self._queued_agent_confirmation_ids:
                return
            self._queued_agent_confirmation_ids.add(confirmation_id)
        self._pending_agent_confirmation_announcements.put((confirmation_id, summary))

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

    def _process_conversation(self, transcript: Transcript) -> None:
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
            resp, _plan = self.conversation_coordinator.handle_transcript(
                transcript,
                session_id=self._conversation_session_id,
            )

            in_tok = resp.usage.input_tokens if resp.usage else None
            out_tok = resp.usage.output_tokens if resp.usage else None
            response_attempts = (
                resp.attempts if isinstance(getattr(resp, "attempts", None), list) else []
            )
            failed_attempts = [
                attempt for attempt in response_attempts if attempt.outcome != "success"
            ]
            first_text_ms = (
                resp.first_text_ms
                if isinstance(getattr(resp, "first_text_ms", None), (int, float))
                else None
            )
            provider_setup_ms = (
                resp.provider_setup_ms
                if isinstance(getattr(resp, "provider_setup_ms", None), (int, float))
                else None
            )
            provider_ready_ms = (
                resp.provider_ready_ms
                if isinstance(getattr(resp, "provider_ready_ms", None), (int, float))
                else None
            )
            fallback_cause = None
            if failed_attempts:
                first_failed = failed_attempts[0]
                fallback_cause = (
                    first_failed.error_kind.value
                    if first_failed.error_kind is not None
                    else first_failed.detail
                )
            self.metrics.record_ai_call(
                latency_ms=resp.latency_ms,
                in_tokens=in_tok,
                out_tokens=out_tok,
                prompt_eval_ms=resp.usage.prompt_eval_ms if resp.usage else None,
                generation_ms=resp.usage.generation_ms if resp.usage else None,
                load_ms=resp.usage.load_ms if resp.usage else None,
                provider=resp.provider,
                model=resp.model,
                first_text_ms=first_text_ms,
                provider_setup_ms=provider_setup_ms,
                provider_ready_ms=provider_ready_ms,
                request_chars=(
                    resp.request_chars
                    if isinstance(getattr(resp, "request_chars", None), int)
                    else None
                ),
                fallback_used=bool(failed_attempts),
                fallback_cause=fallback_cause,
            )

            print(
                f"[ai] Response ready provider={resp.provider} model={resp.model} "
                f"first_text={first_text_ms if first_text_ms is not None else 'unsupported'}ms "
                f"setup={provider_setup_ms if provider_setup_ms is not None else 'unsupported'}ms "
                f"latency={resp.latency_ms:.1f}ms fallback={'yes' if failed_attempts else 'no'} "
                f"fallback_cause={fallback_cause or 'none'} len={len(resp.text)}"
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
        self._memory_pressure_stop.clear()
        if self.config.ai.local.enabled and self.inference_recommendation is not None:
            self._memory_pressure_thread = threading.Thread(
                target=self._memory_pressure_loop,
                name="ailen-model-memory-pressure",
                daemon=True,
            )
            self._memory_pressure_thread.start()
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

                self._try_start_pending_agent_confirmation_announcement()
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
        self._memory_pressure_stop.set()

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

        agent_shutdown_timeout = min(
            15.0, max(1.0, float(self.config.ai.timeout_seconds) + 1.0)
        )
        agent_stopped = True
        if self.agent_service is not None:
            try:
                agent_stopped = self.agent_service.shutdown(timeout=agent_shutdown_timeout)
                if not agent_stopped:
                    logger.warning("Agent task did not stop within the shutdown budget")
            except Exception as exc:  # noqa: BLE001
                agent_stopped = False
                logger.warning("Error stopping Core agent service: %s", exc)
            if agent_stopped:
                self.agent_service = None

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
        if self._agent_announcement_thread is not None:
            announcement_thread = self._agent_announcement_thread
            if announcement_thread is not threading.current_thread():
                try:
                    announcement_thread.join(timeout=agent_shutdown_timeout)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error joining agent announcement thread: %s", exc)
                if announcement_thread.is_alive():
                    logger.warning("Agent confirmation announcement thread remains active")
                else:
                    self._agent_announcement_thread = None

        # Close Face Window
        if self.face_controller:
            try:
                if hasattr(self.face_controller, "close"):
                    self.face_controller.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing face controller: %s", exc)

        # Close persisted conversation session after all turn-producing components stop.
        if agent_stopped and self.memory_repo and self._conversation_session_id:
            try:
                self.memory_repo.end_session(self._conversation_session_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not close conversation session: %s", exc)
            self._conversation_session_id = None

        # Stop AILEN-owned Managed Runtime (never touch external runtimes)
        if self._memory_pressure_thread and self._memory_pressure_thread.is_alive():
            self._memory_pressure_thread.join(timeout=1.0)
        self._memory_pressure_thread = None
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

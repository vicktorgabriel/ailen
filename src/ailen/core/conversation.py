"""End-to-end conversation coordinator for AILEN.

Coordinates the full interaction pipeline:
Transcript -> ContextBuilder -> Router -> AiOrchestrator -> AudioCoordinator.speak()
"""

import logging

from ailen.ai.budget import BudgetPolicy
from ailen.ai.context import AiContextBuilder
from ailen.ai.contracts import AiResponse
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.router import RoutePlan, RouteRequest, RuleBasedRouter
from ailen.audio.contracts import Transcript
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.speech_text import normalize_text_for_speech
from ailen.domain.enums import DeviceProfile, PrivacyLevel, SocialMode

logger = logging.getLogger("ailen.core.conversation")


class ConversationCoordinator:
    """Orchestrates end-to-end user voice input into AI reasoning and vocal response."""

    def __init__(
        self,
        context_builder: AiContextBuilder,
        router: RuleBasedRouter,
        orchestrator: AiOrchestrator,
        audio_coordinator: AudioInteractionCoordinator | None = None,
        profile: DeviceProfile = DeviceProfile.HYBRID,
        mode: SocialMode = SocialMode.WORKSHOP,
        privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE,
        identity_name: str = "Asistente",
        tts_voice_id: str = "es_ES-standard",
        internet_available: bool = False,
        cloud_allowed: bool = False,
        lan_brain_trusted: bool = False,
        budget_policy: BudgetPolicy | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.router = router
        self.orchestrator = orchestrator
        self.audio_coordinator = audio_coordinator
        self.profile = profile
        self.mode = mode
        self.privacy_level = privacy_level
        self.identity_name = identity_name
        self.tts_voice_id = tts_voice_id
        self.internet_available = internet_available
        self.cloud_allowed = cloud_allowed
        self.lan_brain_trusted = lan_brain_trusted
        self.budget_policy = budget_policy

    def handle_user_input(
        self,
        text: str,
        session_id: str | None = None,
        intent: str = "chat",
    ) -> tuple[AiResponse, RoutePlan]:
        """Process user text through context builder, router, orchestrator, and speech output."""
        if not text.strip():
            empty_resp = AiResponse(text="", finish_reason="empty_input")
            empty_plan = RoutePlan(primary_backend="rule", reason_code="EMPTY_INPUT")
            return empty_resp, empty_plan

        # 1. Determine destination and routing. Cloud requires an explicit budget policy.
        budget_exceeded = self.cloud_allowed and self.budget_policy is None
        if self.budget_policy is not None:
            try:
                budget_available, _budget_reason, _summary = self.budget_policy.is_budget_available()
                budget_exceeded = not budget_available
            except Exception as exc:  # noqa: BLE001
                logger.warning("Budget policy unavailable; blocking cloud for this turn: %s", exc)
                budget_exceeded = True

        route_req = RouteRequest(
            intent=intent,
            profile=self.profile,
            privacy_level=self.privacy_level,
            internet_available=self.internet_available,
            lan_brain_available="lan_brain" in self.orchestrator.backends,
            lan_brain_trusted=self.lan_brain_trusted,
            local_backend_available="local" in self.orchestrator.backends or "fake" in self.orchestrator.backends,
            cloud_allowed=self.cloud_allowed,
            budget_exceeded=budget_exceeded,
        )

        plan = self.router.route(route_req)

        # 2. Build privacy-bounded context for the chosen primary backend
        ai_req = self.context_builder.build_request(
            user_message=text,
            session_id=session_id,
            mode=self.mode,
            privacy_level=self.privacy_level,
            identity_name=self.identity_name,
            destination=plan.primary_backend,
            lan_trusted=self.lan_brain_trusted,
            metadata={"voice_output": self.audio_coordinator is not None},
        )

        # 3. Execute inference via orchestrator
        response, plan = self.orchestrator.execute(ai_req, plan=plan, session_id=session_id)

        # 4. Speak response through AudioInteractionCoordinator if present
        if self.audio_coordinator and response.text.strip():
            try:
                spoken_text = normalize_text_for_speech(response.text)
                if spoken_text:
                    self.audio_coordinator.speak(spoken_text, voice_id=self.tts_voice_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("Error outputting audio speech: %s", e)

        return response, plan

    def handle_transcript(
        self,
        transcript: Transcript,
        session_id: str | None = None,
    ) -> tuple[AiResponse, RoutePlan]:
        """Convenience handler accepting a Transcript object from STT."""
        return self.handle_user_input(transcript.text, session_id=session_id)

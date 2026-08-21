"""Unit tests for ConversationCoordinator."""

from ailen.ai.budget import BudgetPolicy
from ailen.ai.context import AiContextBuilder
from ailen.ai.fake import FakeAiBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.router import RuleBasedRouter
from ailen.audio.contracts import Transcript
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.fake import FakeAudioOutputBackend, FakeTtsBackend
from ailen.core.conversation import ConversationCoordinator
from ailen.domain.enums import DeviceProfile, PrivacyLevel, SocialMode
from ailen.face import NullFaceController


def test_conversation_coordinator_pipeline() -> None:
    # 1. Setup components
    face_ctrl = NullFaceController()
    audio_output = FakeAudioOutputBackend()
    tts_backend = FakeTtsBackend()
    audio_coord = AudioInteractionCoordinator(
        audio_output=audio_output,
        tts=tts_backend,
        face_controller=face_ctrl,
    )

    ctx_builder = AiContextBuilder(default_identity_name="Aura")
    router = RuleBasedRouter()
    fake_ai = FakeAiBackend(provider="local_llm", canned_response="Hola, estoy lista para ayudarte.")
    orchestrator = AiOrchestrator(backends={"local": fake_ai})

    coordinator = ConversationCoordinator(
        context_builder=ctx_builder,
        router=router,
        orchestrator=orchestrator,
        audio_coordinator=audio_coord,
        identity_name="Aura",
    )

    transcript = Transcript(text="Hola Aura", confidence=0.95, latency_ms=120.0)
    resp, plan = coordinator.handle_transcript(transcript)

    assert resp.text == "Hola, estoy lista para ayudarte."
    assert resp.provider == "local_llm"
    assert plan.primary_backend == "local"


def test_conversation_budget_policy_blocks_cloud_and_falls_back_local() -> None:
    ctx_builder = AiContextBuilder(default_identity_name="Aura")
    router = RuleBasedRouter()
    cloud_ai = FakeAiBackend(provider="cloud_llm", canned_response="cloud should not run")
    local_ai = FakeAiBackend(provider="local_llm", canned_response="respuesta local")
    orchestrator = AiOrchestrator(backends={"cloud": cloud_ai, "local": local_ai})
    coordinator = ConversationCoordinator(
        context_builder=ctx_builder,
        router=router,
        orchestrator=orchestrator,
        profile=DeviceProfile.CLOUD,
        mode=SocialMode.PUBLIC,
        privacy_level=PrivacyLevel.PUBLIC,
        internet_available=True,
        cloud_allowed=True,
        budget_policy=BudgetPolicy(daily_budget_usd=0.0, monthly_budget_usd=0.0),
    )

    resp, plan = coordinator.handle_user_input("Hola")
    assert plan.primary_backend == "local"
    assert resp.provider == "local_llm"
    assert resp.text == "respuesta local"


def test_conversation_private_lan_requires_explicit_trust() -> None:
    ctx_builder = AiContextBuilder(default_identity_name="Aura")
    router = RuleBasedRouter()
    lan_ai = FakeAiBackend(provider="lan_brain", canned_response="respuesta lan")
    orchestrator = AiOrchestrator(backends={"lan_brain": lan_ai})

    blocked = ConversationCoordinator(
        context_builder=ctx_builder,
        router=router,
        orchestrator=orchestrator,
        privacy_level=PrivacyLevel.PRIVATE,
        lan_brain_trusted=False,
    )
    blocked_resp, blocked_plan = blocked.handle_user_input("Dato privado")
    assert blocked_plan.primary_backend == "degraded"
    assert blocked_resp.finish_reason == "degraded"

    trusted = ConversationCoordinator(
        context_builder=ctx_builder,
        router=router,
        orchestrator=orchestrator,
        privacy_level=PrivacyLevel.PRIVATE,
        lan_brain_trusted=True,
    )
    trusted_resp, trusted_plan = trusted.handle_user_input("Dato privado")
    assert trusted_plan.primary_backend == "lan_brain"
    assert trusted_resp.text == "respuesta lan"

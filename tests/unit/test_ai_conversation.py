"""Unit tests for ConversationCoordinator."""

import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

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
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository


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


def test_conversation_emits_redacted_stage_telemetry() -> None:
    observed: list[tuple[str, str, dict[str, object]]] = []

    def record_stage(turn_id: str, stage: str, **metadata: object) -> None:
        observed.append((turn_id, stage, metadata))

    coordinator = ConversationCoordinator(
        context_builder=AiContextBuilder(default_identity_name="Aura"),
        router=RuleBasedRouter(),
        orchestrator=AiOrchestrator(
            backends={"local": FakeAiBackend(canned_response="Todo bien.")}
        ),
        telemetry_sink=record_stage,
    )

    coordinator.handle_user_input("mensaje sintético", trace_id="turn-safe")

    stages = {stage for _turn_id, stage, _metadata in observed}
    assert {"deterministic_resolver", "context_build", "main_llm", "turn_total"} <= stages
    assert all(turn_id == "turn-safe" for turn_id, _stage, _metadata in observed)
    serialized = str(observed)
    assert "mensaje sintético" not in serialized


def test_conversation_budget_policy_blocks_remote_and_falls_back_local() -> None:
    ctx_builder = AiContextBuilder(default_identity_name="Aura")
    router = RuleBasedRouter()
    remote_ai = FakeAiBackend(provider="remote_llm", canned_response="remote should not run")
    local_ai = FakeAiBackend(provider="local_llm", canned_response="respuesta local")
    orchestrator = AiOrchestrator(
        backends={"remote:test": remote_ai, "local": local_ai}
    )
    coordinator = ConversationCoordinator(
        context_builder=ctx_builder,
        router=router,
        orchestrator=orchestrator,
        profile=DeviceProfile.CLOUD,
        mode=SocialMode.PUBLIC,
        privacy_level=PrivacyLevel.PUBLIC,
        internet_available=True,
        external_allowed=True,
        backend_budget_policies={
            "remote:test": BudgetPolicy(daily_budget_usd=0.0, monthly_budget_usd=0.0)
        },
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


def test_voice_streaming_waits_for_complete_phrase_after_short_sentence() -> None:
    from ailen.ai.contracts import (
        AiResponse,
        BackendCapabilities,
        BackendHealth,
        StreamingAiBackend,
    )
    from ailen.domain.enums import ServiceStatus

    class StreamingBackend(StreamingAiBackend):
        def health(self):  # type: ignore[no-untyped-def]
            return BackendHealth(ServiceStatus.HEALTHY, "ok")

        def capabilities(self):  # type: ignore[no-untyped-def]
            return BackendCapabilities(supports_streaming=True, is_local=True)

        def generate_stream(self, request, on_text_delta):  # type: ignore[no-untyped-def]
            emitted = ""
            for delta in ("¿Qué te pasó?", " ¿Fue", " un día largo?"):
                emitted += delta
                if on_text_delta(delta) is False:
                    return AiResponse(
                        text=emitted,
                        provider="test",
                        model="stream",
                        finish_reason="client_stop",
                    )
            return AiResponse(text=emitted, provider="test", model="stream")

    face_ctrl = NullFaceController()
    audio_coord = AudioInteractionCoordinator(
        audio_output=FakeAudioOutputBackend(),
        tts=FakeTtsBackend(),
        face_controller=face_ctrl,
    )
    router = RuleBasedRouter()
    coordinator = ConversationCoordinator(
        context_builder=AiContextBuilder(default_identity_name="Ailén"),
        router=router,
        orchestrator=AiOrchestrator(backends={"local": StreamingBackend()}),
        audio_coordinator=audio_coord,
        identity_name="Ailén",
    )
    response, _ = coordinator.handle_user_input(
        "Estoy cansado",
        input_modality="voice",
    )
    assert response.text == "¿Qué te pasó? ¿Fue un día largo?"


def test_voice_streaming_starts_tts_before_model_finishes() -> None:
    from ailen.ai.contracts import (
        AiResponse,
        BackendCapabilities,
        BackendHealth,
        StreamingAiBackend,
    )
    from ailen.audio.contracts import SpeechOutput, SpeechRequest
    from ailen.domain.enums import ServiceStatus

    tts_started = threading.Event()
    generation_finished = threading.Event()
    synthesized: list[str] = []

    class RecordingTts:
        def health(self):  # type: ignore[no-untyped-def]
            return None

        def synthesize(self, request: SpeechRequest) -> SpeechOutput:
            synthesized.append(request.text)
            tts_started.set()
            return SpeechOutput(audio_data=b"pcm", duration_ms=30.0)

    class StreamingBackend(StreamingAiBackend):
        def health(self):  # type: ignore[no-untyped-def]
            return BackendHealth(ServiceStatus.HEALTHY, "ok")

        def capabilities(self):  # type: ignore[no-untyped-def]
            return BackendCapabilities(supports_streaming=True, is_local=True)

        def generate_stream(self, request, on_text_delta):  # type: ignore[no-untyped-def]
            del request
            first = "Esta primera frase completa ya debería estar sonando."
            assert on_text_delta(first) is not False
            assert tts_started.wait(timeout=1.0), "TTS waited for the complete LLM response"
            second = " La generación continúa después."
            assert on_text_delta(second) is not False
            generation_finished.set()
            return AiResponse(text=first + second, provider="test", model="stream")

    audio = AudioInteractionCoordinator(
        audio_output=FakeAudioOutputBackend(),
        tts=RecordingTts(),
    )
    coordinator = ConversationCoordinator(
        context_builder=AiContextBuilder(default_identity_name="Ailén"),
        router=RuleBasedRouter(),
        orchestrator=AiOrchestrator(backends={"local": StreamingBackend()}),
        audio_coordinator=audio,
        identity_name="Ailén",
    )

    response, _ = coordinator.handle_user_input("Contame algo", input_modality="voice")

    assert generation_finished.is_set()
    assert response.text == (
        "Esta primera frase completa ya debería estar sonando. "
        "La generación continúa después."
    )
    assert synthesized == [
        "Esta primera frase completa ya debería estar sonando.",
        "La generación continúa después.",
    ]


def test_barge_in_cancels_model_stream_and_discards_queued_phrase() -> None:
    from ailen.ai.contracts import (
        AiResponse,
        BackendCapabilities,
        BackendHealth,
        StreamingAiBackend,
    )
    from ailen.audio.contracts import SpeechOutput, SpeechRequest
    from ailen.domain.enums import ServiceStatus

    cancelled = threading.Event()
    callback_results: list[bool | None] = []
    audio_ref: list[AudioInteractionCoordinator] = []

    class OneChunkTts:
        def health(self):  # type: ignore[no-untyped-def]
            return None

        def synthesize(self, request: SpeechRequest) -> SpeechOutput:
            return SpeechOutput(audio_data=request.text.encode(), duration_ms=40.0)

    class InterruptingOutput(FakeAudioOutputBackend):
        def play(  # type: ignore[override]
            self,
            audio_data: bytes,
            sample_rate: int = 16000,
            channels: int = 1,
            cancel_event: threading.Event | None = None,
        ) -> None:
            del audio_data, sample_rate, channels
            assert cancel_event is not None
            cancel_event.set()
            cancelled.set()

    class StreamingBackend(StreamingAiBackend):
        def health(self):  # type: ignore[no-untyped-def]
            return BackendHealth(ServiceStatus.HEALTHY, "ok")

        def capabilities(self):  # type: ignore[no-untyped-def]
            return BackendCapabilities(supports_streaming=True, is_local=True)

        def generate_stream(self, request, on_text_delta):  # type: ignore[no-untyped-def]
            del request
            first = "Esta frase empieza a reproducirse y será interrumpida."
            callback_results.append(on_text_delta(first))
            assert cancelled.wait(timeout=1.0)
            second = " Esta frase nunca debe llegar a Piper."
            callback_results.append(on_text_delta(second))
            return AiResponse(
                text=first,
                provider="test",
                model="stream",
                finish_reason="client_stop",
            )

    audio = AudioInteractionCoordinator(
        audio_output=InterruptingOutput(),
        tts=OneChunkTts(),
    )
    audio_ref.append(audio)
    with TemporaryDirectory() as tmpdir:
        db = SQLiteManager(Path(tmpdir) / "interrupted.db")
        MigrationRunner(db).run_migrations()
        repository = MemoryRepository(db)
        session = repository.create_session(mode=SocialMode.WORKSHOP)
        coordinator = ConversationCoordinator(
            context_builder=AiContextBuilder(default_identity_name="Ailén"),
            router=RuleBasedRouter(),
            orchestrator=AiOrchestrator(backends={"local": StreamingBackend()}),
            audio_coordinator=audio,
            identity_name="Ailén",
            repository=repository,
        )

        response, _ = coordinator.handle_user_input(
            "Decime algo largo",
            session_id=session.session_id,
            input_modality="voice",
        )

        messages = repository.get_session_messages(session.session_id)

    assert callback_results == [True, False]
    assert audio_ref[0].speech_cancelled is True
    assert response.finish_reason == "interrupted"
    assert [message.role for message in messages] == ["user"]


def test_incremental_speech_worker_has_bounded_join_when_tts_stalls() -> None:
    from ailen.ai.contracts import (
        AiResponse,
        BackendCapabilities,
        BackendHealth,
        StreamingAiBackend,
    )
    from ailen.audio.contracts import SpeechOutput, SpeechRequest
    from ailen.domain.enums import ServiceStatus

    release_tts = threading.Event()

    class StalledTts:
        def health(self):  # type: ignore[no-untyped-def]
            return None

        def synthesize(self, request: SpeechRequest) -> SpeechOutput:
            del request
            assert release_tts.wait(timeout=2.0)
            return SpeechOutput(audio_data=b"late", duration_ms=40.0)

    class OneSentenceBackend(StreamingAiBackend):
        def health(self):  # type: ignore[no-untyped-def]
            return BackendHealth(ServiceStatus.HEALTHY, "ok")

        def capabilities(self):  # type: ignore[no-untyped-def]
            return BackendCapabilities(supports_streaming=True, is_local=True)

        def generate_stream(self, request, on_text_delta):  # type: ignore[no-untyped-def]
            del request
            text = "Esta respuesta no debe bloquear el turno para siempre."
            on_text_delta(text)
            return AiResponse(text=text, provider="test", model="stream")

    audio = AudioInteractionCoordinator(
        audio_output=FakeAudioOutputBackend(),
        tts=StalledTts(),
    )
    coordinator = ConversationCoordinator(
        context_builder=AiContextBuilder(default_identity_name="Ailén"),
        router=RuleBasedRouter(),
        orchestrator=AiOrchestrator(backends={"local": OneSentenceBackend()}),
        audio_coordinator=audio,
        identity_name="Ailén",
        speech_join_timeout_seconds=0.15,
    )
    release_timer = threading.Timer(0.8, release_tts.set)
    release_timer.start()
    started = time.monotonic()
    try:
        response, _ = coordinator.handle_user_input("Decime algo", input_modality="voice")
    finally:
        release_tts.set()
        release_timer.cancel()

    assert time.monotonic() - started < 0.5
    assert response.finish_reason == "speech_output_timeout"


def test_speech_affect_is_forwarded_to_audio_coordinator() -> None:
    from unittest.mock import MagicMock

    from ailen.core.personality import PersonalityService, PersonalityTraits

    audio = MagicMock()
    audio.last_speech_interrupted = False
    personality = PersonalityService(
        identity_id="affect-test",
        defaults=PersonalityTraits(expressiveness=0.9),
    )
    coordinator = ConversationCoordinator(
        context_builder=AiContextBuilder(default_identity_name="Ailén"),
        router=RuleBasedRouter(),
        orchestrator=AiOrchestrator(backends={"local": FakeAiBackend()}),
        audio_coordinator=audio,
        personality_service=personality,
        identity_name="Ailén",
    )

    coordinator._speak_if_enabled("Qué bueno.", emotion="happy")

    audio.speak.assert_called_once_with(
        "Qué bueno.",
        voice_id="es_ES-standard",
        emotion="happy",
        expressiveness=0.9,
    )

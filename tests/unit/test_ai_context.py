"""Unit tests for AiContextBuilder."""

from tempfile import TemporaryDirectory

import pytest

from ailen.ai.context import AiContextBuilder
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository


def test_context_builder_builds_basic_request() -> None:
    builder = AiContextBuilder(default_identity_name="Aura")
    req = builder.build_request(
        user_message="Hola Aura",
        mode=SocialMode.HOME,
        privacy_level=PrivacyLevel.PRIVATE,
    )

    assert "Sos Aura" in req.system_context
    assert "NO ejecuta acciones" in req.system_context
    assert "nunca afirmes que cambiaste volumen" in req.system_context
    assert "Usá voseo" in req.system_context
    assert "castellano peninsular" in req.system_context
    assert "datos externos que pueden haber cambiado" in req.system_context
    assert len(req.messages) == 1
    assert req.messages[0].content == "Hola Aura"
    assert req.mode == SocialMode.HOME


def test_context_builder_with_sqlite_memories_and_sessions() -> None:
    with TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_ctx.db"
        db_mgr = SQLiteManager(db_path)
        MigrationRunner(db_mgr).run_migrations()
        repo = MemoryRepository(db_mgr)

        # Create session & messages
        session = repo.create_session(mode=SocialMode.WORKSHOP)
        repo.add_message(session.session_id, "user", "Mensaje anterior 1")
        repo.add_message(session.session_id, "assistant", "Respuesta anterior 1")

        # Save private memory and public business fact
        repo.add_memory("Clave WiFi secreta: 12345", scope=PrivacyLevel.PRIVATE)
        repo.set_business_fact("Horario", "Lunes a Viernes 9 a 18hs", is_public=True)

        builder = AiContextBuilder(repository=repo, default_identity_name="Asistente")

        # 1. In WORKSHOP mode for LOCAL destination:
        local_req = builder.build_request(
            user_message="¿Qué horario tienen?",
            session_id=session.session_id,
            mode=SocialMode.WORKSHOP,
            privacy_level=PrivacyLevel.PRIVATE,
            destination="local",
        )

        assert len(local_req.messages) == 3  # 2 previous + 1 current
        assert any("Horario" in m for m in local_req.retrieved_memory)

        # 2. A PRIVATE request cannot be downgraded and sent to CLOUD.
        with pytest.raises(PermissionError, match="PRIVATE_REMOTE_BLOCKED"):
            builder.build_request(
                user_message="¿Qué horario tienen?",
                session_id=session.session_id,
                mode=SocialMode.WORKSHOP,
                privacy_level=PrivacyLevel.PRIVATE,
                destination="cloud",
            )


def test_context_builder_includes_bounded_local_vision_state() -> None:
    builder = AiContextBuilder(default_identity_name="AILEN")
    req = builder.build_request(
        user_message="¿Me ves?",
        destination="local",
        metadata={
            "voice_output": True,
            "runtime_context": {
                "camera_active": True,
                "presence_detected": True,
                "faces_count": 1,
                "face_detection_verified": True,
                "visual_capability": "face_detection_with_confidence",
            },
        },
    )
    assert "detector facial verificado está activo" in req.system_context
    assert "detecta un rostro" in req.system_context
    assert "no reconoce identidad" in req.system_context
    assert "no repitas ni parafrasees" in req.system_context.lower()


def test_context_builder_does_not_send_runtime_vision_state_to_cloud() -> None:
    builder = AiContextBuilder(default_identity_name="AILEN")
    req = builder.build_request(
        user_message="Hola",
        destination="cloud",
        privacy_level=PrivacyLevel.PUBLIC,
        metadata={
            "runtime_context": {
                "camera_active": True,
                "presence_detected": True,
                "faces_count": 1,
            },
        },
    )
    assert "cámara de presencia" not in req.system_context
    assert "detecta una persona" not in req.system_context


def test_context_builder_marks_experimental_vision_as_unverified() -> None:
    builder = AiContextBuilder(default_identity_name="AILEN")
    req = builder.build_request(
        user_message="¿Me ves?",
        destination="local",
        metadata={
            "runtime_context": {
                "camera_active": True,
                "presence_detected": True,
                "faces_count": 1,
                "face_detection_verified": False,
                "visual_capability": "experimental_presence_only",
            },
        },
    )
    assert "modo experimental" in req.system_context
    assert "No digas que ves o detectás" in req.system_context

def test_ai_context_includes_bounded_personality_style() -> None:
    builder = AiContextBuilder()
    req = builder.build_request(
        "hola",
        metadata={"personality_style": "Usá un tono informal y respuestas breves."},
    )
    assert "tono informal" in req.system_context
    assert "respuestas breves" in req.system_context


def test_voice_context_allows_natural_reaction_without_support_closings() -> None:
    req = AiContextBuilder().build_request(
        "che, está fresco",
        metadata={"voice_output": True, "capabilities": []},
    )

    assert "reaccioná con naturalidad" in req.system_context
    assert "Evitá interrogatorios" in req.system_context
    assert "Capacidades activas de Core" not in req.system_context

def test_ai_context_includes_declarative_runtime_capabilities() -> None:
    builder = AiContextBuilder()
    req = builder.build_request(
        "hola",
        metadata={
            "capabilities": [
                {"key": "tool.clock", "description": "decir la hora"},
                {"key": "face.expression", "description": "cambiar la expresión de la cara"},
            ]
        },
    )
    assert "tool.clock" in req.system_context
    assert "face.expression" in req.system_context
    assert "Sólo afirmes que podés ejecutar acciones incluidas en esa lista" in req.system_context
    assert "web en vivo=no" not in req.system_context


def test_voice_turn_includes_bounded_sensor_and_persona_context() -> None:
    builder = AiContextBuilder()
    req = builder.build_request(
        "hola",
        destination="local",
        metadata={
            "input_modality": "voice",
            "voice_output": True,
            "persona_description": "Sos curiosa y espontánea.",
            "runtime_context": {
                "microphone_active": True,
                "speech_output_active": True,
                "camera_active": False,
            },
        },
    )
    assert "micrófono" in req.system_context
    assert "entrada de voz activa" in req.system_context
    assert "Sos curiosa y espontánea" in req.system_context
    assert "tono emocional" in req.system_context


def test_voice_context_declares_bounded_conversational_expression_contract() -> None:
    req = AiContextBuilder().build_request(
        "hola",
        metadata={
            "voice_output": True,
            "conversational_expressions": ["neutral", "happy", "curious"],
        },
    )
    assert "[[face:expresion]]" in req.system_context
    assert "neutral, happy, curious" in req.system_context


def test_context_builder_sets_configured_temperature() -> None:
    req = AiContextBuilder(temperature=0.73).build_request("hola")
    assert req.temperature == 0.73


def test_compact_voice_context_stays_bounded_for_small_models() -> None:
    req = AiContextBuilder(max_char_budget=2200).build_request(
        "hola",
        destination="local",
        metadata={
            "voice_output": True,
            "input_modality": "voice",
            "persona_description": "Cálida, curiosa y espontánea.",
            "personality_style": "Tono informal y breve.",
            "conversational_expressions": ["neutral", "happy", "curious"],
            "runtime_context": {
                "microphone_active": True,
                "speech_output_active": True,
                "camera_active": False,
            },
        },
    )
    assert len(req.system_context) < 1600


def test_ai_context_keeps_assistant_identity_distinct_from_user() -> None:
    builder = AiContextBuilder(default_identity_name="Ailén")
    request = builder.build_request("Hola", identity_name="Ailén")
    assert "Tu nombre es Ailén" in request.system_context
    assert "no llames Ailén al usuario" in request.system_context


def test_voice_context_discourages_recent_assistant_openers() -> None:
    with TemporaryDirectory() as tmpdir:
        db_mgr = SQLiteManager(f"{tmpdir}/ctx.db")
        MigrationRunner(db_mgr).run_migrations()
        repo = MemoryRepository(db_mgr)
        session = repo.create_session(mode=SocialMode.WORKSHOP)
        repo.add_message(session.session_id, "user", "hola")
        repo.add_message(session.session_id, "assistant", "Arranque repetido de la respuesta anterior.")

        req = AiContextBuilder(repository=repo).build_request(
            "otra cosa",
            session_id=session.session_id,
            metadata={"voice_output": True},
        )

        assert "no como plantilla de estilo" in req.system_context
        assert "Arranque repetido de la respuesta anterior" in req.system_context


def test_personality_style_is_not_cut_at_legacy_field_limit() -> None:
    style = "x" * 430 + " FINAL_ESTILO"
    req = AiContextBuilder(max_char_budget=4000).build_request(
        "hola", metadata={"personality_style": style}
    )
    assert "FINAL_ESTILO" in req.system_context

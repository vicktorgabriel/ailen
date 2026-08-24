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

    assert "Eres Aura" in req.system_context
    assert "NO ejecuta acciones" in req.system_context
    assert "nunca afirmes que cambiaste volumen" in req.system_context
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
    assert "detecta una persona" in req.system_context
    assert "no reconoce identidad" in req.system_context
    assert "no repitas ni parafrasees" in req.system_context


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

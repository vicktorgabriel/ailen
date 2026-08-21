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

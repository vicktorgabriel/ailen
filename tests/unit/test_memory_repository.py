"""Unit tests for MemoryRepository domain data access."""

import tempfile
import unittest
from pathlib import Path

from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository


class TestMemoryRepository(unittest.TestCase):
    """Test suite for MemoryRepository."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_memory.db"
        self.db_mgr = SQLiteManager(self.db_path)
        runner = MigrationRunner(self.db_mgr)
        runner.run_migrations()
        self.repo = MemoryRepository(self.db_mgr)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_session_and_messages(self):
        session = self.repo.create_session(mode=SocialMode.WORKSHOP, participant_hint="Victor")
        self.assertTrue(session.session_id.startswith("sess-"))
        self.assertEqual(session.mode, SocialMode.WORKSHOP)

        msg1 = self.repo.add_message(
            session_id=session.session_id,
            role="user",
            content="¿Cuál es el pinout del BQ24780?",
            mode=SocialMode.WORKSHOP,
        )
        self.assertTrue(msg1.message_id.startswith("msg-"))
        self.assertEqual(msg1.content, "¿Cuál es el pinout del BQ24780?")

        self.repo.add_message(
            session_id=session.session_id,
            role="assistant",
            content="El pin REGN entrega 6V.",
            mode=SocialMode.WORKSHOP,
        )

        messages = self.repo.get_session_messages(session.session_id)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].content, "¿Cuál es el pinout del BQ24780?")
        self.assertEqual(messages[1].content, "El pin REGN entrega 6V.")

        self.repo.end_session(session.session_id)

    def test_memories_search_and_privacy_scope(self):
        self.repo.add_memory(
            content="Victor prefiere mate amargo mientras trabaja.",
            category="user_preference",
            importance=2.0,
            scope=PrivacyLevel.PRIVATE,
        )
        self.repo.add_memory(
            content="Horario de atención del taller: 9:00 a 18:00 hs.",
            category="shop",
            importance=5.0,
            scope=PrivacyLevel.PUBLIC,
        )

        # Search without scope filter
        results = self.repo.search_memories("Victor")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].scope, PrivacyLevel.PRIVATE)

        # Search with PUBLIC scope filter
        public_results = self.repo.search_memories("taller", scope=PrivacyLevel.PUBLIC)
        self.assertEqual(len(public_results), 1)
        self.assertEqual(public_results[0].scope, PrivacyLevel.PUBLIC)

        # Ensure private memory is not found when querying with PUBLIC scope
        private_under_public = self.repo.search_memories("mate", scope=PrivacyLevel.PUBLIC)
        self.assertEqual(len(private_under_public), 0)

    def test_business_facts(self):
        fact = self.repo.set_business_fact(
            key="schedule",
            value="Lunes a Viernes 09:00 a 18:00",
            category="hours",
            is_public=True,
        )
        self.assertEqual(fact.key, "schedule")

        facts = self.repo.get_business_facts(only_public=True)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].value, "Lunes a Viernes 09:00 a 18:00")

        # Update fact
        self.repo.set_business_fact(
            key="schedule",
            value="Lunes a Sábado 09:00 a 13:00",
            category="hours",
            is_public=True,
        )
        updated_facts = self.repo.get_business_facts(only_public=True)
        self.assertEqual(len(updated_facts), 1)
        self.assertEqual(updated_facts[0].value, "Lunes a Sábado 09:00 a 13:00")

    def test_tool_events_and_ai_usage_logging(self):
        tool_evt = self.repo.log_tool_event(
            tool_name="system_status",
            arguments_redacted="{}",
            result_summary="OK",
            success=True,
            latency_ms=12.5,
        )
        self.assertTrue(tool_evt.event_id.startswith("tool-"))
        self.assertTrue(tool_evt.success)

        ai_evt = self.repo.log_ai_usage(
            provider="mock",
            model="default",
            input_tokens=150,
            output_tokens=50,
            estimated_cost=0.0002,
            latency_ms=120.0,
        )
        self.assertTrue(ai_evt.usage_id.startswith("ai-"))
        self.assertEqual(ai_evt.input_tokens, 150)


if __name__ == "__main__":
    unittest.main()

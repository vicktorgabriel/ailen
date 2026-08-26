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

    def test_close_open_sessions_is_scoped_to_node(self):
        first = self.repo.create_session(mode=SocialMode.WORKSHOP, source_node_id="asrock")
        second = self.repo.create_session(mode=SocialMode.WORKSHOP, source_node_id="asrock")
        other = self.repo.create_session(mode=SocialMode.WORKSHOP, source_node_id="debian")
        self.repo.end_session(second.session_id)

        closed = self.repo.close_open_sessions(source_node_id="asrock")
        self.assertEqual(closed, 1)

        with self.repo.db_manager.connection() as conn:
            first_row = conn.execute(
                "SELECT ended_at FROM sessions WHERE session_id = ?", (first.session_id,)
            ).fetchone()
            second_row = conn.execute(
                "SELECT ended_at FROM sessions WHERE session_id = ?", (second.session_id,)
            ).fetchone()
            other_row = conn.execute(
                "SELECT ended_at FROM sessions WHERE session_id = ?", (other.session_id,)
            ).fetchone()
        assert first_row is not None and second_row is not None and other_row is not None
        self.assertIsNotNone(first_row["ended_at"])
        self.assertIsNotNone(second_row["ended_at"])
        self.assertIsNone(other_row["ended_at"])

    def test_session_message_limit_returns_most_recent_in_chronological_order(self):
        session = self.repo.create_session(mode=SocialMode.WORKSHOP)
        for idx in range(8):
            self.repo.add_message(
                session_id=session.session_id,
                role="user" if idx % 2 == 0 else "assistant",
                content=f"m{idx}",
                mode=SocialMode.WORKSHOP,
            )

        messages = self.repo.get_session_messages(session.session_id, limit=3)
        self.assertEqual([m.content for m in messages], ["m5", "m6", "m7"])

    def test_session_message_limit_breaks_timestamp_ties_by_insertion_order(self):
        session = self.repo.create_session(mode=SocialMode.WORKSHOP)
        same_ts = "2026-08-23T12:00:00.000000+00:00"
        with self.repo.db_manager.connection() as conn:
            cursor = conn.cursor()
            for idx in range(8):
                cursor.execute(
                    "INSERT INTO messages (message_id, session_id, role, content, mode, created_at, token_count)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?);",
                    (f"msg-tie-{idx}", session.session_id, "user", f"m{idx}", "WORKSHOP", same_ts, None),
                )

        messages = self.repo.get_session_messages(session.session_id, limit=3)
        self.assertEqual([m.content for m in messages], ["m5", "m6", "m7"])

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

    def test_personality_traits_persist_and_audit(self):
        self.assertEqual(self.repo.get_personality_traits("ailen-seed-01"), {})
        self.repo.set_personality_trait(
            identity_id="ailen-seed-01",
            trait_name="formality",
            trait_value=0.35,
            reason="quiero que seas más informal",
        )
        traits = self.repo.get_personality_traits("ailen-seed-01")
        self.assertEqual(traits, {"formality": 0.35})
        with self.repo.db_manager.connection() as conn:
            row = conn.execute(
                "SELECT event_type, delta, reason FROM personality_events "
                "WHERE identity_id = ? ORDER BY created_at DESC LIMIT 1;",
                ("ailen-seed-01",),
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["event_type"], "EXPLICIT_STYLE_FEEDBACK")
        self.assertEqual(row["reason"], "quiero que seas más informal")

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

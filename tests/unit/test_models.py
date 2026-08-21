"""Unit tests for domain models."""

import unittest

from ailen.domain.enums import AssistantState, DeviceProfile, ErrorCode, ServiceStatus, SocialMode
from ailen.domain.models import (
    AssistantIdentity,
    ConversationSession,
    HardwareReport,
    RuntimeState,
)


class TestModels(unittest.TestCase):
    """Test suite for domain models serialization and defaults."""

    def test_runtime_state_to_dict(self):
        state = RuntimeState(
            version="0.1.0-dev.0",
            node_id="node-test-01",
            profile=DeviceProfile.HYBRID,
            assistant_state=AssistantState.IDLE,
            uptime_seconds=120.5,
            internet_status=ServiceStatus.HEALTHY,
            last_error_code=ErrorCode.AI_TIMEOUT,
        )
        d = state.to_dict()
        self.assertEqual(d["version"], "0.1.0-dev.0")
        self.assertEqual(d["node_id"], "node-test-01")
        self.assertEqual(d["profile"], "HYBRID")
        self.assertEqual(d["assistant_state"], "IDLE")
        self.assertEqual(d["uptime_seconds"], 120.5)
        self.assertEqual(d["internet_status"], "HEALTHY")
        self.assertEqual(d["last_error_code"], "AI_TIMEOUT")

    def test_assistant_identity(self):
        identity = AssistantIdentity(
            identity_id="id-01",
            name="core-instance-01",
            personality_seed="seed-12345",
        )
        self.assertEqual(identity.name, "core-instance-01")
        self.assertIsNone(identity.display_name)
        self.assertEqual(identity.effective_display_name, "core-instance-01")
        self.assertEqual(identity.personality_seed, "seed-12345")
        self.assertEqual(identity.active_personality_version, 1)

        custom_identity = AssistantIdentity(
            identity_id="id-02",
            name="system-unit",
            display_name="Luna",
        )
        self.assertEqual(custom_identity.name, "system-unit")
        self.assertEqual(custom_identity.display_name, "Luna")
        self.assertEqual(custom_identity.effective_display_name, "Luna")

    def test_conversation_session(self):
        session = ConversationSession(
            session_id="sess-01",
            mode=SocialMode.SHOP,
            source_node_id="bangho-01",
        )
        self.assertEqual(session.session_id, "sess-01")
        self.assertEqual(session.mode, SocialMode.SHOP)
        self.assertIsNone(session.ended_at)

    def test_hardware_report_to_dict(self):
        report = HardwareReport(
            recommended_profile=DeviceProfile.CLOUD
        )
        d = report.to_dict()
        self.assertEqual(d["recommended_profile"], "CLOUD")
        self.assertIn("cpu", d)
        self.assertIn("memory", d)


if __name__ == "__main__":
    unittest.main()

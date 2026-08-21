"""Tests de contratos y fakes: AI, STT, TTS, Vision, Face, Tools."""

import unittest

from ailen.adapters import build_fake_backends
from ailen.ai import (
    AiBackend,
    AiRequest,
    ChatMessage,
    FakeAiBackend,
    RouteRequest,
    RuleBasedRouter,
)
from ailen.audio import (
    AudioSegment,
    FakeSttBackend,
    FakeTtsBackend,
    SpeechRequest,
    SttBackend,
    TtsBackend,
)
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.face import FaceController, NullFaceController
from ailen.tools import ClockTool, FakeNotesTool, FakeVolumeTool, Tool, ToolContext, validate_args
from ailen.vision import FakeVisionBackend, VisionBackend


class TestAiContracts(unittest.TestCase):
    def test_fake_backend_satisfies_protocol(self):
        self.assertIsInstance(FakeAiBackend(), AiBackend)

    def test_fake_generate_echo(self):
        backend = FakeAiBackend()
        request = AiRequest(
            request_id="r1",
            messages=[ChatMessage(role="user", content="hola ailen")],
            mode=SocialMode.WORKSHOP,
        )
        response = backend.generate(request)
        self.assertIn("hola ailen", response.text)
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.usage.estimated_cost, 0.0)
        self.assertGreater(response.usage.input_tokens, 0)

    def test_fake_capabilities_local(self):
        caps = FakeAiBackend().capabilities()
        self.assertTrue(caps.is_local)
        self.assertFalse(caps.requires_internet)


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.router = RuleBasedRouter()

    def test_rule_only_intents_never_use_llm(self):
        for intent in ("volume", "playback", "timer", "system_status"):
            plan = self.router.route(RouteRequest(intent=intent))
            self.assertEqual(plan.primary_backend, "rule", intent)
            self.assertEqual(plan.fallback_backends, [])

    def test_private_privacy_never_routes_to_cloud(self):
        request = RouteRequest(
            intent="chat",
            privacy_level=PrivacyLevel.PRIVATE,
            internet_available=True,
            cloud_allowed=True,
            lan_brain_available=True,
            local_backend_available=True,
        )
        plan = self.router.route(request)
        self.assertEqual(plan.primary_backend, "local")
        self.assertNotIn("cloud", plan.fallback_backends)

    def test_cloud_used_when_allowed_and_available(self):
        request = RouteRequest(
            intent="chat",
            privacy_level=PrivacyLevel.PUBLIC,
            internet_available=True,
            cloud_allowed=True,
        )
        plan = self.router.route(request)
        self.assertEqual(plan.primary_backend, "cloud")
        self.assertIn(plan.reason_code, ("CLOUD_FAST_PATH", "CLOUD_ALLOWED_WITHIN_BUDGET"))

    def test_budget_exceeded_blocks_cloud(self):
        request = RouteRequest(
            intent="chat",
            privacy_level=PrivacyLevel.PUBLIC,
            internet_available=True,
            cloud_allowed=True,
            budget_exceeded=True,
        )
        plan = self.router.route(request)
        self.assertNotIn("cloud", [plan.primary_backend, *plan.fallback_backends])
        self.assertEqual(plan.primary_backend, "degraded")

    def test_no_backend_degrades_to_rule(self):
        plan = self.router.route(RouteRequest(intent="chat", privacy_level=PrivacyLevel.PUBLIC))
        self.assertEqual(plan.primary_backend, "degraded")
        self.assertEqual(plan.reason_code, "ALL_BACKENDS_UNAVAILABLE")


class TestAudioFakes(unittest.TestCase):
    def test_stt_protocol(self):
        self.assertIsInstance(FakeSttBackend(), SttBackend)

    def test_stt_canned_text(self):
        result = FakeSttBackend(canned_text="probando").transcribe(AudioSegment(data=b"\xff\x00"))
        self.assertEqual(result.text, "probando")
        self.assertEqual(result.language, "es")

    def test_stt_utf8_payload_convention(self):
        result = FakeSttBackend().transcribe(AudioSegment(data="qué hora es".encode()))
        self.assertEqual(result.text, "qué hora es")

    def test_tts_protocol(self):
        self.assertIsInstance(FakeTtsBackend(), TtsBackend)

    def test_tts_silence_scales_with_text(self):
        tts = FakeTtsBackend()
        short = tts.synthesize(SpeechRequest(text="hola"))
        long_ = tts.synthesize(SpeechRequest(text="hola " * 50))
        self.assertGreater(long_.duration_ms, short.duration_ms)
        self.assertEqual(len(long_.audio_data or b""), int(22050 * long_.duration_ms / 1000) * 2)


class TestVisionFake(unittest.TestCase):
    def test_protocol(self):
        self.assertIsInstance(FakeVisionBackend(), VisionBackend)

    def test_presence_lifecycle(self):
        vision = FakeVisionBackend()
        self.assertFalse(vision.get_latest_presence().present)
        vision.start()
        vision.set_presence(True, faces_count=1, x=0.25, y=-0.5, confidence=0.9)
        obs = vision.get_latest_presence()
        self.assertTrue(obs.present)
        self.assertEqual(obs.faces_count, 1)
        self.assertEqual(obs.primary_x_normalized, 0.25)
        vision.stop()
        self.assertFalse(vision.get_latest_presence().present)


class TestNullFace(unittest.TestCase):
    def test_protocol(self):
        self.assertIsInstance(NullFaceController(), FaceController)

    def test_gaze_clamped(self):
        face = NullFaceController()
        face.set_gaze(5.0, -5.0)
        self.assertEqual(face.gaze, (1.0, -1.0))

    def test_sleep_wake(self):
        face = NullFaceController()
        face.sleep()
        self.assertTrue(face.sleeping)
        face.wake()
        self.assertFalse(face.sleeping)


class TestTools(unittest.TestCase):
    def test_protocols(self):
        for tool in (ClockTool(), FakeVolumeTool(), FakeNotesTool()):
            self.assertIsInstance(tool, Tool)

    def test_clock_tool(self):
        result = ClockTool().execute({}, ToolContext())
        self.assertTrue(result.success)
        self.assertIn("time", result.data)

    def test_volume_tool_validates_range(self):
        tool = FakeVolumeTool()
        with self.assertRaises(ValueError):
            tool.execute({"level": 101}, ToolContext())
        with self.assertRaises(ValueError):
            tool.execute({"level": "alto"}, ToolContext())
        result = tool.execute({"level": 42}, ToolContext())
        self.assertEqual(result.data["level"], 42)

    def test_notes_tool(self):
        tool = FakeNotesTool()
        self.assertFalse(tool.execute({"action": "add"}, ToolContext()).success)
        tool.execute({"action": "add", "text": "REGN mide 6,05 V"}, ToolContext())
        result = tool.execute({"action": "list"}, ToolContext())
        self.assertEqual(result.data["notes"], ["REGN mide 6,05 V"])

    def test_validate_args_rejects_unknown(self):
        schema = {"properties": {"x": {"type": "int", "required": True}}}
        with self.assertRaises(ValueError):
            validate_args(schema, {"x": 1, "y": 2})
        with self.assertRaises(ValueError):
            validate_args(schema, {})
        self.assertEqual(validate_args(schema, {"x": 1}), {"x": 1})


class TestRegistry(unittest.TestCase):
    def test_fake_backends_complete(self):
        backends = build_fake_backends()
        self.assertIsInstance(backends.ai, AiBackend)
        self.assertIsInstance(backends.stt, SttBackend)
        self.assertIsInstance(backends.tts, TtsBackend)
        self.assertIsInstance(backends.vision, VisionBackend)
        tool_map = backends.tool_map()
        self.assertIn("clock", tool_map)
        self.assertIn("volume", tool_map)
        self.assertIn("notes", tool_map)


if __name__ == "__main__":
    unittest.main()

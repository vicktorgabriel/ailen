"""Setup page uses measured hardware and effective configuration only."""

import re

from ailen.core.config import AILENConfig
from ailen.domain.enums import DeviceProfile
from ailen.domain.models import (
    AudioDeviceInfo,
    CameraInfo,
    CpuInfo,
    DiskInfo,
    GpuInfo,
    HardwareReport,
    MemoryInfo,
    OsInfo,
)
from ailen.services.settings_service import FIELD_SPECS
from ailen.web.setup_view import NO_MEASUREMENT, setup_context
from ailen.web.templates import render


def _hardware() -> HardwareReport:
    return HardwareReport(
        cpu=CpuInfo(
            model="CPU de prueba",
            arch="x86_64",
            cores_physical=6,
            cores_logical=12,
            frequency_mhz=3600.0,
        ),
        memory=MemoryInfo(total_mb=16384.0, available_mb=8192.0),
        disk=DiskInfo(mount_point="/", total_gb=500.0, free_gb=250.0),
        gpu=GpuInfo(detected=True, name="GPU de prueba", driver="driver-test"),
        audio_inputs=[
            AudioDeviceInfo(index=1, name="Micrófono de prueba", is_input=True,
                            is_output=False, is_default=True)
        ],
        audio_outputs=[
            AudioDeviceInfo(index=2, name="Parlantes de prueba", is_input=False,
                            is_output=True, is_default=True)
        ],
        cameras=[CameraInfo(device_path="/dev/video9", name="Cámara de prueba",
                            accessible=True)],
        os=OsInfo(
            system="Linux",
            release="6.1.0-test",
            distribution="Debian de prueba",
            kernel_version="6.1.0-test-kernel",
        ),
        recommended_profile=DeviceProfile.LOCAL,
        timestamp="2026-10-23T00:00:00+00:00",
    )


def _config() -> AILENConfig:
    cfg = AILENConfig()
    cfg.node.name = "Nodo efectivo"
    cfg.node.profile = DeviceProfile.LAN_BRAIN
    cfg.identity.display_name = "Personaje efectivo"
    cfg.audio.input_device = "pipewire:mic-test"
    cfg.audio.output_device = "plughw:CARD=test,DEV=0"
    cfg.audio.capture_gain_db = 3.5
    cfg.audio.auto_gain_enabled = True
    cfg.vision.enabled = False
    cfg.vision.camera_device = "/dev/video9"
    cfg.speech.stt_engine = "whisper_cpp"
    cfg.speech.tts_engine = "piper"
    cfg.speech.tts_voice = "es-test-voice"
    cfg.ai.provider = "local"
    cfg.ai.allow_remote = False
    return cfg


def test_context_reflects_effective_configuration_and_hardware():
    context = setup_context(_hardware(), _config())

    assert context["cpu_name"] == "CPU de prueba"
    assert context["cpu_cores"] == "12"
    assert context["ram_total_mb"] == "16384"
    assert context["rec_profile"] == "LOCAL"
    assert context["node_name"] == "Nodo efectivo"
    assert context["node_profile"] == "LAN_BRAIN"
    assert context["identity_name"] == "Personaje efectivo"
    assert context["audio_input_device"] == "pipewire:mic-test"
    assert context["audio_output_device"] == "plughw:CARD=test,DEV=0"
    assert context["audio_capture_gain"] == "3.5 dB"
    assert context["audio_agc"] == "Habilitado"
    assert context["vision_enabled"] == "Deshabilitada"
    assert context["vision_camera_device"] == "/dev/video9"
    assert context["speech_stt_engine"] == "whisper_cpp"
    assert context["speech_tts_engine"] == "piper"
    assert context["speech_tts_voice"] == "es-test-voice"
    assert context["ai_provider"] == "local"
    assert context["ai_remote"] == "Bloqueados"


def test_context_without_hardware_marks_it_undetected():
    context = setup_context(None, _config())

    assert context["hw_status"] == "Hardware no detectado"
    assert "Hardware no detectado" in context["hardware_html"]
    assert context["ram_total_mb"] == NO_MEASUREMENT
    assert context["rec_profile"] == NO_MEASUREMENT
    body = render("setup.html", **context)
    assert "8192" not in body
    assert "Hardware no detectado" in body


def test_rendered_page_has_no_placeholders_or_invented_steps():
    context = setup_context(_hardware(), _config())
    body = render("setup.html", **context)

    assert "{{" not in body
    for removed in (
        "AILÉN 100% operativa",
        "Paso 1 de 4",
        "2. Voz & Mic",
        "3. Identidad",
        "4. Finalizar",
        "respuesta instantánea",
        "hardware es óptimo",
    ):
        assert removed not in body
    assert "Paso único: revisión de hardware" in body
    assert "ProvisioningPlan" in body
    assert "no una certificación" in body
    for route in ("/audio", "/ia", "/vision", "/personalidad"):
        assert f'href="{route}"' in body


def test_user_supplied_values_are_escaped():
    hw = _hardware()
    hw.cpu.model = '<script>alert("cpu")</script>'
    hw.os.distribution = "<b>distro</b>"
    cfg = _config()
    cfg.identity.display_name = '<img src=x onerror="alert(1)">'
    cfg.node.name = "<u>node</u>"

    body = render("setup.html", **setup_context(hw, cfg))

    assert '<script>alert("cpu")</script>' not in body
    assert "&lt;script&gt;alert" in body
    assert "<b>distro</b>" not in body
    assert "&lt;b&gt;distro&lt;/b&gt;" in body
    assert '<img src=x onerror="alert(1)">' not in body
    assert "&lt;img src=x" in body
    assert "<u>node</u>" not in body


def test_template_only_uses_allowlisted_setting_fields():
    template = (render("setup.html", **_context_for_allowlist()))
    names = set(re.findall(r'name="([^"]+)"', template))
    allowed = {spec.key for spec in FIELD_SPECS}

    assert names - {"_csrf", "section"} <= allowed


def _context_for_allowlist():
    return setup_context(_hardware(), _config())

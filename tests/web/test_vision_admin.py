"""Tests for /vision context builder and template rendering with real config data."""

from ailen.core.config import AILENConfig
from ailen.services.settings_service import FIELD_SPECS
from ailen.web.templates import clear_cache, render
from ailen.web.vision_view import vision_context


def test_vision_context_reflects_effective_config_values() -> None:
    cfg = AILENConfig()
    cfg.vision.enabled = False
    cfg.vision.camera_source = "rtsp"
    cfg.vision.camera_device = "/dev/video2"
    cfg.vision.detector = "yunet"
    cfg.vision.fps = 24
    cfg.vision.detector_score_threshold = 0.65
    cfg.vision.presence_confirm_seconds = 1.4
    cfg.vision.absence_confirm_seconds = 3.5
    cfg.social.auto_greeting_enabled = False

    ctx = vision_context(cfg)

    assert ctx["vision_status"] == "Deshabilitada"
    assert ctx["detector_label"] == "yunet"
    assert ctx["chk_vision_enabled"] == ""
    assert ctx["sel_cam_auto"] == ""
    assert ctx["sel_cam_usb"] == ""
    assert ctx["sel_cam_rtsp"] == " selected"
    assert ctx["camera_device"] == "/dev/video2"
    assert ctx["sel_det_yunet"] == " selected"
    assert ctx["sel_det_haar"] == ""
    assert ctx["val_fps"] == "24"
    assert ctx["val_face_conf"] == "0.65"
    assert ctx["entry_debounce"] == "1.4"
    assert ctx["exit_debounce"] == "3.5"
    assert ctx["chk_auto_greet"] == ""
    assert ctx["vision_metrics"] == "Sin medición"
    assert ctx["sensor_status"] == "No disponible"


def test_vision_template_renders_without_unreplaced_placeholders_or_synthetic_copy() -> None:
    clear_cache()
    cfg = AILENConfig()
    ctx = vision_context(cfg)
    ctx["csrf"] = "csrf-token-123"

    html = render("vision.html", **ctx)

    assert "{{" not in html
    assert "}}" not in html
    assert 'name="_csrf" value="csrf-token-123"' in html
    assert "Sin medición" in html
    assert "No disponible" in html

    for forbidden in (
        "NC250",
        "49ms",
        "92%",
        "showAlert(",
        'value="500"',
        'value="2000"',
        'min="70"',
        'max="98"',
    ):
        assert forbidden not in html

    allowed_keys = {spec.key for spec in FIELD_SPECS}
    for field_name in (
        "vision.enabled",
        "vision.camera_source",
        "vision.camera_device",
        "vision.detector",
        "vision.fps",
        "vision.detector_score_threshold",
        "vision.presence_confirm_seconds",
        "vision.absence_confirm_seconds",
        "social.auto_greeting_enabled",
    ):
        assert field_name in allowed_keys
        assert f'name="{field_name}"' in html


def test_vision_template_escapes_html_in_user_controlled_config() -> None:
    clear_cache()
    cfg = AILENConfig()
    cfg.vision.camera_device = '"><script>alert("xss")</script>'
    ctx = vision_context(cfg)
    ctx["csrf"] = '"><img src=x onerror=alert(1)>'

    html = render("vision.html", **ctx)

    assert "<script>alert(" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html

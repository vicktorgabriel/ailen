"""Face admin view: real DisplayConfig values, allowlist compliance and HTML escaping."""

import re

from ailen.core.config import AILENConfig
from ailen.services.settings_service import FIELD_SPECS
from ailen.web.face_view import NO_AVAILABLE, NO_MEASUREMENT, face_context
from ailen.web.templates import render


def _configured() -> AILENConfig:
    cfg = AILENConfig()
    cfg.display.enabled = False
    cfg.display.fullscreen = False
    cfg.display.face_style = "vector"
    cfg.display.fps_limit = 24
    cfg.display.width = 1024
    cfg.display.height = 600
    cfg.display.backend = "drm"
    cfg.display.facepack_path = "runtime/facepacks/custom.facepack"
    return cfg


def test_face_context_reflects_effective_config() -> None:
    ctx = face_context(_configured())

    assert ctx["display_status"] == "Deshabilitado"
    assert ctx["chk_display_enabled"] == ""
    assert ctx["chk_fullscreen"] == ""
    assert ctx["face_style"] == "vector"
    assert ctx["sel_style_facepack"] == ""
    assert ctx["sel_style_portrait"] == ""
    assert ctx["sel_style_pixel"] == ""
    assert ctx["sel_style_vector"] == " selected"
    assert ctx["val_fps_limit"] == "24"
    assert ctx["display_width"] == "1024"
    assert ctx["display_height"] == "600"
    assert ctx["display_resolution"] == "1024x600"
    assert ctx["display_backend"] == "drm"
    assert ctx["facepack_path"] == "runtime/facepacks/custom.facepack"
    assert ctx["face_metrics"] == NO_MEASUREMENT
    assert ctx["live_expression_state"] == NO_AVAILABLE


def test_face_context_defaults_and_missing_values() -> None:
    cfg = AILENConfig()
    cfg.display.backend = "   "
    cfg.display.facepack_path = ""
    cfg.display.width = 0
    cfg.display.height = 0
    ctx = face_context(cfg)

    assert ctx["display_status"] == "Habilitado"
    assert ctx["chk_display_enabled"] == " checked"
    assert ctx["chk_fullscreen"] == " checked"
    assert ctx["sel_style_facepack"] == " selected"
    assert ctx["display_backend"] == NO_AVAILABLE
    assert ctx["facepack_path"] == NO_AVAILABLE
    assert ctx["display_width"] == NO_AVAILABLE
    assert ctx["display_height"] == NO_AVAILABLE
    assert ctx["display_resolution"] == NO_AVAILABLE


def test_rendered_template_has_no_placeholders_or_synthetic_copy() -> None:
    ctx = face_context(_configured())
    ctx["csrf"] = "csrf-test-token"
    body = render("face.html", **ctx)

    assert "{{" not in body
    assert "}}" not in body
    for removed in (
        "60 FPS",
        "0 ms latencia",
        "32-Bit High-Resolution Character",
        "Parpadeo de Prueba",
        "Probador de Expresiones",
        "Animación en tiempo real",
        "display.theme",
        "cyan_cyber",
        "amber_pixel",
        "emerald_pixel",
        "AILÉN renderiza",
        "btn-expr",
        "pixel-face-svg",
    ):
        assert removed not in body

    assert 'value="csrf-test-token"' in body
    assert "1024x600" in body
    assert "drm" in body
    assert "runtime/facepacks/custom.facepack" in body
    assert NO_MEASUREMENT in body
    assert NO_AVAILABLE in body


def test_template_only_uses_allowlisted_display_fields() -> None:
    body = render("face.html", **face_context(AILENConfig()))
    names = {
        name
        for name in re.findall(r'name="([^"]+)"', body)
        if name not in {"_csrf", "section"} and not name.startswith("__present.")
    }
    allowed_display = {
        spec.key for spec in FIELD_SPECS if spec.key.startswith("display.")
    }

    assert names == allowed_display


def test_user_supplied_values_are_html_escaped() -> None:
    cfg = _configured()
    cfg.display.backend = '<script>alert("xss")</script>'
    cfg.display.facepack_path = '"><img src=x onerror="alert(1)">'
    cfg.display.face_style = "<b>custom</b>"

    body = render("face.html", **face_context(cfg))

    assert '<script>alert("xss")</script>' not in body
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in body
    assert '<img src=x onerror="alert(1)">' not in body
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in body
    assert "<b>custom</b>" not in body
    assert "&lt;b&gt;custom&lt;/b&gt;" in body

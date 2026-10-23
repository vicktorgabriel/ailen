"""Tests for /herramientas context builder and template rendering with real config data."""

import re

from ailen.core.config import AILENConfig
from ailen.domain.enums import SocialMode
from ailen.services.settings_service import FIELD_SPECS
from ailen.web.templates import clear_cache, render
from ailen.web.tools_view import CONTRACT_IMPLEMENTED, NO_AVAILABLE, NO_MEASUREMENT, tools_context


def test_tools_context_reflects_effective_config_values() -> None:
    default_cfg = AILENConfig()
    default_ctx = tools_context(default_cfg)

    assert default_ctx["chk_web_search"] == ""
    assert default_ctx["sel_none"] == " selected"
    assert default_ctx["sel_ddgs"] == ""
    assert default_ctx["sel_reg_ar"] == " selected"
    assert default_ctx["sel_reg_es"] == ""
    assert default_ctx["sel_reg_wt"] == ""
    assert default_ctx["web_search_provider"] == "none"
    assert default_ctx["web_search_region"] == "ar-es"
    assert default_ctx["outbound_status"] == "Red saliente deshabilitada"
    assert default_ctx["tool_latency"] == NO_MEASUREMENT
    assert NO_AVAILABLE in default_ctx["live_runtime_status"]
    assert "proceso Lab no es visible desde serve" in default_ctx["live_runtime_status"]
    assert default_ctx["ssrf_status"] == CONTRACT_IMPLEMENTED
    assert default_ctx["tools_count"] == "11"

    cfg = AILENConfig()
    cfg.network.outbound_web_enabled = True
    cfg.network.web_search_provider = "ddgs"
    cfg.network.web_search_region = "es-es"
    cfg.social.default_mode = SocialMode.PUBLIC
    cfg.memory.sqlite_path = "runtime/custom_notes.db"
    cfg.memory.fts_enabled = False
    cfg.audio.output_device = "pipewire:custom-sink"
    cfg.audio.output_volume = 45
    cfg.audio.music_volume = 35
    cfg.vision.enabled = False
    cfg.display.enabled = False

    ctx = tools_context(cfg)

    assert ctx["chk_web_search"] == " checked"
    assert ctx["sel_ddgs"] == " selected"
    assert ctx["sel_none"] == ""
    assert ctx["sel_reg_ar"] == ""
    assert ctx["sel_reg_es"] == " selected"
    assert ctx["sel_reg_wt"] == ""
    assert ctx["web_search_provider"] == "ddgs"
    assert ctx["web_search_region"] == "es-es"
    assert ctx["social_mode"] == "PUBLIC"
    assert "es-es" in ctx["web_search_availability"]
    assert "runtime/custom_notes.db" in ctx["tools_rows"]
    assert "FTS deshabilitado" in ctx["tools_rows"]
    assert "pipewire:custom-sink (45%)" in ctx["tools_rows"]
    assert "35%" in ctx["tools_rows"]
    assert "vision.enabled=false" in ctx["tools_rows"]
    assert "Display deshabilitado/headless en config" in ctx["tools_rows"]
    assert "Bloqueada en modo PUBLIC" in ctx["tools_rows"]
    for tool_name in (
        "clock",
        "timer",
        "notes",
        "reminders",
        "volume",
        "music",
        "system_status",
        "camera",
        "face_expression",
        "web_search",
        "web_fetch",
    ):
        assert f"<code>{tool_name}</code>" in ctx["tools_rows"]


def test_tools_template_renders_without_unreplaced_placeholders_or_synthetic_copy() -> None:
    clear_cache()
    cfg = AILENConfig()
    ctx = tools_context(cfg)
    ctx["csrf"] = "csrf-tools-token"

    html = render("tools.html", **ctx)

    assert "{{" not in html
    assert "}}" not in html
    assert 'name="_csrf" value="csrf-tools-token"' in html
    assert 'name="section" value="tools"' in html
    assert CONTRACT_IMPLEMENTED in html
    assert NO_MEASUREMENT in html
    assert NO_AVAILABLE in html
    assert "no es visible desde" in html

    for forbidden in (
        "~8ms",
        "8ms",
        "Sanitizada",
        "Activo (Core Guard)",
        "Core Guard",
        "DuckDuckGo",
        "MprisTool",
        "Timers acústicos en background",
        ">Habilitada<",
        'name="section" value="network"',
    ):
        assert forbidden not in html

    names = set(re.findall(r'name="([^"]+)"', html))
    allowed = {spec.key for spec in FIELD_SPECS}
    form_fields = {
        name
        for name in names
        if name not in {"_csrf", "section"} and not name.startswith("__present.")
    }
    present_markers = {
        name.removeprefix("__present.")
        for name in names
        if name.startswith("__present.")
    }
    assert form_fields == {
        "network.outbound_web_enabled",
        "network.web_search_provider",
        "network.web_search_region",
    }
    assert form_fields <= allowed
    assert present_markers <= allowed


def test_tools_template_escapes_html_in_user_controlled_config() -> None:
    clear_cache()
    cfg = AILENConfig()
    cfg.network.outbound_web_enabled = True
    cfg.network.web_search_provider = '<script>alert("provider")</script>'
    cfg.network.web_search_region = '"><img src=x onerror=alert("region")>'
    cfg.memory.sqlite_path = "<b>/tmp/evil.db</b>"
    cfg.audio.output_device = '<svg onload=alert("audio")>'

    ctx = tools_context(cfg)
    ctx["csrf"] = '"><script>alert("csrf")</script>'

    html = render("tools.html", **ctx)

    assert '<script>alert("provider")</script>' not in html
    assert '<img src=x onerror=alert("region")>' not in html
    assert "<b>/tmp/evil.db</b>" not in html
    assert '<svg onload=alert("audio")>' not in html
    assert '<script>alert("csrf")</script>' not in html

    assert "&lt;script&gt;alert(&quot;provider&quot;)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(&quot;region&quot;)&gt;" in html
    assert "&lt;b&gt;/tmp/evil.db&lt;/b&gt;" in html
    assert "&lt;svg onload=alert(&quot;audio&quot;)&gt;" in html
    assert "&lt;script&gt;alert(&quot;csrf&quot;)&lt;/script&gt;" in html

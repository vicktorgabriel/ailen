"""Personality admin view: real config values, honest copy and escaping."""

from ailen.core.config import AILENConfig
from ailen.domain.enums import DeviceProfile, SocialMode
from ailen.web.pers_view import personality_context
from ailen.web.templates import render


def _configured() -> AILENConfig:
    cfg = AILENConfig()
    cfg.identity.display_name = "Taller Norte"
    cfg.node.name = "Nodo Taller"
    cfg.node.profile = DeviceProfile.LOCAL
    cfg.social.default_mode = SocialMode.HOME
    cfg.social.auto_greeting_enabled = False
    cfg.social.greeting_cooldown_seconds = 420.5
    cfg.personality.description = "Tono breve y técnico"
    cfg.personality.base_humor = 0.83
    cfg.personality.base_sociability = 0.24
    cfg.personality.base_formality = 0.95
    cfg.personality.base_expressiveness = 0.11
    cfg.personality.evolution_enabled = False
    cfg.personality.evolution_rate = 0.25
    cfg.memory.sqlite_path = "runtime/test.db"
    cfg.memory.fts_enabled = False
    cfg.memory.retention_days = 30
    return cfg


def test_context_reflects_effective_config():
    ctx = personality_context(_configured())

    assert ctx["display_name"] == "Taller Norte"
    assert ctx["node_name"] == "Nodo Taller"
    assert ctx["node_profile"] == "LOCAL"
    assert ctx["val_desc"] == "Tono breve y técnico"
    assert ctx["chk_auto_greet"] == ""
    assert ctx["val_greet_cd"] == "420.5"
    assert ctx["val_greet_cd_max"] == "600"
    assert 'value="HOME" selected' in ctx["social_mode_options"]
    assert ctx["social_mode_options"].count(" selected") == 1
    assert ctx["memory_path"] == "runtime/test.db"
    assert ctx["memory_fts"] == "FTS deshabilitado"
    assert ctx["memory_retention"] == "30 días"
    assert ctx["evolution_state"] == "Deshabilitada"
    assert ctx["evolution_rate"] == "0.25"


def test_context_exposes_all_base_traits_on_the_config_scale():
    ctx = personality_context(_configured())
    sliders = ctx["trait_sliders"]

    for field in (
        "base_humor", "base_verbosity", "base_curiosity", "base_patience",
        "base_sociability", "base_formality", "base_expressiveness",
    ):
        assert f'name="personality.{field}"' in sliders
    assert 'value="0.83"' in sliders
    assert "83%" in sliders
    assert 'min="0" max="1"' in sliders


def test_cooldown_slider_can_represent_value_above_default_bound():
    cfg = _configured()
    cfg.social.greeting_cooldown_seconds = 720.0
    ctx = personality_context(cfg)
    assert ctx["val_greet_cd"] == "720"
    assert ctx["val_greet_cd_max"] == "720"


def test_defaults_do_not_use_a_hardcoded_character_name():
    ctx = personality_context(AILENConfig())
    assert ctx["display_name"] == "Asistente"


def test_rendered_template_has_no_placeholders_or_synthetic_copy():
    body = render("personality.html", csrf="csrf-token", **personality_context(_configured()))

    assert "{{" not in body and "}}" not in body
    for removed in (
        "Taller Electrónico",
        "100% aislada",
        "Core Local",
        "Latencia:",
        "Simular Respuesta",
        "Buenas. En el registro de hoy",
        "Ailén",
    ):
        assert removed not in body
    assert "Taller Norte" in body
    assert "420.5s" in body
    assert "HOME (hogar / cercano)" in body
    assert "No disponible" in body


def test_user_data_is_html_escaped():
    cfg = _configured()
    cfg.identity.display_name = '<script>alert("bad")</script>'
    cfg.personality.description = '<img src=x onerror="bad">'
    body = render("personality.html", csrf="csrf-token", **personality_context(cfg))

    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body
    assert "<img src=x" not in body
    assert "&lt;img" in body

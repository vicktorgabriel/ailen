"""La vista /sistema refleja sólo datos reales de AILENConfig."""

from pathlib import Path

from ailen.core.config import AILENConfig
from ailen.domain.enums import DeviceProfile
from ailen.web import sys_view
from ailen.web.sys_view import system_context
from ailen.web.templates import render


def test_context_reflects_effective_config(monkeypatch, tmp_path: Path) -> None:
    cfg = AILENConfig()
    cfg.node.name = "Nodo Taller"
    cfg.node.profile = DeviceProfile.LOCAL
    cfg.web.port = 9099
    cfg.memory.sqlite_path = str(tmp_path / "custom.db")
    config_path = tmp_path / "ailen.toml"
    monkeypatch.setattr(sys_view, "find_config_path", lambda: config_path)

    context = system_context(cfg, "runtime-node-7")

    assert context["csrf"] == ""
    assert context["node_name"] == "Nodo Taller"
    assert context["node_id"] == "runtime-node-7"
    assert context["web_port"] == "9099"
    assert context["db_path"] == str(tmp_path / "custom.db")
    assert context["config_path"] == str(config_path)
    assert 'value="LOCAL" selected' in context["profile_options"]
    assert 'value="HYBRID" selected' not in context["profile_options"]


def test_template_renders_without_placeholders_or_fictional_text() -> None:
    cfg = AILENConfig()
    context = system_context(cfg, "node-test")
    context["csrf"] = "token-123"

    body = render("system.html", **context)

    assert "{{" not in body
    assert 'name="_csrf" value="token-123"' in body
    assert 'name="node.name"' in body
    assert 'name="node.profile"' in body
    assert 'name="section" value="node"' in body
    assert 'value="HYBRID" selected' in body
    for profile in DeviceProfile:
        assert f'value="{profile.value}"' in body

    removed = (
        "runtime/lab/ailen_lab.db",
        "Recarga segura",
        "btn-restart-svc",
        "Core Engine",
        "IA Router",
        "Audio PipeWire",
        "Visión YuNet",
        "Aislamiento de Secretos",
        "Permisos 0600",
        "8GB",
        "48GB",
    )
    for text in removed:
        assert text not in body


def test_user_data_is_escaped_in_template() -> None:
    cfg = AILENConfig()
    cfg.node.name = 'Nodo <script>alert("x")</script>'
    context = system_context(cfg, '<img src=x onerror=alert(1)>')
    context["csrf"] = '"><script>alert(2)</script>'

    body = render("system.html", **context)

    assert 'Nodo <script>alert("x")</script>' not in body
    assert "Nodo &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body
    assert "&quot;&gt;&lt;script&gt;alert(2)&lt;/script&gt;" in body

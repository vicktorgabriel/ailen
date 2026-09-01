"""Unit tests for AI CLI commands."""

import json
from pathlib import Path

from ailen.cli import main
from ailen.core.config import AILENConfig, dump_config_toml


def test_cli_diagnose_ai_text(capsys) -> None:
    code = main(["diagnose", "ai"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AILEN AI Diagnostics" in captured.out
    assert "Perfil" in captured.out
    assert "Local" in captured.out
    assert "remote:" in captured.out


def test_cli_diagnose_ai_json(capsys) -> None:
    code = main(["diagnose", "ai", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "node_profile" in data
    assert "local" in data
    assert "lan_brain" in data
    assert "remote_providers" in data


def test_cli_demo_ai_dry_run(capsys) -> None:
    code = main(["demo", "ai", "Hola cómo estás", "--dry-run"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AILEN AI Demo — canonical adaptive routing" in captured.out
    assert "DRY-RUN" in captured.out


def test_cli_demo_ai_intent_volume(capsys) -> None:
    code = main(["demo", "ai", "bajar volumen", "--intent", "volume", "--dry-run"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Destino primario : rule" in captured.out
    assert "RULE_ONLY_INTENT" in captured.out


def test_cli_demo_auto_excludes_remote_that_is_not_qualified(
    tmp_path: Path, capsys
) -> None:
    cfg = AILENConfig()
    cfg.ai.provider = "auto"
    cfg.ai.local.enabled = False
    cfg.ai.allow_remote = True
    cfg.ai.allow_sanitized_external_prompts = True
    remote = cfg.ai.remote.providers["openai"]
    remote.enabled = True
    remote.model = "operator-model"
    remote.qualification_status = "configured"
    config_path = tmp_path / "ailen.toml"
    config_path.write_text(dump_config_toml(cfg), encoding="utf-8")

    code = main(
        ["-c", str(config_path), "demo", "ai", "Hola", "--dry-run"]
    )

    assert code == 0
    assert "Destino primario : degraded" in capsys.readouterr().out

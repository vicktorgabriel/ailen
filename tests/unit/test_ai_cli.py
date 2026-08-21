"""Unit tests for AI CLI commands."""

import json

from ailen.cli import main


def test_cli_diagnose_ai_text(capsys) -> None:
    code = main(["diagnose", "ai"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AILEN AI Diagnostics" in captured.out
    assert "Perfil de Dispositivo" in captured.out
    assert "Local LLM Server" in captured.out
    assert "Presupuesto Cloud" in captured.out


def test_cli_diagnose_ai_json(capsys) -> None:
    code = main(["diagnose", "ai", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "node_profile" in data
    assert "local" in data
    assert "lan_brain" in data
    assert "cloud" in data
    assert "budget" in data


def test_cli_demo_ai_dry_run(capsys) -> None:
    code = main(["demo", "ai", "Hola cómo estás", "--dry-run"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AILEN AI Demo — Hybrid Routing & Context" in captured.out
    assert "DRY-RUN" in captured.out


def test_cli_demo_ai_intent_volume(capsys) -> None:
    code = main(["demo", "ai", "bajar volumen", "--intent", "volume", "--dry-run"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Destino Primario : RULE" in captured.out
    assert "RULE_ONLY_INTENT" in captured.out

"""Unit tests for RuntimeModelInventory inspecting Ollama and OpenAI runtime endpoints."""

import json
from unittest.mock import MagicMock, patch

from ailen.runtime.inventory import RuntimeModelInventory


def test_inventory_list_openai_models() -> None:
    inv = RuntimeModelInventory(timeout=0.1)

    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.read.return_value = json.dumps({
        "data": [
            {"id": "qwen3.5-0.8b-q4_0", "object": "model"},
            {"id": "llama-3.2-1b", "object": "model"},
        ]
    }).encode("utf-8")
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=fake_response):
        models = inv.list_models("http://127.0.0.1:8080/v1")
        assert "qwen3.5-0.8b-q4_0" in models
        assert "llama-3.2-1b" in models


def test_inventory_list_ollama_tags_fallback() -> None:
    inv = RuntimeModelInventory(timeout=0.1)

    # First call (/models) fails, second call (/api/tags) succeeds
    resp_tags = MagicMock()
    resp_tags.status = 200
    resp_tags.read.return_value = json.dumps({
        "models": [
            {"name": "qwen2.5:0.5b", "size": 397759536},
            {"name": "llama3.2:1b", "size": 810000000},
        ]
    }).encode("utf-8")
    resp_tags.__enter__.return_value = resp_tags
    resp_tags.__exit__.return_value = False

    with patch("urllib.request.urlopen", side_effect=[Exception("404"), resp_tags]):
        models = inv.list_models("http://127.0.0.1:11434/v1")
        assert "qwen2.5:0.5b" in models
        assert "llama3.2:1b" in models


def test_inventory_has_model_exact_and_alias() -> None:
    inv = RuntimeModelInventory(timeout=0.1)

    with patch.object(inv, "list_models", return_value=["qwen3.5:0.8b", "qwen3.5:9b", "llama3.2:1b"]):
        assert inv.has_model("http://127.0.0.1:11434", "qwen3.5:9b") is True
        assert inv.resolve_model(
            "http://127.0.0.1:11434",
            "qwen3.5-0.8b-q8_0",
            aliases=["qwen3.5:0.8b"],
        ) == "qwen3.5:0.8b"

        # Never fuzzy-match a different size merely because the family prefix matches.
        assert inv.has_model(
            "http://127.0.0.1:11434",
            "qwen3.5-4b-q8_0",
            aliases=["qwen3.5:4b"],
        ) is False
        assert inv.has_model("http://127.0.0.1:11434", "deepseek-r1:70b") is False

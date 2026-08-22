"""Unit tests for ModelBenchmarkRunner."""

from unittest.mock import MagicMock, patch

from ailen.ai.contracts import AiResponse, AiUsage
from ailen.runtime.inventory import RuntimeModelInventory
from ailen.runtime.model_benchmark import ModelBenchmarkRunner


def test_structural_evaluation_heuristics() -> None:
    runner = ModelBenchmarkRunner()

    # Empty text
    is_empty, is_sp, s_pass = runner.evaluate_structural("")
    assert is_empty
    assert not s_pass

    # Non-spanish or code fence
    _, _, s_pass_json = runner.evaluate_structural("```json\n{\"foo\": 1}\n```")
    assert not s_pass_json

    # Valid Spanish sentence
    is_empty, is_sp, s_pass = runner.evaluate_structural("La fotosíntesis es el proceso por el cual las plantas producen energía.")
    assert not is_empty
    assert is_sp
    assert s_pass


def test_uninstalled_model_reports_not_installed() -> None:
    inv = MagicMock(spec=RuntimeModelInventory)
    inv.list_models.return_value = ["qwen3.5:9b"]

    runner = ModelBenchmarkRunner(inventory=inv)
    report = runner.run_benchmark(
        candidate_models=["llama3.2:3b", "gemma3:4b"],
        warmup_turns=1,
    )

    assert len(report.models_evaluated) == 2
    assert report.models_evaluated[0].status == "NOT_INSTALLED"
    assert report.models_evaluated[1].status == "NOT_INSTALLED"


@patch("ailen.runtime.model_benchmark.LocalAiBackend")
def test_installed_model_benchmark_execution(mock_backend_cls: MagicMock) -> None:
    inv = MagicMock(spec=RuntimeModelInventory)
    inv.list_models.return_value = ["qwen3.5:9b"]
    inv.is_ollama_endpoint.return_value = False

    mock_backend = MagicMock()
    mock_backend.generate.return_value = AiResponse(
        text="Hola, soy AILEN y estoy lista para ayudarte.",
        finish_reason="stop",
        latency_ms=120.0,
        provider="local_llm",
        model="qwen3.5:9b",
        usage=AiUsage(input_tokens=10, output_tokens=12),
    )
    mock_backend_cls.return_value = mock_backend

    runner = ModelBenchmarkRunner(inventory=inv)
    report = runner.run_benchmark(
        candidate_models=["qwen3.5:9b"],
        warmup_turns=1,
        max_prompts=2,
    )

    assert len(report.models_evaluated) == 1
    m = report.models_evaluated[0]
    assert m.status == "PASS"
    assert m.turns_evaluated == 2
    assert m.warm_latency_avg_ms == 120.0
    assert m.tokens_per_second_avg is None
    assert m.structural_pass_rate == 100.0


@patch("ailen.runtime.model_benchmark.OllamaNativeBackend")
def test_installed_ollama_model_uses_native_backend(mock_backend_cls: MagicMock) -> None:
    inv = MagicMock(spec=RuntimeModelInventory)
    inv.list_models.return_value = ["qwen3.5:9b"]
    inv.is_ollama_endpoint.return_value = True
    backend = MagicMock()
    backend.generate.return_value = AiResponse(
        text="La respuesta es breve y clara.",
        finish_reason="stop",
        latency_ms=80.0,
        provider="ollama",
        model="qwen3.5:9b",
        usage=AiUsage(input_tokens=8, output_tokens=7, generation_tokens_per_second=55.5),
    )
    mock_backend_cls.return_value = backend

    report = ModelBenchmarkRunner(inventory=inv).run_benchmark(
        candidate_models=["qwen3.5:9b"], warmup_turns=1, max_prompts=1
    )

    assert report.models_evaluated[0].status == "PASS"
    assert report.models_evaluated[0].tokens_per_second_avg == 55.5
    mock_backend_cls.assert_called_once()
    assert mock_backend_cls.call_args.kwargs["think"] is False
    assert mock_backend_cls.call_args.kwargs["keep_alive"] == "10m"

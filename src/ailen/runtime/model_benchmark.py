"""Reproducible local model benchmark runner evaluating installed Ollama/llama.cpp models."""

import logging
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from ailen.ai.contracts import AiBackend, AiRequest, ChatMessage
from ailen.ai.local_backend import LocalAiBackend
from ailen.ai.ollama_backend import OllamaNativeBackend
from ailen.runtime.inventory import RuntimeModelInventory

logger = logging.getLogger(__name__)

# Standard Spanish benchmark battery oriented to AILEN conversational turns
DEFAULT_BENCHMARK_PROMPTS = [
    {"id": "greeting", "prompt": "Hola, ¿cómo estás hoy?", "expected_intent": "saludo"},
    {"id": "simple_explanation", "prompt": "Explicá en dos oraciones simples qué es la fotosíntesis.", "expected_intent": "explicacion"},
    {"id": "tech_concept", "prompt": "¿Cuál es la diferencia básica entre memoria RAM y almacenamiento en disco?", "expected_intent": "tecnico"},
    {"id": "summarize", "prompt": "Resumí en una frase: El calor del sol evapora el agua que luego forma nubes y cae como lluvia.", "expected_intent": "resumen"},
    {"id": "action_request", "prompt": "Confirmá si podés poner un temporizador de 5 minutos.", "expected_intent": "accion"},
    {"id": "general_knowledge", "prompt": "¿En qué continente está Argentina y cuál es su idioma oficial?", "expected_intent": "conocimiento"},
]


@dataclass
class PromptResult:
    """Individual prompt execution benchmark result."""
    prompt_id: str
    prompt_text: str
    response_text: str
    latency_ms: float
    is_warmup: bool
    input_tokens: int | None
    output_tokens: int | None
    tokens_per_sec: float | None
    is_empty: bool
    is_spanish: bool
    structural_pass: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelBenchmarkSummary:
    """Consolidated benchmark metrics for a single model candidate."""
    model_name: str
    status: str  # "PASS", "FAIL", "NOT_INSTALLED", "ERROR"
    first_turn_ms: float | None = None
    warm_latency_avg_ms: float | None = None
    warm_latency_p50_ms: float | None = None
    warm_latency_p95_ms: float | None = None
    total_output_tokens: int | None = None
    tokens_per_second_avg: float | None = None
    structural_pass_rate: float = 0.0
    turns_evaluated: int = 0
    prompt_results: list[PromptResult] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["prompt_results"] = [p.to_dict() for p in self.prompt_results]
        return d


@dataclass
class BenchmarkSuiteReport:
    """Full benchmark suite execution summary."""
    endpoint: str
    timestamp: int
    models_evaluated: list[ModelBenchmarkSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "timestamp": self.timestamp,
            "models_evaluated": [m.to_dict() for m in self.models_evaluated],
        }


class ModelBenchmarkRunner:
    """Orchestrates reproducible inference performance benchmarks without pulling external models."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434/v1",
        inventory: RuntimeModelInventory | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.inventory = inventory or RuntimeModelInventory()

    def evaluate_structural(self, text: str) -> tuple[bool, bool, bool]:
        """Check if output is non-empty, in Spanish, and structurally sound."""
        clean = text.strip()
        if not clean:
            return True, False, False  # is_empty=True, is_spanish=False, pass=False

        # Heuristic check for Spanish markers
        spanish_markers = {"el", "la", "de", "que", "en", "un", "una", "es", "por", "para", "con", "los", "las", "como", "está", "estás", "fotosíntesis", "minutos", "argentina", "memoria"}
        words = {w.lower().strip(".,!?:;\"'()[]{}") for w in clean.split()}
        overlap = words.intersection(spanish_markers)
        is_spanish = len(overlap) >= 1 or any(c in clean for c in "áéíóúñ¿¡")

        # Passes if non-empty, reasonably length (> 5 chars), and in Spanish
        structural_pass = bool(not clean.startswith("```json") and len(clean) >= 5 and is_spanish)
        return False, is_spanish, structural_pass

    def run_benchmark(
        self,
        candidate_models: list[str],
        warmup_turns: int = 1,
        max_prompts: int | None = None,
        prompts: list[dict[str, str]] | None = None,
    ) -> BenchmarkSuiteReport:
        """Run benchmark battery across candidate models."""
        active_models = self.inventory.list_models(self.endpoint)
        active_names = {m.lower() for m in active_models}

        test_prompts = prompts or DEFAULT_BENCHMARK_PROMPTS
        if max_prompts is not None and max_prompts > 0:
            test_prompts = test_prompts[:max_prompts]

        suite_results: list[ModelBenchmarkSummary] = []
        timestamp = int(time.time())

        for cand in candidate_models:
            clean_cand = cand.strip()
            if not clean_cand:
                continue

            # Check if model is installed in runtime
            is_installed = clean_cand.lower() in active_names

            if not is_installed:
                suite_results.append(ModelBenchmarkSummary(
                    model_name=clean_cand,
                    status="NOT_INSTALLED",
                    detail=f"Model '{clean_cand}' is not present in runtime inventory ({self.endpoint})",
                ))
                continue

            # Run evaluation on installed model
            summary = self._benchmark_single_model(
                model_name=clean_cand,
                warmup_turns=warmup_turns,
                prompts=test_prompts,
            )
            suite_results.append(summary)

        return BenchmarkSuiteReport(
            endpoint=self.endpoint,
            timestamp=timestamp,
            models_evaluated=suite_results,
        )

    def _benchmark_single_model(
        self,
        model_name: str,
        warmup_turns: int,
        prompts: list[dict[str, str]],
    ) -> ModelBenchmarkSummary:
        """Run warmups and prompt turns on a single installed model."""
        backend: AiBackend
        if self.inventory.is_ollama_endpoint(self.endpoint):
            backend = OllamaNativeBackend(
                endpoint=self.endpoint,
                model=model_name,
                timeout_seconds=30.0,
                think=False,
                keep_alive="10m",
            )
        else:
            backend = LocalAiBackend(
                endpoint=self.endpoint,
                model=model_name,
                timeout_seconds=30.0,
            )

        first_turn_ms: float | None = None
        results: list[PromptResult] = []
        warm_latencies: list[float] = []
        token_rates: list[float] = []
        total_tokens = 0
        tokens_available = False

        # 1. Warmup turns
        for i in range(max(1, warmup_turns)):
            req = AiRequest(
                request_id=f"warmup-{uuid4().hex[:8]}",
                messages=[ChatMessage(role="user", content="Hola, respondé 'OK' en una sola palabra.")],
                max_output_tokens=16,
                timeout_seconds=30.0,
            )
            resp = backend.generate(req)
            if i == 0:
                first_turn_ms = resp.latency_ms

        # 2. Benchmark turns
        for p in prompts:
            p_id = p.get("id", "prompt")
            p_text = p.get("prompt", "")

            req = AiRequest(
                request_id=f"bench-{uuid4().hex[:8]}",
                messages=[ChatMessage(role="user", content=p_text)],
                max_output_tokens=96,
                timeout_seconds=30.0,
            )
            resp = backend.generate(req)

            in_tok = resp.usage.input_tokens if resp.usage else None
            out_tok = resp.usage.output_tokens if resp.usage else None
            tps = resp.usage.generation_tokens_per_second if resp.usage else None
            if out_tok is not None:
                tokens_available = True
                total_tokens += out_tok
            if tps is not None:
                token_rates.append(tps)

            is_empty, is_spanish, s_pass = self.evaluate_structural(resp.text)
            warm_latencies.append(resp.latency_ms)

            results.append(PromptResult(
                prompt_id=p_id,
                prompt_text=p_text,
                response_text=resp.text,
                latency_ms=resp.latency_ms,
                is_warmup=False,
                input_tokens=in_tok,
                output_tokens=out_tok,
                tokens_per_sec=tps,
                is_empty=is_empty,
                is_spanish=is_spanish,
                structural_pass=s_pass,
            ))

        # 3. Compute statistical summary
        avg_lat = statistics.mean(warm_latencies) if warm_latencies else None
        p50_lat = statistics.median(warm_latencies) if warm_latencies else None
        p95_lat = None
        if warm_latencies:
            sorted_lat = sorted(warm_latencies)
            idx95 = int(len(sorted_lat) * 0.95)
            p95_lat = sorted_lat[min(idx95, len(sorted_lat) - 1)]

        avg_tps = statistics.mean(token_rates) if token_rates else None
        pass_count = sum(1 for r in results if r.structural_pass)
        pass_rate = round((pass_count / len(results)) * 100.0, 1) if results else 0.0

        status = "PASS" if (pass_rate >= 60.0 and avg_lat is not None and avg_lat < 15000.0) else "FAIL"

        return ModelBenchmarkSummary(
            model_name=model_name,
            status=status,
            first_turn_ms=round(first_turn_ms, 1) if first_turn_ms else None,
            warm_latency_avg_ms=round(avg_lat, 1) if avg_lat is not None else None,
            warm_latency_p50_ms=round(p50_lat, 1) if p50_lat is not None else None,
            warm_latency_p95_ms=round(p95_lat, 1) if p95_lat is not None else None,
            total_output_tokens=total_tokens if tokens_available else None,
            tokens_per_second_avg=round(avg_tps, 2) if avg_tps is not None else None,
            structural_pass_rate=pass_rate,
            turns_evaluated=len(results),
            prompt_results=results,
            detail=f"Evaluated {len(results)} turns with {pass_rate}% structural pass",
        )

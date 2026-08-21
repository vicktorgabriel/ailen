"""Local LLM inference backend for AILEN.

Connects to a decoupled local inference server (e.g. llama.cpp server, Ollama,
vLLM) running on the local host.
"""

from ailen.ai.http_backend import GenericOpenAiBackend


class LocalAiBackend(GenericOpenAiBackend):
    """Local LLM backend communicating via standard HTTP."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8080/v1",
        model: str = "local-model",
        timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model=model,
            api_key=None,
            timeout_seconds=timeout_seconds,
            provider_name="local_llm",
            is_local=True,
            requires_internet=False,
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
        )

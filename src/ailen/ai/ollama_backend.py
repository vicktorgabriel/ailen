"""Native Ollama backend for low-latency local conversation.

Uses Ollama's loopback `/api/chat` endpoint rather than the OpenAI-compatible
shim so thinking-capable models can explicitly run with `think=false`.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ailen.ai.contracts import (
    AiBackend,
    AiRequest,
    AiResponse,
    AiUsage,
    BackendCapabilities,
    BackendHealth,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger("ailen.ai.ollama")


class OllamaNativeBackend(AiBackend):
    """Local Ollama client using the native non-streaming chat API."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434/v1",
        model: str = "",
        timeout_seconds: float = 60.0,
        think: bool = False,
        keep_alive: str = "30m",
    ) -> None:
        base = endpoint.rstrip("/").removesuffix("/v1")
        parsed = urlparse(base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama native backend must use a loopback HTTP endpoint")
        self.endpoint = base.rstrip("/")
        self.model = model
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.think = think
        self.keep_alive = keep_alive

    def health(self) -> BackendHealth:
        if not self.model:
            return BackendHealth(ServiceStatus.DISABLED, "No Ollama model configured")
        req = urllib.request.Request(f"{self.endpoint}/api/tags", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=min(2.0, self.timeout_seconds)) as resp:
                if resp.status != 200:
                    return BackendHealth(ServiceStatus.UNHEALTHY, f"HTTP {resp.status}")
                raw = resp.read(1_000_001)
                if len(raw) > 1_000_000:
                    return BackendHealth(ServiceStatus.UNHEALTHY, "Ollama tags response too large")
                payload = json.loads(raw.decode("utf-8"))
                models = {str(item.get("name", "")) for item in payload.get("models", [])}
                if self.model not in models:
                    return BackendHealth(ServiceStatus.UNHEALTHY, f"Model not loaded/installed: {self.model}")
                return BackendHealth(ServiceStatus.HEALTHY, f"Ollama native API ready with {self.model}")
        except Exception as exc:  # noqa: BLE001
            return BackendHealth(ServiceStatus.DISABLED, f"Ollama unreachable: {exc}")

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_tools=False,
            supports_streaming=False,
            max_context_tokens=4096,
            is_local=True,
            requires_internet=False,
        )

    def warmup(self) -> bool:
        """Ask Ollama to load/retain this model without generating user-facing text."""
        if not self.model:
            return False
        payload = {
            "model": self.model,
            "prompt": "",
            "stream": False,
            "keep_alive": self.keep_alive,
        }
        req = urllib.request.Request(
            f"{self.endpoint}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                if resp.status != 200:
                    return False
                raw = resp.read(1_000_001)
                if len(raw) > 1_000_000:
                    return False
                data = json.loads(raw.decode("utf-8"))
                return bool(data.get("done", False))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama warmup failed for %s: %s", self.model, exc)
            return False

    def generate(self, request: AiRequest) -> AiResponse:
        start_t = time.monotonic()
        messages: list[dict[str, str]] = []
        system_parts: list[str] = []
        if request.system_context:
            system_parts.append(request.system_context)
        if request.retrieved_memory:
            system_parts.append("Información de contexto:\n" + "\n".join(f"- {m}" for m in request.retrieved_memory))
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        messages.extend({"role": msg.role, "content": msg.content} for msg in request.messages)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": request.max_output_tokens,
                "temperature": 0.4,
            },
        }
        req = urllib.request.Request(
            f"{self.endpoint}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = request.timeout_seconds or self.timeout_seconds
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(2_000_001)
                latency_ms = (time.monotonic() - start_t) * 1000.0
                if len(raw) > 2_000_000:
                    return self._failure("malformed_response", latency_ms)
                data = json.loads(raw.decode("utf-8"))
                message = data.get("message") or {}
                text = str(message.get("content") or "").strip()
                if not text:
                    return self._failure("empty_response", latency_ms)
                eval_count = data.get("eval_count")
                eval_duration = data.get("eval_duration")
                generation_tps: float | None = None
                if (
                    isinstance(eval_count, int)
                    and eval_count >= 0
                    and isinstance(eval_duration, int | float)
                    and eval_duration > 0
                ):
                    generation_tps = eval_count / (float(eval_duration) / 1_000_000_000.0)
                usage = AiUsage(
                    input_tokens=data.get("prompt_eval_count"),
                    output_tokens=eval_count,
                    estimated_cost=0.0,
                    currency="USD",
                    generation_tokens_per_second=generation_tps,
                )
                return AiResponse(
                    text=text,
                    finish_reason=str(data.get("done_reason") or "stop"),
                    usage=usage,
                    latency_ms=latency_ms,
                    provider="ollama",
                    model=str(data.get("model") or self.model),
                )
        except TimeoutError:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("Timeout connecting to native Ollama chat after %.1fs", timeout)
            return self._failure("timeout", latency_ms)
        except urllib.error.URLError as exc:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("Ollama native API unreachable: %s", exc.reason)
            return self._failure("unreachable", latency_ms)
        except (urllib.error.HTTPError, json.JSONDecodeError, OSError, ValueError) as exc:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("Ollama native API error: %s", exc)
            return self._failure("error", latency_ms)

    def _failure(self, finish_reason: str, latency_ms: float) -> AiResponse:
        return AiResponse(
            text="",
            finish_reason=finish_reason,
            latency_ms=latency_ms,
            provider="ollama",
            model=self.model,
        )

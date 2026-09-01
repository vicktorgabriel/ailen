"""Native Ollama backend for low-latency local conversation.

Uses Ollama's loopback `/api/chat` endpoint rather than the OpenAI-compatible
shim so thinking-capable models can explicitly run with `think=false`.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlparse

from ailen.ai.contracts import (
    AiBackend,
    AiRequest,
    AiResponse,
    AiUsage,
    BackendCapabilities,
    BackendHealth,
    StreamingAiBackend,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger("ailen.ai.ollama")


class OllamaNativeBackend(AiBackend, StreamingAiBackend):
    """Local Ollama client using the native non-streaming chat API."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434/v1",
        model: str = "",
        timeout_seconds: float = 60.0,
        think: bool = False,
        keep_alive: str = "30m",
        allow_remote: bool = False,
        context_tokens: int = 4096,
    ) -> None:
        base = endpoint.rstrip("/").removesuffix("/v1")
        parsed = urlparse(base)
        is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme not in {"http", "https"} or (not is_loopback and not allow_remote):
            raise ValueError(
                "Ollama native backend must use loopback unless trusted remote access is explicit"
            )
        self.endpoint = base.rstrip("/")
        self.model = model
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.think = think
        self.keep_alive = keep_alive
        self.allow_remote = allow_remote
        self.context_tokens = max(512, context_tokens)
        self._request_lock = threading.Lock()

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
            supports_streaming=True,
            max_context_tokens=self.context_tokens,
            is_local=True,
            requires_internet=False,
        )

    def warmup(self) -> bool:
        """Ask Ollama to load/retain this model without generating user-facing text."""
        with self._request_lock:
            return self._warmup_unlocked()

    def _warmup_unlocked(self) -> bool:
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

    def release_if_idle(self) -> bool:
        """Unload this model without stopping Ollama when no request is active."""
        if not self._request_lock.acquire(blocking=False):
            return False
        try:
            if not self.model:
                return False
            payload = {
                "model": self.model,
                "messages": [],
                "stream": False,
                "keep_alive": 0,
            }
            req = urllib.request.Request(
                f"{self.endpoint}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=min(2.0, self.timeout_seconds)) as resp:
                if resp.status != 200:
                    return False
                raw = resp.read(1_000_001)
                if len(raw) > 1_000_000:
                    return False
                data = json.loads(raw.decode("utf-8"))
                return bool(data.get("done", False))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama model release failed for %s: %s", self.model, exc)
            return False
        finally:
            self._request_lock.release()

    def generate(self, request: AiRequest) -> AiResponse:
        with self._request_lock:
            return self._generate_unlocked(request)

    def _generate_unlocked(self, request: AiRequest) -> AiResponse:
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
                "temperature": request.temperature,
                "num_ctx": self.context_tokens,
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
                prompt_eval_duration = data.get("prompt_eval_duration")
                load_duration = data.get("load_duration")
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
                    prompt_eval_ms=(
                        float(prompt_eval_duration) / 1_000_000.0
                        if isinstance(prompt_eval_duration, int | float)
                        else None
                    ),
                    generation_ms=(
                        float(eval_duration) / 1_000_000.0
                        if isinstance(eval_duration, int | float)
                        else None
                    ),
                    load_ms=(
                        float(load_duration) / 1_000_000.0
                        if isinstance(load_duration, int | float)
                        else None
                    ),
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

    def generate_stream(
        self,
        request: AiRequest,
        on_text_delta: Callable[[str], bool | None],
    ) -> AiResponse:
        """Stream Ollama chat deltas and allow voice Core to stop after a useful phrase."""
        with self._request_lock:
            return self._generate_stream_unlocked(request, on_text_delta)

    def _generate_stream_unlocked(
        self,
        request: AiRequest,
        on_text_delta: Callable[[str], bool | None],
    ) -> AiResponse:
        start_t = time.monotonic()
        messages: list[dict[str, str]] = []
        system_parts: list[str] = []
        if request.system_context:
            system_parts.append(request.system_context)
        if request.retrieved_memory:
            system_parts.append(
                "Información de contexto:\n"
                + "\n".join(f"- {m}" for m in request.retrieved_memory)
            )
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        messages.extend({"role": msg.role, "content": msg.content} for msg in request.messages)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": request.max_output_tokens,
                "temperature": request.temperature,
                "num_ctx": self.context_tokens,
            },
        }
        req = urllib.request.Request(
            f"{self.endpoint}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = request.timeout_seconds or self.timeout_seconds
        text_parts: list[str] = []
        final_data: dict[str, object] = {}
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw_line in resp:
                    if not raw_line.strip():
                        continue
                    data = json.loads(raw_line.decode("utf-8"))
                    final_data = data
                    message = data.get("message") or {}
                    delta = str(message.get("content") or "") if isinstance(message, dict) else ""
                    if delta:
                        text_parts.append(delta)
                        if on_text_delta(delta) is False:
                            latency_ms = (time.monotonic() - start_t) * 1000.0
                            return AiResponse(
                                text="".join(text_parts).strip(),
                                finish_reason="client_stop",
                                latency_ms=latency_ms,
                                provider="ollama",
                                model=str(data.get("model") or self.model),
                            )
                    if bool(data.get("done", False)):
                        break
            latency_ms = (time.monotonic() - start_t) * 1000.0
            text = "".join(text_parts).strip()
            if not text:
                return self._failure("empty_response", latency_ms)
            eval_count = final_data.get("eval_count")
            eval_duration = final_data.get("eval_duration")
            prompt_eval_duration = final_data.get("prompt_eval_duration")
            load_duration = final_data.get("load_duration")
            generation_tps: float | None = None
            if (
                isinstance(eval_count, int)
                and eval_count >= 0
                and isinstance(eval_duration, int | float)
                and eval_duration > 0
            ):
                generation_tps = eval_count / (float(eval_duration) / 1_000_000_000.0)
            prompt_eval_count = final_data.get("prompt_eval_count")
            usage = AiUsage(
                input_tokens=prompt_eval_count if isinstance(prompt_eval_count, int) else None,
                output_tokens=eval_count if isinstance(eval_count, int) else None,
                estimated_cost=0.0,
                currency="USD",
                generation_tokens_per_second=generation_tps,
                prompt_eval_ms=(
                    float(prompt_eval_duration) / 1_000_000.0
                    if isinstance(prompt_eval_duration, int | float)
                    else None
                ),
                generation_ms=(
                    float(eval_duration) / 1_000_000.0
                    if isinstance(eval_duration, int | float)
                    else None
                ),
                load_ms=(
                    float(load_duration) / 1_000_000.0
                    if isinstance(load_duration, int | float)
                    else None
                ),
            )
            return AiResponse(
                text=text,
                finish_reason=str(final_data.get("done_reason") or "stop"),
                usage=usage,
                latency_ms=latency_ms,
                provider="ollama",
                model=str(final_data.get("model") or self.model),
            )
        except TimeoutError:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            return self._failure("timeout", latency_ms)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, ValueError) as exc:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("Ollama native streaming API error: %s", exc)
            return self._failure("error", latency_ms)

    def _failure(self, finish_reason: str, latency_ms: float) -> AiResponse:
        return AiResponse(
            text="",
            finish_reason=finish_reason,
            latency_ms=latency_ms,
            provider="ollama",
            model=self.model,
        )

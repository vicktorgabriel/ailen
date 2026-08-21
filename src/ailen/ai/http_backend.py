"""Generic OpenAI-compatible HTTP inference backend.

Communicates with any standard OpenAI-compatible server (llama.cpp server, Ollama,
vLLM, LiteLLM, Groq, OpenRouter, etc.) via Python standard library HTTP.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from ailen.ai.contracts import (
    AiBackend,
    AiRequest,
    AiResponse,
    AiUsage,
    BackendCapabilities,
    BackendHealth,
    ToolCallRequest,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger("ailen.ai.http")


class GenericOpenAiBackend(AiBackend):
    """Client for OpenAI-compatible chat completion endpoints."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8080/v1",
        model: str = "default",
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        provider_name: str = "openai_compatible",
        is_local: bool = False,
        requires_internet: bool = False,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.provider_name = provider_name
        self.is_local = is_local
        self.requires_internet = requires_internet
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self._last_health = BackendHealth(ServiceStatus.UNKNOWN, "Unchecked")

    def health(self) -> BackendHealth:
        """Check backend reachability."""
        if not self.endpoint:
            return BackendHealth(ServiceStatus.DISABLED, "No endpoint configured")

        url = f"{self.endpoint}/models"
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=min(2.0, self.timeout_seconds)) as resp:
                if resp.status == 200:
                    self._last_health = BackendHealth(ServiceStatus.HEALTHY, f"Connected to {self.endpoint}")
                else:
                    self._last_health = BackendHealth(ServiceStatus.UNHEALTHY, f"HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            # Some local servers don't implement /models but work on /chat/completions
            if e.code == 404:
                self._last_health = BackendHealth(ServiceStatus.HEALTHY, f"Endpoint reachable at {self.endpoint}")
            else:
                self._last_health = BackendHealth(ServiceStatus.UNHEALTHY, f"HTTP {e.code}: {e.reason}")
        except Exception as e:  # noqa: BLE001
            self._last_health = BackendHealth(ServiceStatus.DISABLED, f"Unreachable: {e}")

        return self._last_health

    def capabilities(self) -> BackendCapabilities:
        """Return backend capabilities."""
        return BackendCapabilities(
            supports_tools=True,
            supports_streaming=False,
            max_context_tokens=4096,
            is_local=self.is_local,
            requires_internet=self.requires_internet,
        )

    def generate(self, request: AiRequest) -> AiResponse:
        """Execute chat completion request against endpoint."""
        start_t = time.monotonic()

        # 1. Format messages list
        formatted_messages: list[dict[str, Any]] = []

        system_parts: list[str] = []
        if request.system_context:
            system_parts.append(request.system_context)
        if request.retrieved_memory:
            system_parts.append("Información de contexto:\n" + "\n".join(f"- {m}" for m in request.retrieved_memory))

        if system_parts:
            formatted_messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        for msg in request.messages:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": request.max_output_tokens,
            "temperature": 0.7,
        }

        # 2. Build HTTP request
        url = f"{self.endpoint}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload).encode("utf-8")
        http_req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        timeout = request.timeout_seconds or self.timeout_seconds

        try:
            with urllib.request.urlopen(http_req, timeout=timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                latency_ms = (time.monotonic() - start_t) * 1000.0
                return self._parse_success_response(raw_body, latency_ms)

        except urllib.error.HTTPError as e:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:  # noqa: BLE001, S110
                pass
            logger.warning("HTTP %d from %s: %s", e.code, url, error_body)
            return AiResponse(
                text="",
                finish_reason="error",
                latency_ms=latency_ms,
                provider=self.provider_name,
                model=self.model,
            )

        except urllib.error.URLError as e:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("URLError connecting to %s: %s", url, e.reason)
            return AiResponse(
                text="",
                finish_reason="unreachable",
                latency_ms=latency_ms,
                provider=self.provider_name,
                model=self.model,
            )

        except TimeoutError:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("Timeout connecting to %s after %.1fs", url, timeout)
            return AiResponse(
                text="",
                finish_reason="timeout",
                latency_ms=latency_ms,
                provider=self.provider_name,
                model=self.model,
            )

        except Exception as e:  # noqa: BLE001
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("Unexpected error from %s: %s", url, e)
            return AiResponse(
                text="",
                finish_reason="error",
                latency_ms=latency_ms,
                provider=self.provider_name,
                model=self.model,
            )

    def _parse_success_response(self, raw_body: str, latency_ms: float) -> AiResponse:
        """Parse standard OpenAI completion response JSON."""
        try:
            data = json.loads(raw_body)
            choices = data.get("choices", [])
            if not choices:
                return AiResponse(
                    text="",
                    finish_reason="empty_response",
                    latency_ms=latency_ms,
                    provider=self.provider_name,
                    model=self.model,
                )

            choice = choices[0]
            message = choice.get("message", {})
            text = message.get("content") or ""
            finish_reason = choice.get("finish_reason") or "stop"

            # Parse tool calls if present
            tool_calls: list[ToolCallRequest] = []
            if "tool_calls" in message and isinstance(message["tool_calls"], list):
                for tc in message["tool_calls"]:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args_str = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:  # noqa: BLE001
                        args = {}
                    if name:
                        tool_calls.append(ToolCallRequest(name=name, arguments=args))

            # Parse token usage
            usage_data = data.get("usage", {})
            input_tokens = usage_data.get("prompt_tokens")
            output_tokens = usage_data.get("completion_tokens")

            estimated_cost: float | None = None
            if (
                input_tokens is not None
                and output_tokens is not None
                and self.input_cost_per_million is not None
                and self.output_cost_per_million is not None
            ):
                cost = (input_tokens / 1_000_000.0 * self.input_cost_per_million) + (
                    output_tokens / 1_000_000.0 * self.output_cost_per_million
                )
                estimated_cost = round(cost, 6)

            usage = AiUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=estimated_cost,
                currency="USD" if estimated_cost is not None else None,
            )

            return AiResponse(
                text=text.strip(),
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                latency_ms=latency_ms,
                provider=self.provider_name,
                model=data.get("model", self.model),
            )

        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to parse JSON response from %s: %s", self.provider_name, e)
            return AiResponse(
                text="",
                finish_reason="malformed_response",
                latency_ms=latency_ms,
                provider=self.provider_name,
                model=self.model,
            )

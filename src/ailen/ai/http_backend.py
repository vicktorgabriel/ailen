"""Generic OpenAI-compatible HTTP inference backend.

Communicates with any standard OpenAI-compatible server (llama.cpp server, Ollama,
vLLM, LiteLLM, Groq, OpenRouter, etc.) via Python standard library HTTP.
"""

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any

from ailen.ai.contracts import (
    AiErrorKind,
    AiRequest,
    AiResponse,
    AiUsage,
    BackendCapabilities,
    BackendHealth,
    ChatMessage,
    StreamingAiBackend,
    ToolCallRequest,
)
from ailen.ai.providers import (
    AiProvider,
    AuthMode,
    ModelCatalogSource,
    ProviderMetadata,
    ProviderModelCatalog,
    ProviderTestResult,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger("ailen.ai.http")

OPENAI_PROVIDER_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "kimi": "Kimi",
    "minimax": "MiniMax",
}


class GenericOpenAiBackend(AiProvider, StreamingAiBackend):
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
        reasoning_effort: str | None = None,
        supports_reasoning_effort: bool = False,
        streaming_enabled: bool = True,
        requires_api_key: bool = False,
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
        self.reasoning_effort = reasoning_effort
        self.supports_reasoning_effort = supports_reasoning_effort
        self.streaming_enabled = streaming_enabled
        self.requires_api_key = requires_api_key
        self._last_health = BackendHealth(ServiceStatus.UNKNOWN, "Unchecked")
        self._health_checked_at = 0.0
        self._health_ttl_seconds = 30.0

    @property
    def provider_id(self) -> str:
        return self.provider_name

    @property
    def display_name(self) -> str:
        if self.provider_name in OPENAI_PROVIDER_NAMES:
            return OPENAI_PROVIDER_NAMES[self.provider_name]
        return f"OpenAI-Compatible ({self.provider_name})"

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id=self.provider_id,
            display_name=self.display_name,
            auth_mode=AuthMode.API_KEY if self.requires_api_key else AuthMode.NONE,
            description="Proveedor HTTP estándar OpenAI-compatible.",
            default_endpoint=self.endpoint,
            default_model=self.model,
            supports_custom_model=True,
            supports_reasoning_effort=self.supports_reasoning_effort,
        )


    def health(self) -> BackendHealth:
        """Check backend reachability."""
        now = time.monotonic()
        if (
            self._last_health.status is not ServiceStatus.UNKNOWN
            and now - self._health_checked_at < self._health_ttl_seconds
        ):
            return self._last_health
        if not self.endpoint:
            self._last_health = BackendHealth(
                ServiceStatus.DISABLED, "No endpoint configured"
            )
            self._health_checked_at = now
            return self._last_health
        if self.requires_api_key and not self.api_key:
            self._last_health = BackendHealth(
                ServiceStatus.DISABLED, "Provider API key is not configured"
            )
            self._health_checked_at = now
            return self._last_health

        url = f"{self.endpoint}/models"
        headers: dict[str, str] = {"Accept": "application/json", "User-Agent": "AILEN/0.1"}
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
            # A missing catalog proves reachability, not inference health.
            if e.code == 404:
                self._last_health = BackendHealth(
                    ServiceStatus.DEGRADED,
                    f"Endpoint reachable but model catalog is unavailable at {self.endpoint}",
                )
            elif e.code == 429:
                self._last_health = BackendHealth(ServiceStatus.DEGRADED, "Límite de solicitudes alcanzado (HTTP 429)")
            else:
                self._last_health = BackendHealth(ServiceStatus.UNHEALTHY, f"HTTP {e.code}: {e.reason}")
        except Exception as e:  # noqa: BLE001
            self._last_health = BackendHealth(ServiceStatus.UNHEALTHY, f"Unreachable: {e}")

        self._health_checked_at = now
        return self._last_health

    def capabilities(self) -> BackendCapabilities:
        """Return backend capabilities."""
        return BackendCapabilities(
            supports_tools=False,
            supports_streaming=self.streaming_enabled,
            max_context_tokens=4096,
            is_local=self.is_local,
            requires_internet=self.requires_internet,
        )

    def generate(self, request: AiRequest) -> AiResponse:
        """Execute chat completion request against endpoint."""
        start_t = time.monotonic()
        if self.requires_api_key and not self.api_key:
            return self._failure_response(
                kind=AiErrorKind.AUTHENTICATION,
                latency_ms=0.0,
            )

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

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        effort = request.metadata.get("reasoning_effort") or self.reasoning_effort
        if (
            self.supports_reasoning_effort
            and effort
            and effort not in ("none", "disabled")
        ):
            payload["reasoning_effort"] = effort

        # 2. Build HTTP request
        url = f"{self.endpoint}/chat/completions"
        headers = {"Content-Type": "application/json", "User-Agent": "AILEN/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload).encode("utf-8")
        http_req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        timeout = request.timeout_seconds or self.timeout_seconds

        try:
            with urllib.request.urlopen(http_req, timeout=timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                latency_ms = (time.monotonic() - start_t) * 1000.0
                return self._parse_success_response(
                    raw_body,
                    latency_ms,
                    request_chars=len(data),
                )

        except urllib.error.HTTPError as e:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:  # noqa: BLE001, S110
                pass
            logger.warning("HTTP %d from %s: %s", e.code, url, error_body)
            return self._failure_response(
                kind=self._classify_http_error(e.code, error_body),
                latency_ms=latency_ms,
                retry_after_seconds=self._parse_retry_after(e),
            )

        except urllib.error.URLError as e:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("URLError connecting to %s: %s", url, e.reason)
            reason = e.reason
            kind = (
                AiErrorKind.TIMEOUT
                if isinstance(reason, (TimeoutError, socket.timeout))
                else AiErrorKind.NETWORK
            )
            return self._failure_response(
                kind=kind,
                latency_ms=latency_ms,
            )

        except TimeoutError:
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("Timeout connecting to %s after %.1fs", url, timeout)
            return self._failure_response(
                kind=AiErrorKind.TIMEOUT,
                latency_ms=latency_ms,
            )

        except Exception as e:  # noqa: BLE001
            latency_ms = (time.monotonic() - start_t) * 1000.0
            logger.warning("Unexpected error from %s: %s", url, e)
            return self._failure_response(
                kind=AiErrorKind.INTERNAL_ERROR,
                latency_ms=latency_ms,
            )

    def generate_stream(
        self,
        request: AiRequest,
        on_text_delta: Callable[[str], bool | None],
    ) -> AiResponse:
        """Stream an OpenAI-compatible chat completion using SSE ``data:`` events."""
        start_t = time.monotonic()
        if not self.streaming_enabled:
            response = self.generate(request)
            if response.text:
                on_text_delta(response.text)
            return response
        if self.requires_api_key and not self.api_key:
            return self._failure_response(
                kind=AiErrorKind.AUTHENTICATION,
                latency_ms=0.0,
            )
        formatted_messages: list[dict[str, Any]] = []
        system_parts: list[str] = []
        if request.system_context:
            system_parts.append(request.system_context)
        if request.retrieved_memory:
            system_parts.append(
                "Información de contexto:\n"
                + "\n".join(f"- {item}" for item in request.retrieved_memory)
            )
        if system_parts:
            formatted_messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        formatted_messages.extend(
            {"role": msg.role, "content": msg.content} for msg in request.messages
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": True,
        }
        effort = request.metadata.get("reasoning_effort") or self.reasoning_effort
        if (
            self.supports_reasoning_effort
            and effort
            and effort not in ("none", "disabled")
        ):
            payload["reasoning_effort"] = effort

        headers = {"Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": "AILEN/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(payload).encode("utf-8")
        http_req = urllib.request.Request(
            f"{self.endpoint}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        timeout = request.timeout_seconds or self.timeout_seconds
        emitted: list[str] = []
        finish_reason = "stop"
        response_model = self.model
        first_text_ms: float | None = None
        usage = AiUsage()
        try:
            with urllib.request.urlopen(http_req, timeout=timeout) as resp:
                while True:
                    raw_line = resp.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data_text = line[5:].strip()
                    if not data_text or data_text == "[DONE]":
                        if data_text == "[DONE]":
                            break
                        continue
                    try:
                        event = json.loads(data_text)
                    except ValueError:
                        continue
                    response_model = str(event.get("model") or response_model)
                    raw_usage = event.get("usage")
                    if isinstance(raw_usage, dict):
                        prompt_tokens = raw_usage.get("prompt_tokens")
                        completion_tokens = raw_usage.get("completion_tokens")
                        usage.input_tokens = (
                            prompt_tokens if isinstance(prompt_tokens, int) else None
                        )
                        usage.output_tokens = (
                            completion_tokens
                            if isinstance(completion_tokens, int)
                            else None
                        )
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0] if isinstance(choices[0], dict) else {}
                    finish_reason = str(choice.get("finish_reason") or finish_reason)
                    delta = choice.get("delta") or {}
                    content = delta.get("content") if isinstance(delta, dict) else None
                    if not isinstance(content, str) or not content:
                        continue
                    if first_text_ms is None:
                        first_text_ms = (time.monotonic() - start_t) * 1000.0
                    emitted.append(content)
                    if on_text_delta(content) is False:
                        finish_reason = "client_stop"
                        break
            return AiResponse(
                text="".join(emitted).strip(),
                finish_reason=finish_reason,
                usage=usage,
                latency_ms=(time.monotonic() - start_t) * 1000.0,
                provider=self.provider_name,
                model=response_model,
                first_text_ms=first_text_ms,
                request_chars=len(data),
                error_kind=(AiErrorKind.INVALID_RESPONSE if not emitted else None),
            )
        except urllib.error.HTTPError as exc:
            logger.warning("HTTP %d from streaming backend %s", exc.code, self.endpoint)
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:  # noqa: BLE001, S110
                pass
            return self._failure_response(
                kind=self._classify_http_error(exc.code, error_body),
                latency_ms=(time.monotonic() - start_t) * 1000.0,
                retry_after_seconds=self._parse_retry_after(exc),
            )
        except urllib.error.URLError as exc:
            logger.warning("Streaming backend unreachable %s: %s", self.endpoint, exc.reason)
            reason = exc.reason
            kind = (
                AiErrorKind.TIMEOUT
                if isinstance(reason, (TimeoutError, socket.timeout))
                else AiErrorKind.NETWORK
            )
            return self._failure_response(
                kind=kind,
                latency_ms=(time.monotonic() - start_t) * 1000.0,
            )
        except TimeoutError:
            return self._failure_response(
                kind=AiErrorKind.TIMEOUT,
                latency_ms=(time.monotonic() - start_t) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected streaming error from %s: %s", self.endpoint, exc)
            return self._failure_response(
                kind=AiErrorKind.INTERNAL_ERROR,
                latency_ms=(time.monotonic() - start_t) * 1000.0,
            )

    @staticmethod
    def _classify_http_error(status_code: int, body: str) -> AiErrorKind:
        lowered = body.lower()
        if status_code == 429:
            return AiErrorKind.RATE_LIMIT
        if status_code in {401, 403}:
            return AiErrorKind.AUTHENTICATION
        invalid_model_markers = (
            "invalid",
            "model_not_found",
            "not found",
            "not available",
            "unknown",
        )
        if status_code in {400, 404, 422} and "model" in lowered and any(
            marker in lowered for marker in invalid_model_markers
        ):
            return AiErrorKind.INVALID_MODEL
        if status_code >= 500:
            return AiErrorKind.UNAVAILABLE
        return AiErrorKind.UNAVAILABLE

    @staticmethod
    def _parse_retry_after(error: urllib.error.HTTPError) -> float | None:
        raw = error.headers.get("Retry-After") if error.headers is not None else None
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
                return max(0.0, retry_at.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return None

    def _failure_response(
        self,
        *,
        kind: AiErrorKind,
        latency_ms: float,
        retry_after_seconds: float | None = None,
    ) -> AiResponse:
        finish_reason = {
            AiErrorKind.RATE_LIMIT: "rate_limited",
            AiErrorKind.TIMEOUT: "timeout",
            AiErrorKind.NETWORK: "unreachable",
            AiErrorKind.INVALID_RESPONSE: "malformed_response",
        }.get(kind, "error")
        return AiResponse(
            text="",
            finish_reason=finish_reason,
            latency_ms=latency_ms,
            provider=self.provider_name,
            model=self.model,
            error_kind=kind,
            retry_after_seconds=retry_after_seconds,
        )

    def _parse_success_response(
        self,
        raw_body: str,
        latency_ms: float,
        *,
        request_chars: int,
    ) -> AiResponse:
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
                    error_kind=AiErrorKind.INVALID_RESPONSE,
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
                first_text_ms=latency_ms if text.strip() else None,
                request_chars=request_chars,
            )

        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to parse JSON response from %s: %s", self.provider_name, e)
            return AiResponse(
                text="",
                finish_reason="malformed_response",
                latency_ms=latency_ms,
                provider=self.provider_name,
                model=self.model,
                error_kind=AiErrorKind.INVALID_RESPONSE,
            )

    def _fetch_live_models(self) -> list[str]:
        """Fetch model IDs from ``/models`` without disguising fallback as live."""
        if not self.endpoint:
            return []
        url = f"{self.endpoint}/models"
        headers: dict[str, str] = {"Accept": "application/json", "User-Agent": "AILEN/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=min(3.0, self.timeout_seconds)) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    items = data.get("data") or data.get("models") or []
                    models: list[str] = []
                    for item in items:
                        if isinstance(item, dict) and "id" in item:
                            models.append(str(item["id"]))
                        elif isinstance(item, str):
                            models.append(item)
                    if models:
                        return sorted(models)
        except Exception:  # noqa: BLE001, S110
            pass
        return []

    def model_catalog(self) -> ProviderModelCatalog:
        live_models = self._fetch_live_models()
        if live_models:
            return ProviderModelCatalog(
                models=live_models,
                source=ModelCatalogSource.LIVE,
                detail="Catálogo publicado por el endpoint /models.",
            )
        if self.model:
            return ProviderModelCatalog(
                models=[self.model],
                source=ModelCatalogSource.CONFIGURED,
                detail="El endpoint no publicó catálogo; se conserva el modelo configurado.",
            )
        return ProviderModelCatalog(
            source=ModelCatalogSource.UNAVAILABLE,
            detail="El endpoint no publicó catálogo y no hay modelo configurado.",
        )

    def list_models(self) -> list[str]:
        """Compatibility view of :meth:`model_catalog`."""
        return self.model_catalog().models

    def test_connection(self, prompt: str = "Respondé solamente: OK") -> ProviderTestResult:
        """Execute a quick non-destructive test probe and measure latency."""
        start_t = time.monotonic()
        req = AiRequest(
            request_id="test-probe",
            system_context="",
            messages=[ChatMessage(role="user", content=prompt)],
            max_output_tokens=64,
            temperature=0.0,
            timeout_seconds=min(8.0, self.timeout_seconds),
        )
        try:
            resp = self.generate_stream(req, lambda _delta: True)
            latency_ms = resp.latency_ms or ((time.monotonic() - start_t) * 1000.0)
            if resp.finish_reason not in ("error", "unreachable", "timeout", "malformed_response") and resp.text:
                return ProviderTestResult(
                    ok=True,
                    latency_ms=latency_ms,
                    response_text=resp.text,
                    first_token_ms=resp.first_text_ms,
                    model=resp.model or self.model,
                    provider_setup_ms=resp.provider_setup_ms,
                )
            return ProviderTestResult(
                ok=False,
                latency_ms=latency_ms,
                error=f"Error en respuesta: {resp.finish_reason}",
                model=self.model,
                error_kind=resp.error_kind,
                provider_setup_ms=resp.provider_setup_ms,
            )
        except Exception as e:  # noqa: BLE001
            latency_ms = (time.monotonic() - start_t) * 1000.0
            return ProviderTestResult(
                ok=False,
                latency_ms=latency_ms,
                error=str(e),
                model=self.model,
            )

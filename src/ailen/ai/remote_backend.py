"""Lightweight remote AI adapters with real protocol streaming and no SDK dependency."""

from __future__ import annotations

import json
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
)
from ailen.ai.http_backend import GenericOpenAiBackend
from ailen.ai.providers import (
    AiProvider,
    AuthMode,
    ModelCatalogSource,
    ProviderMetadata,
    ProviderModelCatalog,
    ProviderTestResult,
)
from ailen.core.config import RemoteProviderConfig
from ailen.domain.enums import ServiceStatus


def _http_error_kind(status: int, body: str) -> AiErrorKind:
    lowered = body.lower()
    if status == 429:
        return AiErrorKind.RATE_LIMIT
    if status in {401, 403}:
        return AiErrorKind.AUTHENTICATION
    if status in {400, 404, 422} and "model" in lowered and any(
        marker in lowered
        for marker in ("invalid", "not_found", "not found", "unknown", "not available")
    ):
        return AiErrorKind.INVALID_MODEL
    if status >= 500:
        return AiErrorKind.UNAVAILABLE
    return AiErrorKind.INVALID_RESPONSE


def _retry_after(error: urllib.error.HTTPError) -> float | None:
    raw = error.headers.get("Retry-After") if error.headers is not None else None
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


class _NativeRemoteBackend(AiProvider):
    """Common fail-closed mechanics for native Responses/Messages adapters."""

    protocol_name = "remote"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        api_key: str | None,
        provider_name: str,
        timeout_seconds: float = 10.0,
        streaming_enabled: bool = True,
        catalog_mode: str = "manual",
        auth_required: bool = True,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds
        self.streaming_enabled = streaming_enabled
        self.catalog_mode = catalog_mode
        self.auth_required = auth_required
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self._last_health = BackendHealth(ServiceStatus.UNKNOWN, "Not tested")
        self._health_checked_at = 0.0

    @property
    def provider_id(self) -> str:
        return self.provider_name

    @property
    def display_name(self) -> str:
        return self.provider_name.removeprefix("remote:").replace("_", " ").title()

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id=self.provider_name,
            display_name=self.display_name,
            auth_mode=AuthMode.API_KEY if self.auth_required else AuthMode.NONE,
            description=f"Remote {self.protocol_name} provider",
            default_endpoint=self.endpoint,
            default_model=self.model,
            supports_custom_model=True,
            supports_reasoning_effort=False,
        )

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_tools=False,
            supports_streaming=self.streaming_enabled,
            max_context_tokens=4096,
            is_local=False,
            requires_internet=True,
        )

    def _auth_headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _model_catalog_url(self) -> str:
        return f"{self.endpoint}/models"

    def _configured(self) -> bool:
        return bool(
            self.endpoint
            and self.model
            and (self.api_key or not self.auth_required)
        )

    def health(self) -> BackendHealth:
        now = time.monotonic()
        if now - self._health_checked_at < 30.0 and self._last_health.status is not ServiceStatus.UNKNOWN:
            return self._last_health
        if not self.endpoint or not self.model:
            self._last_health = BackendHealth(
                ServiceStatus.DISABLED, "Remote endpoint/model is not configured"
            )
        elif self.auth_required and not self.api_key:
            self._last_health = BackendHealth(
                ServiceStatus.DISABLED, "Provider API key is not configured"
            )
        elif self.catalog_mode != "live":
            self._last_health = BackendHealth(
                ServiceStatus.UNKNOWN,
                "Configured; health requires an explicit connection test",
            )
        else:
            request = urllib.request.Request(
                self._model_catalog_url(), headers=self._auth_headers(), method="GET"
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=min(3.0, self.timeout_seconds)
                ) as response:
                    self._last_health = BackendHealth(
                        ServiceStatus.HEALTHY
                        if response.status == 200
                        else ServiceStatus.UNHEALTHY,
                        f"HTTP {response.status}",
                    )
            except urllib.error.HTTPError as exc:
                status = (
                    ServiceStatus.DEGRADED
                    if exc.code in {404, 429}
                    else ServiceStatus.UNHEALTHY
                )
                self._last_health = BackendHealth(status, f"HTTP {exc.code}")
            except (OSError, TimeoutError, urllib.error.URLError):
                self._last_health = BackendHealth(
                    ServiceStatus.UNHEALTHY, "Remote endpoint unavailable"
                )
        self._health_checked_at = now
        return self._last_health

    def _models_from_document(self, document: Any) -> list[str]:
        if not isinstance(document, dict):
            return []
        items = document.get("data") or document.get("models") or []
        result: list[str] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    result.append(item["id"])
                elif isinstance(item, str):
                    result.append(item)
        return sorted(set(result))

    def model_catalog(self) -> ProviderModelCatalog:
        if self.catalog_mode != "live" or not self._configured():
            return ProviderModelCatalog(
                models=[self.model] if self.model else [],
                source=(
                    ModelCatalogSource.CONFIGURED
                    if self.model
                    else ModelCatalogSource.UNAVAILABLE
                ),
                detail="Manual model selection; no live catalog was claimed.",
            )
        request = urllib.request.Request(
            self._model_catalog_url(), headers=self._auth_headers(), method="GET"
        )
        try:
            with urllib.request.urlopen(
                request, timeout=min(3.0, self.timeout_seconds)
            ) as response:
                models = self._models_from_document(
                    json.loads(response.read().decode("utf-8"))
                )
        except (OSError, TimeoutError, ValueError, urllib.error.URLError):
            models = []
        if models:
            return ProviderModelCatalog(
                models=models,
                source=ModelCatalogSource.LIVE,
                detail="Catalog returned by the configured provider endpoint.",
            )
        return ProviderModelCatalog(
            models=[self.model] if self.model else [],
            source=(
                ModelCatalogSource.CONFIGURED
                if self.model
                else ModelCatalogSource.UNAVAILABLE
            ),
            detail="Live catalog unavailable; showing only the configured model.",
        )

    def list_models(self) -> list[str]:
        return self.model_catalog().models

    def test_connection(self, prompt: str = "Respondé solamente: OK") -> ProviderTestResult:
        response = self.generate_stream(
            AiRequest(
                request_id="remote-provider-test",
                messages=[ChatMessage(role="user", content=prompt)],
                max_output_tokens=32,
                temperature=0.0,
                timeout_seconds=min(8.0, self.timeout_seconds),
            ),
            lambda _delta: True,
        )
        return ProviderTestResult(
            ok=bool(response.text) and response.error_kind is None,
            latency_ms=response.latency_ms,
            response_text=response.text,
            first_token_ms=response.first_text_ms,
            model=response.model,
            error="" if response.error_kind is None else response.error_kind.value,
            error_kind=response.error_kind,
        )

    def _failure(
        self,
        kind: AiErrorKind,
        started: float,
        *,
        retry_after_seconds: float | None = None,
    ) -> AiResponse:
        finish = {
            AiErrorKind.TIMEOUT: "timeout",
            AiErrorKind.RATE_LIMIT: "rate_limited",
            AiErrorKind.NETWORK: "unreachable",
            AiErrorKind.INVALID_RESPONSE: "malformed_response",
        }.get(kind, "error")
        return AiResponse(
            text="",
            finish_reason=finish,
            latency_ms=max(0.0, (time.monotonic() - started) * 1000.0),
            provider=self.provider_name,
            model=self.model or "unconfigured",
            error_kind=kind,
            retry_after_seconds=retry_after_seconds,
        )

    def _handle_transport_error(self, exc: BaseException, started: float) -> AiResponse:
        if isinstance(exc, urllib.error.HTTPError):
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except OSError:
                body = ""
            return self._failure(
                _http_error_kind(exc.code, body),
                started,
                retry_after_seconds=_retry_after(exc),
            )
        if isinstance(exc, urllib.error.URLError):
            kind = (
                AiErrorKind.TIMEOUT
                if isinstance(exc.reason, (TimeoutError, socket.timeout))
                else AiErrorKind.NETWORK
            )
            return self._failure(kind, started)
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return self._failure(AiErrorKind.TIMEOUT, started)
        return self._failure(AiErrorKind.INTERNAL_ERROR, started)

    def _usage(
        self, input_tokens: int | None, output_tokens: int | None
    ) -> AiUsage:
        cost: float | None = None
        if (
            input_tokens is not None
            and output_tokens is not None
            and self.input_cost_per_million is not None
            and self.output_cost_per_million is not None
        ):
            cost = round(
                input_tokens / 1_000_000 * self.input_cost_per_million
                + output_tokens / 1_000_000 * self.output_cost_per_million,
                6,
            )
        return AiUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            currency="USD" if cost is not None else None,
        )

    def generate_stream(
        self,
        request: AiRequest,
        on_text_delta: Callable[[str], bool | None],
    ) -> AiResponse:
        raise NotImplementedError


class OpenAiResponsesBackend(_NativeRemoteBackend):
    """Native OpenAI Responses API adapter with real SSE deltas and store=false."""

    protocol_name = "OpenAI Responses API"

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AILEN/0.4",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _input(request: AiRequest) -> list[dict[str, str]]:
        return [
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role in {"user", "assistant"}
        ]

    def _payload(self, request: AiRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": self._input(request),
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "stream": stream,
        }
        if request.system_context:
            payload["instructions"] = request.system_context
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload

    def generate(self, request: AiRequest) -> AiResponse:
        started = time.monotonic()
        if not self._configured():
            kind = (
                AiErrorKind.AUTHENTICATION
                if self.endpoint and self.model and self.auth_required
                else AiErrorKind.UNAVAILABLE
            )
            return self._failure(kind, started)
        payload = self._payload(request, stream=False)
        data = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.endpoint}/responses",
            data=data,
            headers=self._auth_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=request.timeout_seconds or self.timeout_seconds
            ) as response:
                document = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
            return self._handle_transport_error(exc, started)
        text = document.get("output_text") if isinstance(document, dict) else None
        if not isinstance(text, str):
            parts: list[str] = []
            for item in document.get("output", []) if isinstance(document, dict) else []:
                for content in item.get("content", []) if isinstance(item, dict) else []:
                    if isinstance(content, dict) and content.get("type") == "output_text":
                        value = content.get("text")
                        if isinstance(value, str):
                            parts.append(value)
            text = "".join(parts)
        usage_raw = document.get("usage", {}) if isinstance(document, dict) else {}
        usage = self._usage(
            usage_raw.get("input_tokens") if isinstance(usage_raw, dict) else None,
            usage_raw.get("output_tokens") if isinstance(usage_raw, dict) else None,
        )
        latency = (time.monotonic() - started) * 1000.0
        return AiResponse(
            text=text.strip(),
            finish_reason=str(document.get("status") or "stop"),
            usage=usage,
            latency_ms=latency,
            provider=self.provider_name,
            model=str(document.get("model") or self.model),
            first_text_ms=latency if text.strip() else None,
            request_chars=len(data),
            error_kind=None if text.strip() else AiErrorKind.INVALID_RESPONSE,
        )

    def generate_stream(
        self,
        request: AiRequest,
        on_text_delta: Callable[[str], bool | None],
    ) -> AiResponse:
        if not self.streaming_enabled:
            response = self.generate(request)
            if response.text:
                on_text_delta(response.text)
            return response
        started = time.monotonic()
        if not self._configured():
            kind = (
                AiErrorKind.AUTHENTICATION
                if self.endpoint and self.model and self.auth_required
                else AiErrorKind.UNAVAILABLE
            )
            return self._failure(kind, started)
        data = json.dumps(self._payload(request, stream=True)).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.endpoint}/responses",
            data=data,
            headers={**self._auth_headers(), "Accept": "text/event-stream"},
            method="POST",
        )
        parts: list[str] = []
        first_text_ms: float | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        model = self.model
        finish_reason = "stop"
        try:
            with urllib.request.urlopen(
                http_request, timeout=request.timeout_seconds or self.timeout_seconds
            ) as response:
                while True:
                    raw = response.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    encoded = line[5:].strip()
                    if not encoded or encoded == "[DONE]":
                        continue
                    try:
                        event = json.loads(encoded)
                    except ValueError:
                        continue
                    event_type = event.get("type")
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta")
                        if isinstance(delta, str) and delta:
                            if first_text_ms is None:
                                first_text_ms = (time.monotonic() - started) * 1000.0
                            parts.append(delta)
                            if on_text_delta(delta) is False:
                                finish_reason = "client_stop"
                                break
                    elif event_type == "response.completed":
                        completed = event.get("response", {})
                        if isinstance(completed, dict):
                            model = str(completed.get("model") or model)
                            finish_reason = str(completed.get("status") or finish_reason)
                            usage = completed.get("usage", {})
                            if isinstance(usage, dict):
                                input_tokens = usage.get("input_tokens")
                                output_tokens = usage.get("output_tokens")
                    elif event_type in {"response.failed", "error"}:
                        return self._failure(AiErrorKind.INVALID_RESPONSE, started)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            return self._handle_transport_error(exc, started)
        text = "".join(parts).strip()
        return AiResponse(
            text=text,
            finish_reason=finish_reason,
            usage=self._usage(input_tokens, output_tokens),
            latency_ms=(time.monotonic() - started) * 1000.0,
            provider=self.provider_name,
            model=model,
            first_text_ms=first_text_ms,
            request_chars=len(data),
            error_kind=None if text else AiErrorKind.INVALID_RESPONSE,
        )


class AnthropicMessagesBackend(_NativeRemoteBackend):
    """Native Anthropic Messages adapter with content_block_delta SSE parsing."""

    protocol_name = "Anthropic Messages API"

    def __init__(self, *, anthropic_version: str = "2023-06-01", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.anthropic_version = anthropic_version

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AILEN/0.4",
            "anthropic-version": self.anthropic_version,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _payload(self, request: AiRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
                if message.role in {"user", "assistant"}
            ],
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.system_context:
            payload["system"] = request.system_context
        return payload

    def generate(self, request: AiRequest) -> AiResponse:
        started = time.monotonic()
        if not self._configured():
            kind = (
                AiErrorKind.AUTHENTICATION
                if self.endpoint and self.model and self.auth_required
                else AiErrorKind.UNAVAILABLE
            )
            return self._failure(kind, started)
        data = json.dumps(self._payload(request, stream=False)).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.endpoint}/messages",
            data=data,
            headers=self._auth_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=request.timeout_seconds or self.timeout_seconds
            ) as response:
                document = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
            return self._handle_transport_error(exc, started)
        parts = [
            item["text"]
            for item in document.get("content", [])
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        usage_raw = document.get("usage", {})
        latency = (time.monotonic() - started) * 1000.0
        text = "".join(parts).strip()
        return AiResponse(
            text=text,
            finish_reason=str(document.get("stop_reason") or "stop"),
            usage=self._usage(
                usage_raw.get("input_tokens") if isinstance(usage_raw, dict) else None,
                usage_raw.get("output_tokens") if isinstance(usage_raw, dict) else None,
            ),
            latency_ms=latency,
            provider=self.provider_name,
            model=str(document.get("model") or self.model),
            first_text_ms=latency if text else None,
            request_chars=len(data),
            error_kind=None if text else AiErrorKind.INVALID_RESPONSE,
        )

    def generate_stream(
        self,
        request: AiRequest,
        on_text_delta: Callable[[str], bool | None],
    ) -> AiResponse:
        if not self.streaming_enabled:
            response = self.generate(request)
            if response.text:
                on_text_delta(response.text)
            return response
        started = time.monotonic()
        if not self._configured():
            kind = (
                AiErrorKind.AUTHENTICATION
                if self.endpoint and self.model and self.auth_required
                else AiErrorKind.UNAVAILABLE
            )
            return self._failure(kind, started)
        data = json.dumps(self._payload(request, stream=True)).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.endpoint}/messages",
            data=data,
            headers={**self._auth_headers(), "Accept": "text/event-stream"},
            method="POST",
        )
        parts: list[str] = []
        first_text_ms: float | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        model = self.model
        finish_reason = "stop"
        try:
            with urllib.request.urlopen(
                http_request, timeout=request.timeout_seconds or self.timeout_seconds
            ) as response:
                while True:
                    raw = response.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    encoded = line[5:].strip()
                    if not encoded:
                        continue
                    try:
                        event = json.loads(encoded)
                    except ValueError:
                        continue
                    event_type = event.get("type")
                    if event_type == "message_start":
                        message = event.get("message", {})
                        if isinstance(message, dict):
                            model = str(message.get("model") or model)
                            usage = message.get("usage", {})
                            if isinstance(usage, dict):
                                input_tokens = usage.get("input_tokens")
                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if isinstance(delta, dict) and delta.get("type") == "text_delta":
                            text_delta = delta.get("text")
                            if isinstance(text_delta, str) and text_delta:
                                if first_text_ms is None:
                                    first_text_ms = (time.monotonic() - started) * 1000.0
                                parts.append(text_delta)
                                if on_text_delta(text_delta) is False:
                                    finish_reason = "client_stop"
                                    break
                    elif event_type == "message_delta":
                        delta = event.get("delta", {})
                        usage = event.get("usage", {})
                        if isinstance(delta, dict):
                            finish_reason = str(delta.get("stop_reason") or finish_reason)
                        if isinstance(usage, dict):
                            output_tokens = usage.get("output_tokens")
                    elif event_type == "error":
                        return self._failure(AiErrorKind.INVALID_RESPONSE, started)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            return self._handle_transport_error(exc, started)
        text = "".join(parts).strip()
        return AiResponse(
            text=text,
            finish_reason=finish_reason,
            usage=self._usage(input_tokens, output_tokens),
            latency_ms=(time.monotonic() - started) * 1000.0,
            provider=self.provider_name,
            model=model,
            first_text_ms=first_text_ms,
            request_chars=len(data),
            error_kind=None if text else AiErrorKind.INVALID_RESPONSE,
        )


def build_remote_backend(
    provider_id: str,
    config: RemoteProviderConfig,
    *,
    api_key: str | None,
) -> AiProvider:
    """Build exactly the configured protocol; no brand-specific hidden fallback."""

    common: dict[str, Any] = {
        "endpoint": config.endpoint,
        "model": config.model,
        "api_key": api_key,
        "timeout_seconds": config.timeout_seconds,
        "provider_name": f"remote:{provider_id}",
        "streaming_enabled": config.streaming_enabled,
        "auth_required": config.auth_mode == "api_key",
        "catalog_mode": config.catalog_mode,
        "input_cost_per_million": config.input_cost_per_million,
        "output_cost_per_million": config.output_cost_per_million,
    }
    if config.protocol == "openai_responses":
        return OpenAiResponsesBackend(**common)
    if config.protocol == "anthropic_messages":
        return AnthropicMessagesBackend(
            **common,
            anthropic_version=config.anthropic_version,
        )
    if config.protocol == "openai_chat":
        return GenericOpenAiBackend(
            endpoint=config.endpoint,
            model=config.model,
            api_key=api_key,
            timeout_seconds=config.timeout_seconds,
            provider_name=f"remote:{provider_id}",
            is_local=False,
            requires_internet=True,
            input_cost_per_million=config.input_cost_per_million,
            output_cost_per_million=config.output_cost_per_million,
            streaming_enabled=config.streaming_enabled,
            requires_api_key=config.auth_mode == "api_key",
        )
    raise ValueError(f"Unsupported remote protocol: {config.protocol}")

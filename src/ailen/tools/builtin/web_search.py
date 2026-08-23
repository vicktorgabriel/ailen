"""Web search boundary and tool for AILEN.

Provides an isolated, provider-agnostic web search interface.
LLMs never receive direct network/urllib sockets.
See ADR-010.
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable
from urllib.parse import urlsplit

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult


@dataclass
class WebSearchRequest:
    """Standardized web search query request."""

    query: str
    max_results: int = 5
    language: str = "es"
    safe_search: bool = True
    timeout: float = 5.0


@dataclass
class WebSearchResult:
    """Sanitized individual search result item."""

    title: str
    snippet: str
    url: str
    source: str = "web"


@dataclass
class WebSearchResponse:
    """Normalized response from a search provider."""

    success: bool
    results: list[WebSearchResult] = field(default_factory=list)
    status: str = "OK"  # "OK", "UNCONFIGURED", "ERROR", "TIMEOUT"
    cost_tier: str = "UNKNOWN"  # "FREE", "PAID", "UNKNOWN"
    error_message: str | None = None


@runtime_checkable
class WebSearchProvider(Protocol):
    """Protocol for interchangeable web search backends."""

    def search(self, request: WebSearchRequest) -> WebSearchResponse:
        """Execute a search query against the external provider."""
        ...


class UnconfiguredWebSearchProvider:
    """Default fallback provider when no external search provider is configured."""

    def search(self, request: WebSearchRequest) -> WebSearchResponse:
        return WebSearchResponse(
            success=False,
            results=[],
            status="UNCONFIGURED",
            cost_tier="UNKNOWN",
            error_message="El proveedor de búsqueda web no está configurado en este nodo.",
        )


class FakeWebSearchProvider:
    """Deterministic mock search provider for unit tests and offline demos."""

    def __init__(self, canned_results: dict[str, list[WebSearchResult]] | None = None) -> None:
        self.canned_results = canned_results or {}
        self.call_history: list[WebSearchRequest] = []

    def search(self, request: WebSearchRequest) -> WebSearchResponse:
        self.call_history.append(request)
        for key, results in self.canned_results.items():
            if key.lower() in request.query.lower():
                return WebSearchResponse(
                    success=True,
                    results=results[: request.max_results],
                    status="OK",
                    cost_tier="FREE",
                )

        # Default simulated result
        default_res = [
            WebSearchResult(
                title=f"Resultado para {request.query}",
                snippet=f"Información resumida pública encontrada sobre {request.query}.",
                url="https://example.org/search",
                source="fake_search",
            )
        ]
        return WebSearchResponse(
            success=True,
            results=default_res[: request.max_results],
            status="OK",
            cost_tier="FREE",
        )


class WebSearchTool:
    """Controlled Web Search tool."""

    name: str = "web_search"
    description: str = "Busca información pública en la web de forma controlada y estructurada."
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "query": {
                "type": "str",
                "required": True,
                "min_len": 2,
                "max_len": 300,
            },
            "max_results": {
                "type": "int",
                "required": False,
                "min": 1,
                "max": 10,
                "default": 5,
            },
            "language": {
                "type": "str",
                "required": False,
                "default": "es",
            },
        },
    }
    permissions: ClassVar[list[str]] = ["web.search"]
    allowed_modes: ClassVar[set[SocialMode]] = {
        SocialMode.HOME,
        SocialMode.WORKSHOP,
        SocialMode.PUBLIC,
        SocialMode.PRIVATE,
    }
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = True
    destructive: bool = False
    timeout_seconds: float = 6.0

    def __init__(self, provider: WebSearchProvider | None = None) -> None:
        self.provider = provider or UnconfiguredWebSearchProvider()

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        query = validated_args["query"].strip()
        max_results = validated_args.get("max_results", 5)
        language = validated_args.get("language", "es")

        req = WebSearchRequest(
            query=query,
            max_results=max_results,
            language=language,
            timeout=context.timeout_seconds,
        )

        resp = self.provider.search(req)

        if not resp.success:
            if resp.status == "UNCONFIGURED":
                msg = "El servicio de búsqueda web no está configurado en este momento."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNCONFIGURED",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.CLOUD_OFFLINE,
                    requires_llm_summary=False,
                )
            msg = f"Error al realizar la búsqueda web: {resp.error_message or 'desconocido'}"
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="ERROR",
                message=msg,
                summary=msg,
                error_code=ErrorCode.UNKNOWN_ERROR,
                requires_llm_summary=False,
            )

        # Success path: provider output is untrusted external data. Bound text
        # sizes and keep only navigable HTTP(S) result URLs before LLM synthesis.
        results_data: list[dict[str, str]] = []
        for item in resp.results[:max_results]:
            title = " ".join(str(item.title).split())[:300]
            snippet = " ".join(str(item.snippet).split())[:1200]
            raw_url = str(item.url).strip()[:1000]
            try:
                parsed = urlsplit(raw_url)
                safe_url = raw_url if parsed.scheme in {"http", "https"} and parsed.netloc else ""
            except ValueError:
                safe_url = ""
            source = " ".join(str(item.source).split())[:120]
            results_data.append(
                {
                    "title": title,
                    "snippet": snippet,
                    "url": safe_url,
                    "source": source,
                }
            )

        if not results_data:
            msg = f"No se encontraron resultados web para '{query}'."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={"query": query, "count": 0, "results": []},
                requires_llm_summary=False,
            )

        summary_msg = f"Se encontraron {len(results_data)} resultados para '{query}'."
        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=summary_msg,
            summary=summary_msg,
            data={
                "query": query,
                "count": len(results_data),
                "results": results_data,
                "cost_tier": resp.cost_tier,
            },
            requires_llm_summary=True,  # Allows LLM to synthesize concise voice answer
        )

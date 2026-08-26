"""Web search boundary and tool for AILEN.

Provides an isolated, provider-agnostic web search interface.
LLMs never receive direct network/urllib sockets.
See ADR-010.
"""

import importlib.util
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Protocol, runtime_checkable
from urllib.parse import urlsplit

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult


@dataclass
class WebSearchRequest:
    """Standardized web search query request."""

    query: str
    max_results: int = 3
    language: str = "es"
    safe_search: bool = True
    timeout: float = 5.0
    category: str = "text"
    freshness: str | None = None


@dataclass
class WebSearchResult:
    """Sanitized individual search result item."""

    title: str
    snippet: str
    url: str
    source: str = "web"
    published_at: str | None = None


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
    """Explicit unavailable provider used when web search is disabled."""

    is_available = False

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

    is_available = True

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


class DdgsWebSearchProvider:
    """Keyless metasearch provider using the maintained ``ddgs`` Python package."""

    def __init__(self, region: str = "ar-es") -> None:
        self.region = region.strip() or "ar-es"

    @property
    def is_available(self) -> bool:
        try:
            return importlib.util.find_spec("ddgs") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def search(self, request: WebSearchRequest) -> WebSearchResponse:
        if not self.is_available:
            return WebSearchResponse(
                success=False,
                status="UNCONFIGURED",
                cost_tier="FREE",
                error_message="El paquete ddgs no está instalado.",
            )
        try:
            from ddgs import DDGS  # type: ignore[import-untyped]

            client = DDGS(timeout=max(1, round(request.timeout)))
            category = request.category.strip().lower()
            if category == "news":
                time_limit = {
                    "day": "d",
                    "week": "w",
                    "month": "m",
                }.get((request.freshness or "").strip().lower())
                rows = client.news(
                    request.query,
                    region=self.region,
                    safesearch="moderate" if request.safe_search else "off",
                    timelimit=time_limit,
                    max_results=request.max_results,
                )
            elif category == "text":
                rows = client.text(
                    request.query,
                    region=self.region,
                    safesearch="moderate" if request.safe_search else "off",
                    max_results=request.max_results,
                )
            else:
                return WebSearchResponse(
                    success=False,
                    status="ERROR",
                    cost_tier="FREE",
                    error_message=f"Categoría de búsqueda no soportada: {request.category}",
                )
            results: list[WebSearchResult] = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("href") or row.get("url") or "").strip()
                title = str(row.get("title") or "").strip()
                snippet = str(row.get("body") or row.get("snippet") or "").strip()
                if not url or not title:
                    continue
                parsed = urlsplit(url)
                source = str(row.get("source") or "").strip() or parsed.netloc or "web"
                published_at = str(row.get("date") or "").strip() or None
                results.append(
                    WebSearchResult(
                        title=title,
                        snippet=snippet,
                        url=url,
                        source=source,
                        published_at=published_at,
                    )
                )
            return WebSearchResponse(
                success=True,
                results=results[: request.max_results],
                status="OK",
                cost_tier="FREE",
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or type(exc).__name__
            if "no results found" in message.casefold():
                return WebSearchResponse(
                    success=True,
                    results=[],
                    status="OK",
                    cost_tier="FREE",
                )
            status = "TIMEOUT" if "timeout" in message.casefold() else "ERROR"
            return WebSearchResponse(
                success=False,
                status=status,
                cost_tier="FREE",
                error_message=message,
            )


def create_web_search_provider(name: str, region: str = "ar-es") -> WebSearchProvider:
    """Build the explicitly configured provider; no automatic provider switching."""
    provider = name.strip().lower()
    if provider == "none":
        return UnconfiguredWebSearchProvider()
    if provider == "ddgs":
        return DdgsWebSearchProvider(region=region)
    raise ValueError(f"Unsupported web search provider: {name}")


class WebSearchTool:
    """Controlled Web Search tool."""

    name: str = "web_search"
    description: str = "Busca información pública en la web de forma controlada y estructurada."
    intent_hints = (
        "internet", "web", "buscar", "buscá", "busca", "averigua", "averiguá",
        "investiga", "investigá", "consulta", "consultá", "noticias", "clima",
        "temperatura", "pronóstico", "pronostico", "novedades", "precio actual",
        "cotización", "cotizacion",
    )
    intent_guidance = (
        "Para noticias, novedades o actualidad usá category=news; usá freshness=day si piden hoy, "
        "week si piden esta semana y month si piden este mes. Para información general usá "
        "category=text y omití freshness. En category=news, dejá en query sólo el tema; category y "
        "freshness ya representan palabras como noticias, novedades u hoy."
    )
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
                "default": 3,
            },
            "language": {
                "type": "str",
                "required": False,
                "default": "es",
            },
            "category": {
                "type": "str",
                "required": False,
                "default": "text",
                "enum": ["text", "news"],
            },
            "freshness": {
                "type": "str",
                "required": False,
                "enum": ["day", "week", "month"],
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

    @property
    def is_available(self) -> bool:
        """Whether the configured provider can execute searches now."""
        available = getattr(self.provider, "is_available", True)
        return bool(available)

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        query = validated_args["query"].strip()
        max_results = validated_args.get("max_results", 3)
        language = validated_args.get("language", "es")
        category = validated_args.get("category", "text")
        freshness = validated_args.get("freshness")

        req = WebSearchRequest(
            query=query,
            max_results=max_results,
            language=language,
            timeout=context.timeout_seconds,
            category=category,
            freshness=freshness,
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
        now_utc = datetime.now(UTC)
        max_news_age = {
            "day": timedelta(days=1),
            "week": timedelta(days=7),
            "month": timedelta(days=31),
        }.get(str(freshness or ""))
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
            published_time = self._parse_publication_time(item.published_at)
            if category == "news":
                if published_time is None:
                    continue
                if published_time > now_utc + timedelta(minutes=5):
                    continue
                if max_news_age is not None and published_time < now_utc - max_news_age:
                    continue
            published_at = published_time.isoformat() if published_time is not None else ""
            results_data.append(
                {
                    "title": title,
                    "snippet": snippet,
                    "url": safe_url,
                    "source": source,
                    "published_at": published_at,
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

    @staticmethod
    def _parse_publication_time(value: str | None) -> datetime | None:
        raw = " ".join(str(value or "").split())[:80]
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

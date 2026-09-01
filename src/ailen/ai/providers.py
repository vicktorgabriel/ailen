"""Provider abstraction and Registry for AILEN external AI inference providers.

Decouples AILEN Core (identity, memory, tools, privacy) from inference providers.
Each provider declares capabilities, authentication mode, health, and test mechanisms.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ailen.ai.contracts import (
    AiBackend,
    AiErrorKind,
)


class AuthMode(StrEnum):
    """Authentication mode required by the provider."""
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"


class ModelCatalogSource(StrEnum):
    """Truthful origin of model IDs shown to an administrator."""

    LIVE = "live"
    CONFIGURED = "configured"
    KNOWN_FALLBACK = "known_fallback"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProviderModelCatalog:
    """Bounded provider model catalog with explicit provenance."""

    models: list[str] = field(default_factory=list)
    source: ModelCatalogSource = ModelCatalogSource.UNAVAILABLE
    detail: str = ""


@dataclass
class ProviderTestResult:
    """Outcome of a real connection/inference test from UI or CLI."""
    ok: bool
    latency_ms: float
    response_text: str = ""
    first_token_ms: float | None = None
    model: str = ""
    error: str = ""
    error_kind: AiErrorKind | None = None
    provider_setup_ms: float | None = None


@dataclass
class ProviderMetadata:
    """Public metadata descriptor for UI and configuration rendering."""
    provider_id: str
    display_name: str
    auth_mode: AuthMode = AuthMode.NONE
    description: str = ""
    default_endpoint: str = ""
    default_model: str = ""
    supported_models: list[str] = field(default_factory=list)
    supports_custom_model: bool = True
    supports_reasoning_effort: bool = False
    homepage_url: str = ""


@runtime_checkable
class AiProvider(AiBackend, Protocol):
    """Unified contract for an AI provider."""

    @property
    def provider_id(self) -> str:
        """Unique provider identifier (for example ``remote:openai`` or ``local``)."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable provider name."""
        ...

    @property
    def metadata(self) -> ProviderMetadata:
        """Provider descriptive metadata."""
        ...

    def list_models(self) -> list[str]:
        """Return available/catalog models for this provider."""
        ...

    def model_catalog(self) -> ProviderModelCatalog:
        """Return models together with their live/configured provenance."""
        ...

    def test_connection(self, prompt: str = "Respondé solamente: OK") -> ProviderTestResult:
        """Execute a quick non-destructive health probe and measure latency."""
        ...


class ProviderRegistry:
    """Central registry of known AI providers and active instances."""

    def __init__(self) -> None:
        self._providers: dict[str, AiProvider] = {}
        self._metadata: dict[str, ProviderMetadata] = {}

    def register(self, provider: AiProvider) -> None:
        """Register an active provider instance."""
        pid = provider.provider_id.lower().strip()
        self._providers[pid] = provider
        self._metadata[pid] = provider.metadata

    def register_metadata(self, meta: ProviderMetadata) -> None:
        """Register provider metadata even before an active instance is configured."""
        self._metadata[meta.provider_id.lower().strip()] = meta

    def has(self, provider_id: str) -> bool:
        """Check if provider instance is registered."""
        return provider_id.lower().strip() in self._providers

    def __contains__(self, provider_id: str) -> bool:
        return self.has(provider_id)

    def get(self, provider_id: str) -> AiProvider | None:
        """Get an active provider instance by ID."""
        return self._providers.get(provider_id.lower().strip())

    def list_providers(self) -> list[AiProvider]:
        """Return all registered providers."""
        return list(self._providers.values())

    def list_all(self) -> list[AiProvider]:
        """Alias for list_providers."""
        return self.list_providers()



    def list_all_metadata(self) -> list[ProviderMetadata]:
        """List metadata for all known providers."""
        return list(self._metadata.values())

    def get_metadata(self, provider_id: str) -> ProviderMetadata | None:
        """Get provider metadata by ID."""
        return self._metadata.get(provider_id.lower().strip())

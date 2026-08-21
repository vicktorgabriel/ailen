"""Cloud AI inference backend for AILEN.

Connects to fast, economical cloud LLM providers (e.g. Gemini, OpenAI, Groq, OpenRouter)
via standard REST HTTP endpoints.
"""

from ailen.ai.contracts import AiRequest, AiResponse, BackendHealth
from ailen.ai.http_backend import GenericOpenAiBackend
from ailen.ai.secrets import SecretResolver
from ailen.domain.enums import ServiceStatus


class CloudAiBackend(GenericOpenAiBackend):
    """Cloud provider client with secret resolver and cost tracking."""

    def __init__(
        self,
        endpoint: str = "",
        model: str = "",
        api_key: str | None = None,
        api_key_env: str = "AILEN_AI_CLOUD_API_KEY",
        api_key_file: str | None = "ai_cloud_key",
        secrets_resolver: SecretResolver | None = None,
        timeout_seconds: float = 10.0,
        provider_name: str = "cloud_llm",
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
    ) -> None:
        resolver = secrets_resolver or SecretResolver()
        resolved_key = resolver.resolve(
            env_var=api_key_env,
            file_name=api_key_file,
            direct_value=api_key,
        )

        super().__init__(
            endpoint=endpoint,
            model=model,
            api_key=resolved_key,
            timeout_seconds=timeout_seconds,
            provider_name=provider_name,
            is_local=False,
            requires_internet=True,
            input_cost_per_million=input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
        )

    def health(self) -> BackendHealth:
        """Cloud access is fail-closed unless endpoint, model and credential exist."""
        if not self.endpoint or not self.model:
            return BackendHealth(ServiceStatus.DISABLED, "Cloud endpoint/model not configured")
        if not self.api_key:
            return BackendHealth(ServiceStatus.DISABLED, "Cloud API key not configured")
        return super().health()

    def generate(self, request: AiRequest) -> AiResponse:
        """Refuse network inference when cloud credentials/configuration are incomplete."""
        if not self.endpoint or not self.model or not self.api_key:
            return AiResponse(
                text="",
                finish_reason="unreachable",
                provider=self.provider_name,
                model=self.model or "unconfigured",
            )
        return super().generate(request)

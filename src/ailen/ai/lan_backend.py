"""LAN Brain inference backend for AILEN.

Connects to a dedicated LAN Brain server located on the local network.
"""

from ailen.ai.http_backend import GenericOpenAiBackend


class LanBrainAiBackend(GenericOpenAiBackend):
    """LAN Brain inference backend with trust boundary awareness."""

    def __init__(
        self,
        endpoint: str = "http://192.168.1.100:8080/v1",
        model: str = "lan-model",
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
        trusted: bool = False,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            provider_name="lan_brain",
            is_local=False,
            requires_internet=False,
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
        )
        self.trusted = trusted

"""AI package: backend contracts, router and fakes."""

from ailen.ai.contracts import (
    AiBackend,
    AiRequest,
    AiResponse,
    AiUsage,
    BackendCapabilities,
    BackendHealth,
    ChatMessage,
    ToolCallRequest,
)
from ailen.ai.fake import FakeAiBackend
from ailen.ai.router import RoutePlan, RouteRequest, RuleBasedRouter

__all__ = [
    "AiBackend",
    "AiRequest",
    "AiResponse",
    "AiUsage",
    "BackendCapabilities",
    "BackendHealth",
    "ChatMessage",
    "FakeAiBackend",
    "RoutePlan",
    "RouteRequest",
    "RuleBasedRouter",
    "ToolCallRequest",
]

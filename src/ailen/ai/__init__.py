"""AI package: backend contracts, router, context builder, policies, backends and orchestrator."""

from ailen.ai.budget import BudgetPolicy
from ailen.ai.cloud_backend import CloudAiBackend
from ailen.ai.context import AiContextBuilder
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
from ailen.ai.http_backend import GenericOpenAiBackend
from ailen.ai.lan_backend import LanBrainAiBackend
from ailen.ai.local_backend import LocalAiBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.privacy import OutboundPrivacyPolicy
from ailen.ai.residency import ModelResidencyPolicy
from ailen.ai.router import (
    ROUTE_CLOUD,
    ROUTE_DEGRADED,
    ROUTE_LAN_BRAIN,
    ROUTE_LOCAL,
    ROUTE_RULE_ONLY,
    RULE_ONLY_INTENTS,
    RoutePlan,
    RouteRequest,
    RuleBasedRouter,
    classify_fast_path_intent,
)
from ailen.ai.secrets import SecretResolver

__all__ = [
    "ROUTE_CLOUD",
    "ROUTE_DEGRADED",
    "ROUTE_LAN_BRAIN",
    "ROUTE_LOCAL",
    "ROUTE_RULE_ONLY",
    "RULE_ONLY_INTENTS",
    "AiBackend",
    "AiContextBuilder",
    "AiOrchestrator",
    "AiRequest",
    "AiResponse",
    "AiUsage",
    "BackendCapabilities",
    "BackendHealth",
    "BudgetPolicy",
    "ChatMessage",
    "CloudAiBackend",
    "FakeAiBackend",
    "GenericOpenAiBackend",
    "LanBrainAiBackend",
    "LocalAiBackend",
    "ModelResidencyPolicy",
    "OutboundPrivacyPolicy",
    "RoutePlan",
    "RouteRequest",
    "RuleBasedRouter",
    "SecretResolver",
    "ToolCallRequest",
    "classify_fast_path_intent",
]

"""Contracts and data models for local inference runtimes."""

from dataclasses import dataclass
from enum import Enum


class RuntimeType(str, Enum):
    """Supported decoupled local inference runtime types."""
    LLAMA_SERVER = "llama.cpp server"
    OLLAMA = "Ollama"
    CUSTOM = "Custom OpenAI-compatible Server"
    NONE = "None"


class RuntimeStatus(str, Enum):
    """Lifecycle and operational status of a local runtime."""
    INSTALLED = "INSTALLED"
    RUNNING = "RUNNING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class RuntimeHealth:
    """Health and responsiveness status of a runtime endpoint."""
    status: RuntimeStatus
    endpoint: str
    is_running: bool
    version: str | None = None
    details: str = ""


@dataclass
class ExternalRuntimeDescriptor:
    """Metadata describing a detected or configured local runtime."""
    runtime_type: RuntimeType
    executable_path: str | None
    endpoint: str
    is_detected: bool
    status: RuntimeStatus = RuntimeStatus.UNAVAILABLE
    health: RuntimeHealth | None = None

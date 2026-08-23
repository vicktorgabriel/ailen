"""Tool contracts and data structures for AILEN.

See docs/architecture/MODULE_CONTRACTS.md section 15 and ADR-010.
Every tool declares schema, permissions, allowed modes, privacy level, and timeout.
Prohibited: arbitrary shell execution.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode

ALL_SOCIAL_MODES: frozenset[SocialMode] = frozenset(SocialMode)


@dataclass
class ToolContext:
    """Execution context given to a tool."""

    session_id: str | None = None
    mode: SocialMode = SocialMode.WORKSHOP
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    correlation_id: str | None = None
    timeout_seconds: float = 5.0
    user_id: str | None = None
    internet_available: bool = True
    network_access_allowed: bool = False


@dataclass
class ToolResult:
    """Normalized structured tool output. Data must never expose sensitive secrets."""

    success: bool
    tool_name: str = ""
    status_code: str = "OK"
    message: str = ""
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    requires_llm_summary: bool = False
    error_code: ErrorCode | None = None

    def __post_init__(self) -> None:
        if not self.message and self.summary:
            self.message = self.summary
        elif not self.summary and self.message:
            self.summary = self.message
        if not self.success and self.status_code == "OK":
            self.status_code = "ERROR"


@runtime_checkable
class Tool(Protocol):
    """Allowlisted tool contract."""

    @property
    def name(self) -> str:
        """Stable unique tool name."""
        ...

    @property
    def description(self) -> str:
        """Short human-readable description of what the tool does."""
        ...

    @property
    def schema(self) -> dict[str, Any]:
        """JSON-schema-like argument declaration."""
        ...

    @property
    def permissions(self) -> list[str]:
        """Required permissions/capabilities."""
        ...

    @property
    def allowed_modes(self) -> set[SocialMode]:
        """Social modes in which this tool is allowed to execute."""
        ...

    @property
    def privacy_level(self) -> PrivacyLevel:
        """Minimum privacy requirement or classification of the tool."""
        ...

    @property
    def requires_network(self) -> bool:
        """Whether this tool requires outbound network connectivity."""
        ...

    @property
    def destructive(self) -> bool:
        """Whether this tool performs irreversible or destructive operations."""
        ...

    @property
    def timeout_seconds(self) -> float:
        """Maximum execution timeout for this tool."""
        ...

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute with pre-validated arguments. Never trust unvalidated LLM output."""
        ...


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize arguments against a JSON-like schema specification.

    Supported schema format:
    ``{"properties": {name: {"type": "str|int|float|bool|list|dict", "required": bool,
    "default": val, "min": x, "max": y, "min_len": x, "max_len": y, "enum": [...]}}}``
    """
    properties: dict[str, Any] = schema.get("properties", {})
    cleaned: dict[str, Any] = {}

    for key in args:
        if key not in properties:
            raise ValueError(f"argumento desconocido: {key}")

    type_map: dict[str, tuple[type, ...]] = {
        "str": (str,),
        "int": (int,),
        "float": (int, float),
        "bool": (bool,),
        "list": (list,),
        "dict": (dict,),
    }

    for key, spec in properties.items():
        required = spec.get("required", False)
        if key not in args:
            if "default" in spec:
                cleaned[key] = spec["default"]
                continue
            if required:
                raise ValueError(f"falta argumento requerido: {key}")
            continue

        value = args[key]
        spec_type = spec.get("type", "str")
        expected = type_map.get(spec_type, (object,))

        # Strict bool vs int check: bool is subclass of int in Python
        if spec_type == "int" and isinstance(value, bool):
            raise ValueError(f"tipo inválido para {key}: se esperaba int")
        if spec_type == "float" and isinstance(value, bool):
            raise ValueError(f"tipo inválido para {key}: se esperaba float")
        if spec_type == "bool" and not isinstance(value, bool):
            raise ValueError(f"tipo inválido para {key}: se esperaba bool")
        if not isinstance(value, expected):
            raise ValueError(f"tipo inválido para {key}: se esperaba {spec_type}")  # noqa: TRY004

        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"valor fuera de enum para {key}")
        if "min" in spec and isinstance(value, (int, float)) and value < spec["min"]:
            raise ValueError(f"valor por debajo del mínimo para {key}")
        if "max" in spec and isinstance(value, (int, float)) and value > spec["max"]:
            raise ValueError(f"valor por encima del máximo para {key}")
        if "min_len" in spec and isinstance(value, (str, list)) and len(value) < spec["min_len"]:
            raise ValueError(f"longitud por debajo del mínimo para {key}")
        if "max_len" in spec and isinstance(value, (str, list)) and len(value) > spec["max_len"]:
            raise ValueError(f"longitud por encima del máximo para {key}")

        cleaned[key] = value

    return cleaned

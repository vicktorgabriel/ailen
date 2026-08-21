"""Tool contracts. Ver MODULE_CONTRACTS.md sección 15.

Cada tool declara schema, permisos y timeout. Prohibido shell general.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ailen.domain.enums import ErrorCode, SocialMode


@dataclass
class ToolContext:
    """Execution context given to a tool."""
    session_id: str | None = None
    mode: SocialMode = SocialMode.WORKSHOP
    correlation_id: str | None = None
    timeout_seconds: float = 5.0


@dataclass
class ToolResult:
    """Normalized tool output. `data` nunca expone secretos."""
    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: ErrorCode | None = None


@runtime_checkable
class Tool(Protocol):
    """Allowlisted tool contract."""

    @property
    def name(self) -> str:
        """Stable tool name."""
        ...

    @property
    def schema(self) -> dict[str, Any]:
        """JSON-schema-like argument declaration."""
        ...

    @property
    def permissions(self) -> list[str]:
        """Required permissions/capabilities."""
        ...

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute with pre-validated arguments. Nunca confiar en salida LLM."""
        ...


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Minimal argument validation against a simple schema.

    Schema soportado (subset propio, suficiente para el baseline):
    ``{"properties": {name: {"type": "str|int|float|bool", "required": bool,
    "min": x, "max": y, "enum": [...]}}}``
    """
    properties = schema.get("properties", {})
    cleaned: dict[str, Any] = {}

    for key, value in args.items():
        if key not in properties:
            raise ValueError(f"argumento desconocido: {key}")

    type_map: dict[str, tuple[type, ...]] = {
        "str": (str,),
        "int": (int,),
        "float": (int, float),
        "bool": (bool,),
    }
    for key, spec in properties.items():
        required = spec.get("required", False)
        if key not in args:
            if required:
                raise ValueError(f"falta argumento requerido: {key}")
            continue
        value = args[key]
        expected = type_map[spec["type"]]
        if spec["type"] == "int" and isinstance(value, bool):
            raise ValueError(f"tipo inválido para {key}: se esperaba int")
        if not isinstance(value, expected) or (
            spec["type"] == "bool" and not isinstance(value, bool)
        ):
            raise ValueError(f"tipo inválido para {key}: se esperaba {spec['type']}")
        if spec["type"] == "int" and isinstance(value, bool):
            raise ValueError(f"tipo inválido para {key}")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"valor fuera de enum para {key}")
        if "min" in spec and isinstance(value, (int, float)) and value < spec["min"]:
            raise ValueError(f"valor por debajo del mínimo para {key}")
        if "max" in spec and isinstance(value, (int, float)) and value > spec["max"]:
            raise ValueError(f"valor por encima del máximo para {key}")
        cleaned[key] = value
    return cleaned

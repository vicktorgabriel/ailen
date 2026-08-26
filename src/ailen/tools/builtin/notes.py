"""Notes tool for AILEN.

Provides persistent note creation, listing, and searching using SQLite.
All input text is strictly treated as data, never as code or commands.
See ADR-010.
"""

from typing import Any, ClassVar

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.memory.repository import MemoryRepository
from ailen.tools.contracts import ToolContext, ToolResult


class NotesTool:
    """Persistent SQLite-backed notes tool."""

    name: str = "notes"
    description: str = "Guarda, lista o busca notas del usuario de forma persistente."
    intent_hints = (
        "nota", "notas", "anota", "anotá", "anotame", "apunta", "apuntá",
        "guardar", "guardame", "apuntado", "comprar",
    )
    intent_guidance = (
        "Nunca inventes texto faltante para crear una nota. 'nota comprar X' puede significar "
        "guardar una nota, no una compra financiera. Si preguntan cuál/qué nota fue guardada o "
        "anotada y no nombran un tema concreto, usá notes list; no busques la palabra 'nota'. "
        "Si preguntan por contenido concreto de una nota, como 'qué tengo que comprar mañana', "
        "usá notes search con sólo palabras de contenido útiles, por ejemplo 'comprar mañana'."
    )
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "action": {
                "type": "str",
                "required": True,
                "enum": ["create", "add", "list", "search"],
            },
            "text": {
                "type": "str",
                "required": False,
                "max_len": 1000,
            },
            "query": {
                "type": "str",
                "required": False,
                "max_len": 200,
            },
            "limit": {
                "type": "int",
                "required": False,
                "min": 1,
                "max": 50,
                "default": 10,
            },
        },
    }
    permissions: ClassVar[list[str]] = ["memory.write", "memory.read"]
    allowed_modes: ClassVar[set[SocialMode]] = {
        SocialMode.HOME,
        SocialMode.WORKSHOP,
        SocialMode.PRIVATE,
    }
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 2.0

    def __init__(self, repository: MemoryRepository | None = None) -> None:
        self.repository = repository

    @property
    def is_available(self) -> bool:
        return self.repository is not None

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        repository = self.repository
        if repository is None:
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="UNAVAILABLE",
                message="Las notas persistentes requieren la base de datos local.",
                error_code=ErrorCode.TOOL_UNAVAILABLE,
            )

        action = validated_args["action"]

        if action in {"create", "add"}:
            text = (validated_args.get("text") or "").strip()
            if not text:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="INVALID_ARGS",
                    message="Falta el texto de la nota.",
                    error_code=ErrorCode.TOOL_ARGS_INVALID,
                )

            note = repository.create_note(content=text)
            note_id = note.note_id

            msg = f"Nota guardada: {text}"
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={"note_id": note_id, "content": text},
                requires_llm_summary=False,
            )

        if action == "list":
            limit = validated_args.get("limit", 10)
            notes = repository.list_notes(limit=limit)
            note_items = [
                {"note_id": n.note_id, "content": n.content, "created_at": n.created_at}
                for n in notes
            ]

            if not note_items:
                msg = "No tenés ninguna nota guardada."
            elif len(note_items) == 1:
                msg = f"Tenés 1 nota: {note_items[0]['content']}."
            else:
                texts = "; ".join(f"{i+1}) {n['content']}" for i, n in enumerate(note_items[:5]))
                msg = f"Tenés {len(note_items)} notas: {texts}."

            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={"count": len(note_items), "notes": note_items},
                requires_llm_summary=False,
            )

        if action == "search":
            query = (validated_args.get("query") or "").strip()
            limit = validated_args.get("limit", 10)
            if not query:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="INVALID_ARGS",
                    message="Se requiere un texto de búsqueda para las notas.",
                    error_code=ErrorCode.TOOL_ARGS_INVALID,
                )

            matches = repository.search_notes(query=query, limit=limit)
            results = [
                {"note_id": n.note_id, "content": n.content, "created_at": n.created_at}
                for n in matches
            ]

            if not results:
                msg = f"No se encontraron notas con '{query}'."
            elif len(results) == 1:
                msg = f"Encontré esta nota: {results[0]['content']}."
            else:
                preview = "; ".join(
                    f"{i + 1}) {item['content']}"
                    for i, item in enumerate(results[:5])
                )
                msg = f"Encontré {len(results)} notas: {preview}."

            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={"query": query, "count": len(results), "notes": results},
                requires_llm_summary=False,
            )

        return ToolResult(
            success=False,
            tool_name=self.name,
            status_code="INVALID_ARGS",
            message=f"Acción de notas desconocida: {action}",
            error_code=ErrorCode.TOOL_ARGS_INVALID,
        )

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
        self._fallback_notes: list[str] = []

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
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

            if self.repository is not None:
                note = self.repository.create_note(content=text)
                note_id = note.note_id
            else:
                self._fallback_notes.append(text)
                note_id = f"mem-{len(self._fallback_notes)}"

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
            if self.repository is not None:
                notes = self.repository.list_notes(limit=limit)
                note_items = [{"note_id": n.note_id, "content": n.content, "created_at": n.created_at} for n in notes]
            else:
                note_items = [{"note_id": f"mem-{i+1}", "content": c, "created_at": ""} for i, c in enumerate(self._fallback_notes[:limit])]

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

            if self.repository is not None:
                matches = self.repository.search_notes(query=query, limit=limit)
                results = [{"note_id": n.note_id, "content": n.content, "created_at": n.created_at} for n in matches]
            else:
                results = [
                    {"note_id": f"mem-{i+1}", "content": c, "created_at": ""}
                    for i, c in enumerate(self._fallback_notes)
                    if query.lower() in c.lower()
                ][:limit]

            if not results:
                msg = f"No se encontraron notas con '{query}'."
            else:
                msg = f"Se encontraron {len(results)} notas con '{query}'."

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

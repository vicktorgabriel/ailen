"""Bounded administration of explicit memories; no conversational context export."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ailen.domain.enums import PrivacyLevel
from ailen.domain.models import MemoryItem
from ailen.memory.repository import MemoryRepository


@dataclass(frozen=True)
class MemoryPage:
    items: list[MemoryItem]
    total: int
    page: int
    page_size: int = 50


class MemoryAdmin(Protocol):
    def list_memories(self, query: str = "", include_private: bool = False, page: int = 1) -> MemoryPage: ...
    def get(self, memory_id: str, include_private: bool = False) -> MemoryItem: ...
    def save(
        self, content: str, category: str = "general", scope: str = "PRIVATE",
        memory_id: str = "", confirmed: bool = False,
    ) -> MemoryItem: ...
    def delete(self, memory_id: str, confirmed: bool = False) -> None: ...
    def export(
        self, query: str = "", include_private: bool = False, confirmed: bool = False,
    ) -> list[MemoryItem]: ...


class MemoryAdminService:
    """Admin-only service; callers must authenticate and check CSRF for writes.

    Private/restricted records require an explicit viewing/export opt-in.
    This boundary never changes the Core's conversational privacy policy.
    """

    EXPORT_LIMIT = 1000

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    @staticmethod
    def _query(query: str) -> str:
        if len(query) > 200 or "\x00" in query:
            raise ValueError("La búsqueda admite hasta 200 caracteres.")
        return query.strip()

    @staticmethod
    def _id(memory_id: str) -> str:
        if not re.fullmatch(r"mem-[A-Za-z0-9_-]{1,80}", memory_id):
            raise ValueError("Identificador de recuerdo inválido.")
        return memory_id

    def list_memories(self, query: str = "", include_private: bool = False, page: int = 1) -> MemoryPage:
        if not 1 <= page <= 10000:
            raise ValueError("Página fuera de rango.")
        items, total = self._repository.admin_list_memories(
            self._query(query), include_private=include_private, limit=50, offset=(page - 1) * 50,
        )
        return MemoryPage(items, total, page)

    def get(self, memory_id: str, include_private: bool = False) -> MemoryItem:
        item = self._repository.get_memory(self._id(memory_id))
        if item is None or (item.scope != PrivacyLevel.PUBLIC and not include_private):
            raise LookupError("Recuerdo no encontrado en el alcance seleccionado.")
        return item

    def save(
        self, content: str, category: str = "general", scope: str = "PRIVATE",
        memory_id: str = "", confirmed: bool = False,
    ) -> MemoryItem:
        content, category = content.strip(), category.strip()
        if not content or len(content) > 4000 or "\x00" in content:
            raise ValueError("El recuerdo debe contener entre 1 y 4000 caracteres.")
        if not category or len(category) > 80 or "\x00" in category:
            raise ValueError("La categoría debe contener entre 1 y 80 caracteres.")
        try:
            privacy = PrivacyLevel(scope)
        except ValueError:
            raise ValueError("Nivel de privacidad inválido.") from None
        if not confirmed:
            raise ValueError("Confirmá el contenido del recuerdo y su privacidad.")
        if memory_id:
            updated = self._repository.update_memory(
                self._id(memory_id), content=content, category=category, scope=privacy,
            )
            if not updated:
                raise LookupError("Recuerdo no encontrado.")
            return self.get(memory_id, include_private=True)
        return self._repository.add_memory(content, category=category, scope=privacy)

    def delete(self, memory_id: str, confirmed: bool = False) -> None:
        if not confirmed:
            raise ValueError("Confirmá el borrado individual del recuerdo.")
        if not self._repository.delete_memory(self._id(memory_id)):
            raise LookupError("Recuerdo no encontrado.")

    def export(
        self, query: str = "", include_private: bool = False, confirmed: bool = False,
    ) -> list[MemoryItem]:
        if not confirmed:
            raise ValueError("Confirmá la descarga de los recuerdos seleccionados.")
        items, total = self._repository.admin_list_memories(
            self._query(query), include_private=include_private, limit=self.EXPORT_LIMIT + 1,
        )
        if total > self.EXPORT_LIMIT:
            raise ValueError("La exportación admite hasta 1000 recuerdos. Acotá la búsqueda.")
        return items

"""Server-rendered memory admin forms; all record content is escaped."""

from urllib.parse import urlencode

from ailen.domain.enums import PrivacyLevel
from ailen.domain.models import MemoryItem
from ailen.services.memory_admin_service import MemoryPage
from ailen.web.templates import render


def memory_content(
    page: MemoryPage, *, csrf: str, query: str, include_private: bool,
    editing: MemoryItem | None = None, saved: bool = False,
) -> str:
    params = {"q": query, "include_private": "1" if include_private else "0"}
    rows = "".join(render(
        "memory_row.html", memory_id=item.memory_id, content=item.content,
        category=item.category, scope=item.scope.value, updated_at=item.updated_at,
        expires_at=item.expires_at or "Sin vencimiento", csrf=csrf,
        edit_url="/memoria?" + urlencode({**params, "edit": item.memory_id}),
    ) for item in page.items)
    if not rows:
        rows = '<tr><td colspan="5">Sin recuerdos en el alcance seleccionado.</td></tr>'
    navigation = []
    for number, label in ((page.page - 1, "Anterior"), (page.page + 1, "Siguiente")):
        if number >= 1 and (number < page.page or page.page * page.page_size < page.total):
            navigation.append(render(
                "memory_link.html", url="/memoria?" + urlencode({**params, "page": number}),
                label=label,
            ))
    scope = editing.scope if editing else PrivacyLevel.PRIVATE
    return render(
        "memory.html", csrf=csrf, query=query, rows=rows,
        total=page.total, page=page.page, navigation=" ".join(navigation),
        private_checked=" checked" if include_private else "",
        include_private="1" if include_private else "0",
        action="update" if editing else "create",
        form_title="Editar recuerdo" if editing else "Nuevo recuerdo",
        memory_id=editing.memory_id if editing else "",
        content=editing.content if editing else "", category=editing.category if editing else "general",
        scope_options="".join(render(
            "memory_option.html", value=value.value, label=value.value,
            selected=" selected" if value == scope else "",
        ) for value in PrivacyLevel),
        notice="Cambio guardado." if saved else "",
    )

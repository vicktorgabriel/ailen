"""Server-rendered agent administration panel."""

from ailen.services.agent_admin_service import AgentSnapshot
from ailen.web.templates import render


def agent_content(snapshot: AgentSnapshot, csrf: str, flash: str) -> str:
    if not snapshot.confirmations_available:
        confirmations = render("agent_empty.html", message="No disponible")
    elif snapshot.confirmations:
        confirmations = "".join(render(
            "agent_confirmation.html",
            confirmation_id=item.id,
            tool_name=item.tool_name,
            summary=item.summary,
            seconds_remaining=item.seconds_remaining,
            csrf=csrf,
        ) for item in snapshot.confirmations)
    else:
        confirmations = render("agent_empty.html", message="Sin confirmaciones pendientes")

    if not snapshot.events_available:
        events = render("agent_empty.html", message="No disponible")
    elif snapshot.events:
        events = "".join(render(
            "agent_event.html", tool_name=item.tool_name, status=item.status,
            created_at=item.created_at, arguments=item.arguments_redacted,
        ) for item in snapshot.events)
    else:
        events = render("agent_empty.html", message="Sin eventos")

    roots = "".join(render("agent_root.html", path=root) for root in snapshot.file_roots)
    if not roots:
        roots = render("agent_empty.html", message="Sin raíces configuradas")
    return render(
        "agent.html", autonomy=f"N{snapshot.max_autonomy_level}", roots=roots,
        confirmations=confirmations, events=events, flash=flash,
    )

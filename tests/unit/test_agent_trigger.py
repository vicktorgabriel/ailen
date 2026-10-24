"""Explicit, deliberately narrow voice commands for Core agent tasks."""

import pytest

from ailen.core.agent_trigger import parse_agent_command


@pytest.mark.parametrize(
    ("text", "kind", "task"),
    [
        ("Agente, ordená estos archivos", "submit", "ordená estos archivos"),
        ("modo agente: resumí la nota", "submit", "resumí la nota"),
        ("tarea para el agente: revisá el documento", "submit", "revisá el documento"),
        ("¡MODO AGENTE: buscá archivos duplicados", "submit", "buscá archivos duplicados"),
        ("agente, cancelá la tarea", "cancel", None),
        ("agente, confirmo", "confirm", None),
        ("agente, denegá", "deny", None),
        ("cancelá la tarea", "cancel", None),
        ("CANCELA LA TAREA DEL AGENTE.", "cancel", None),
        ("detené al agente!", "cancel", None),
        ("confirmo", "confirm", None),
        ("Sí, confirmo.", "confirm", None),
        ("denegá", "deny", None),
        ("No, cancelá la acción.", "deny", None),
    ],
)
def test_explicit_agent_commands(text: str, kind: str, task: str | None) -> None:
    command = parse_agent_command(text)

    assert command is not None
    assert command.kind == kind
    assert command.task == task


@pytest.mark.parametrize(
    "text",
    [
        "el agente de viajes me llamó",
        "hacé una tarea",
        "quiero hablar con el agente",
        "confirmo que mañana llueve",
        "podés cancelar la tarea de matemáticas",
        "modo agente",
        "agente",
        "tarea para el agente:",
        "el agente de seguros me llamó",
        "agente de seguros, revisá mis pólizas",
        "modo agente buscá archivos duplicados",
        "agente, buscá duplicados",
        "modo agente: buscá duplicados",
        "tarea para el agente, revisá todos los archivos",
    ],
)
def test_ordinary_or_incomplete_phrases_are_not_intercepted(text: str) -> None:
    assert parse_agent_command(text) is None

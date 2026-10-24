"""Narrow, explicit voice phrases that address the supervised Core agent."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

AgentCommandKind = Literal["submit", "cancel", "confirm", "deny"]


@dataclass(frozen=True, slots=True)
class AgentCommand:
    """A bounded agent command parsed from an explicit utterance."""

    kind: AgentCommandKind
    task: str | None = None


_SUBMIT_PATTERNS = (
    re.compile(r"^[\s¡¿,.!?]*agente\s*[,:]\s*(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^[\s¡¿,.!?]*modo\s+agente\s*[,:]\s*(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^[\s¡¿,.!?]*tarea\s+para\s+el\s+agente\s*:\s*(.+?)\s*$", re.IGNORECASE),
)


def _normalize_phrase(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(
        char for char in decomposed if not unicodedata.category(char).startswith("M")
    )
    words = re.sub(r"[^a-z0-9]+", " ", without_marks)
    return " ".join(words.split())


def parse_agent_command(text: str) -> AgentCommand | None:
    """Parse only explicit agent commands; ordinary conversation is untouched.

    Punctuation is ignored for fixed control phrases. Submit commands require
    an explicit addressing prefix and non-empty task; the returned task keeps
    the operator's original spelling and accents.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    candidate = text.strip()
    command_text = candidate
    for pattern in _SUBMIT_PATTERNS:
        match = pattern.fullmatch(candidate)
        if match is not None:
            command_text = match.group(1).strip()
            break

    # A call prefix may introduce a control phrase; classify it before treating
    # the remainder as a task (e.g. "agente, confirmo").
    normalized = _normalize_phrase(command_text)
    if normalized in {
        "cancela la tarea",
        "cancela la tarea del agente",
        "detene al agente",
    }:
        return AgentCommand(kind="cancel")
    if normalized in {"confirmo", "si confirmo"}:
        return AgentCommand(kind="confirm")
    if normalized in {"denega", "no cancela la accion"}:
        return AgentCommand(kind="deny")

    for pattern in _SUBMIT_PATTERNS:
        match = pattern.fullmatch(candidate)
        if match is None:
            continue
        task = match.group(1).strip().strip(" \t\r\n,;:!?-").strip()
        if len(_normalize_phrase(task).split()) >= 3:
            return AgentCommand(kind="submit", task=task)
    return None

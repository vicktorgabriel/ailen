"""Bounded local-LLM fallback for imperfect voice tool intents.

The model may only *propose* one registered, non-network, non-destructive tool call.
Core validates the proposal against the tool schema and ToolExecutor enforces all
normal permissions before execution. The model never executes a tool directly.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from ailen.ai.contracts import AiBackend, AiRequest, ChatMessage
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.memory.repository import MemoryRepository
from ailen.tools.contracts import validate_args
from ailen.tools.intent_resolver import IntentResolution
from ailen.tools.registry import ToolRegistry


class SemanticToolIntentResolver:
    """Use a trusted local model as a constrained intent parser when rules miss."""

    _HINT_TERMS = (
        "hora", "fecha", "día", "dia",
        "volumen", "silencio", "mute", "sonido", "audio",
        "nota", "notas", "anota", "anotá", "apunta", "apuntá", "recorda", "recordá",
        "comprar", "mañana", "recordatorio",
        "temporizador", "timer", "alarma", "cuenta regresiva", "cronómetro", "cronometro",
        "música", "musica", "canción", "cancion", "pausa", "siguiente",
        "sistema", "hardware", "cpu", "ram", "batería", "bateria",
    )

    def __init__(
        self,
        backend: AiBackend | None,
        registry: ToolRegistry,
        repository: MemoryRepository | None = None,
        min_confidence: float = 0.78,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.repository = repository
        self.min_confidence = min_confidence
        self.request_timeout_seconds = max(1.0, request_timeout_seconds)

    def should_attempt(self, text: str, session_id: str | None = None) -> bool:
        """Avoid a second inference call for ordinary conversational turns."""
        clean = " ".join((text or "").lower().split())
        if self._has_any_hint(clean, self._HINT_TERMS):
            return True
        # Very short elliptical questions often come from imperfect STT. Only use
        # history as a hint when the recent conversation itself involved a tool domain.
        if self.repository is not None and session_id and len(clean.split()) <= 5:
            try:
                recent = self.repository.get_session_messages(session_id, limit=4)
            except Exception:  # noqa: BLE001
                recent = []
            recent_text = " ".join(m.content.lower() for m in recent)
            return self._has_any_hint(recent_text, self._HINT_TERMS)
        return False

    def resolve(
        self,
        text: str,
        *,
        session_id: str | None,
        mode: SocialMode,
        privacy_level: PrivacyLevel,
    ) -> IntentResolution | None:
        """Return a validated tool proposal, or None when uncertain/not applicable."""
        if self.backend is None or not self.should_attempt(text, session_id):
            return None
        try:
            caps = self.backend.capabilities()
        except Exception:  # noqa: BLE001
            return None
        if not caps.is_local or caps.requires_internet:
            return None

        allowed = self._allowed_tools(mode)
        allowed = self._narrow_tools_for_text(text, allowed)
        if not allowed:
            return None

        history = self._recent_history(session_id)
        tool_specs = [
            {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.schema,
            }
            for tool in allowed.values()
        ]
        prompt = (
            "Interpretá el último texto como posible comando de voz para AILEN. "
            "El STT puede omitir artículos, signos o alguna palabra. Usá el historial sólo para resolver referencias. "
            "Elegí una herramienta únicamente si la intención de usar/consultar una capacidad local es suficientemente clara. "
            "Si es charla, una frase incompleta sin intención clara, o faltan datos imprescindibles, devolvé chat. "
            "Nunca inventes texto faltante para crear una nota. 'nota comprar X' puede significar guardar una nota, no una compra financiera. "
            "Si preguntan cuál/qué nota fue guardada o anotada y no nombran un tema concreto, usá notes list; no busques la palabra 'nota'. "
            "Si preguntan por contenido concreto de una nota, como 'qué tengo que comprar mañana', usá notes search con sólo palabras de contenido útiles, por ejemplo 'comprar mañana'. "
            "Devolvé SOLO JSON válido, sin markdown ni explicación, con esta forma exacta: "
            '{"kind":"tool|chat","tool":"nombre_o_vacio","arguments":{},"confidence":0.0}.\n'
            f"TOOLS={json.dumps(tool_specs, ensure_ascii=False)}\n"
            f"HISTORIAL={json.dumps(history, ensure_ascii=False)}\n"
            f"TEXTO={json.dumps(text, ensure_ascii=False)}"
        )
        request = AiRequest(
            request_id=f"intent-{uuid.uuid4().hex[:12]}",
            system_context=(
                "Sos un parser de intención local y restringido. No respondas al usuario. "
                "No ejecutes acciones. Sólo clasificá usando la allowlist proporcionada."
            ),
            messages=[ChatMessage(role="user", content=prompt)],
            mode=mode,
            max_output_tokens=80,
            timeout_seconds=self.request_timeout_seconds,
            privacy_level=privacy_level,
            metadata={"purpose": "semantic_tool_intent"},
        )

        started = time.monotonic()
        try:
            response = self.backend.generate(request)
            payload = self._parse_json(response.text)
        except Exception:  # noqa: BLE001
            return None
        latency_ms = max(response.latency_ms, (time.monotonic() - started) * 1000.0)
        if payload is None or payload.get("kind") != "tool":
            return None

        tool_name = payload.get("tool")
        args = payload.get("arguments", {})
        confidence = payload.get("confidence", 0.0)
        if not isinstance(tool_name, str) or tool_name not in allowed:
            return None
        if not isinstance(args, dict):
            return None
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return None
        confidence_f = float(confidence)
        if confidence_f < self.min_confidence or confidence_f > 1.0:
            return None

        try:
            validated = validate_args(allowed[tool_name].schema, args)
        except ValueError:
            return None

        return IntentResolution(
            intent=f"semantic_{tool_name}",
            tool_name=tool_name,
            tool_args=validated,
            requires_llm=False,
            confidence=confidence_f,
            raw_text=text,
            source="semantic_local",
            latency_ms=latency_ms,
        )


    @staticmethod
    def _narrow_tools_for_text(text: str, allowed: dict[str, Any]) -> dict[str, Any]:
        """Reduce semantic parser prompt to likely tool domains for lower latency.

        This only narrows an already policy-approved allowlist; it never adds a tool.
        """
        clean = " ".join((text or "").lower().split())
        domain_hints: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
            (("hora", "fecha", "día", "dia"), ("clock",)),
            (("volumen", "silencio", "mute", "sonido", "audio"), ("volume",)),
            (("nota", "notas", "anota", "anotá", "anotame", "recorda", "recordá", "guardar", "guardame", "comprar"), ("notes",)),
            (("temporizador", "timer", "alarma", "cuenta regresiva", "cronómetro", "cronometro"), ("timer",)),
            (("música", "musica", "canción", "cancion", "pausa", "siguiente"), ("music",)),
            (("sistema", "hardware", "cpu", "ram", "batería", "bateria"), ("system_status",)),
        ]
        selected: set[str] = set()
        for hints, tools in domain_hints:
            if SemanticToolIntentResolver._has_any_hint(clean, hints):
                selected.update(tools)
        if not selected:
            return allowed
        narrowed = {name: tool for name, tool in allowed.items() if name in selected}
        return narrowed or allowed

    @staticmethod
    def _has_any_hint(text: str, hints: tuple[str, ...]) -> bool:
        """Match intent hints as complete lexical terms, never substrings.

        For example, the clock hint ``dia`` must not match ``inmediato``.
        Multi-word hints still work because boundaries are checked only at the
        beginning and end of the complete escaped hint.
        """
        return any(
            re.search(rf"(?<!\w){re.escape(hint)}(?!\w)", text) is not None
            for hint in hints
        )

    def _allowed_tools(self, mode: SocialMode) -> dict[str, Any]:
        allowed: dict[str, Any] = {}
        for tool in self.registry.list_tools():
            if getattr(tool, "requires_network", False) or getattr(tool, "destructive", False):
                continue
            allowed_modes = getattr(tool, "allowed_modes", set(SocialMode))
            if mode not in allowed_modes:
                continue
            if mode in {SocialMode.SHOP, SocialMode.PUBLIC} and getattr(
                tool, "privacy_level", PrivacyLevel.PRIVATE
            ) == PrivacyLevel.PRIVATE:
                continue
            allowed[tool.name] = tool
        return allowed

    def _recent_history(self, session_id: str | None) -> list[dict[str, str]]:
        if self.repository is None or not session_id:
            return []
        try:
            messages = self.repository.get_session_messages(session_id, limit=6)
        except Exception:  # noqa: BLE001
            return []
        return [
            {"role": m.role, "content": m.content[:240]}
            for m in messages
            if m.role in {"user", "assistant"}
        ]

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        raw = (text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

"""Deterministic Intent Resolver for AILEN Core.

Resolves direct unambiguous user commands into structured tool calls before
invoking LLM inference.
See ADR-010 and docs/architecture/MODULE_CONTRACTS.md.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from ailen.tools.reminder_time import extract_reminder_request


@dataclass
class IntentResolution:
    """Result of intent resolution."""

    intent: str  # clock, timer, reminders, volume, music, notes, web_search, chat
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    requires_llm: bool = False
    confidence: float = 1.0
    raw_text: str = ""
    source: str = "deterministic"
    latency_ms: float = 0.0


class IntentResolver:
    """Deterministic, conservative intent resolver for AILEN."""

    def resolve(self, text: str) -> IntentResolution:
        """Parse user input text deterministically.

        False positives are worse than false negatives. Ambiguous or conceptual
        questions remain as chat intent.
        """
        if not text or not text.strip():
            return IntentResolution(intent="chat", raw_text=text, confidence=0.0)

        cleaned = " ".join(text.lower().strip().split()).strip(" ¿?¡!.,;:")

        # 1. Explicit web search commands take precedence over conceptual negative
        # filters: "buscá en internet X" is an unambiguous user request to search,
        # even when X contains a keyword like "volumen" or "batería".
        search_res = self._match_web_search(cleaned, text)
        if search_res:
            return search_res

        # 2. Negative filters: explicitly conceptual/educational questions that must NOT trigger tools
        if self._is_negative_case(cleaned):
            return IntentResolution(intent="chat", raw_text=text, requires_llm=True, confidence=1.0)

        # 3. Clock Intent
        clock_res = self._match_clock(cleaned, text)
        if clock_res:
            return clock_res

        # 3. Volume Intent
        volume_res = self._match_volume(cleaned, text)
        if volume_res:
            return volume_res

        # 4. Persistent Reminder Intent. This must run before notes so an
        # explicit temporal anchor is never flattened into an atemporal note.
        reminder_res = self._match_reminders(cleaned, text)
        if reminder_res:
            return reminder_res

        # 5. Timer Intent
        timer_res = self._match_timer(cleaned, text)
        if timer_res:
            return timer_res

        # 6. Music Intent
        music_res = self._match_music(cleaned, text)
        if music_res:
            return music_res

        # 7. Notes Intent
        notes_res = self._match_notes(cleaned, text)
        if notes_res:
            return notes_res

        # 8. System Status Intent
        status_res = self._match_system_status(cleaned, text)
        if status_res:
            return status_res

        # 9. Natural freshness questions. Local tools above get first refusal;
        # only an actual question asking for time-sensitive public information
        # is sent to web, so casual phrases such as "hoy estoy cansado" remain chat.
        fresh_web_res = self._match_fresh_web_question(cleaned, text)
        if fresh_web_res:
            return fresh_web_res

        # Default: General conversational chat handled by AI Router
        return IntentResolution(intent="chat", raw_text=text, requires_llm=True, confidence=0.5)

    @staticmethod
    def _strip_prefix_preserving_case(raw_text: str, prefix: str) -> str | None:
        """Remove a lowercase prefix from raw text case-insensitively.

        Returns the remainder of the ORIGINAL collapsed text (original casing
        preserved) or None when the prefix does not match.
        """
        collapsed = " ".join(raw_text.strip().split()).lstrip("¿?¡!.,;:")
        if collapsed.lower().startswith(prefix):
            return collapsed[len(prefix):].strip()
        return None

    def _is_negative_case(self, clean: str) -> bool:
        """Check for known negative phrases that contain keywords but are questions/explanations."""
        # Volume negative phrases (geometry, sound theory)
        if any(term in clean for term in (
            "volumen de un cilindro", "volumen de una esfera", "volumen de un cubo",
            "volumen de un prisma", "volumen del cilindro", "fórmula de volumen",
            "formula de volumen", "qué es el volumen", "que es el volumen",
            "cómo calcular el volumen", "como calcular el volumen",
        )):
            return True

        # Battery / Hardware negative phrases (purchase, specs)
        if any(term in clean for term in (
            "qué batería usa", "que bateria usa", "qué batería comprar", "que bateria comprar",
            "cómo cambiar la batería", "como cambiar la bateria", "dónde comprar batería",
            "donde comprar bateria", "qué memoria ram comprar", "qué procesador tiene la luna",
        )):
            return True

        # Timer negative phrases (explanations)
        if any(term in clean for term in (
            "explicame qué es un temporizador", "explícame qué es un temporizador",
            "cómo funciona un temporizador", "como funciona un temporizador",
            "qué es un temporizador", "que es un temporizador",
            "qué es una alarma", "que es una alarma",
        )):
            return True

        # Music negative phrases (genre/history queries)
        if any(term in clean for term in (
            "qué es la música", "que es la musica", "música clásica", "musica clasica",
            "por qué la música", "por que la musica", "historia de la música", "historia de la musica",
            "qué tipo de música", "que tipo de musica", "géneros de música", "generos de musica",
        )):
            return True

        # Clock negative phrases (store hours, travel)
        return any(term in clean for term in (
            "qué hora abre", "que hora abre", "a qué hora abre", "a que hora abre",
            "qué hora cierra", "que hora cierra", "a qué hora cierra", "a que hora cierra",
            "a qué hora llega", "a que hora llega",
        ))

    def _match_clock(self, clean: str, raw_text: str) -> IntentResolution | None:
        date_exact = {
            "qué día es hoy", "que dia es hoy", "fecha de hoy",
            "cuál es la fecha", "cual es la fecha",
        }
        if clean in date_exact:
            return IntentResolution(
                intent="clock",
                tool_name="clock",
                tool_args={"format": "date"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        time_exact = {
            "qué hora es", "que hora es", "dime la hora", "decime la hora",
            "hora actual", "qué hora tenemos", "que hora tenemos",
            "la hora", "hora", "hora es", "la hora es", "ahora es",
        }
        clock_query = clean in time_exact
        if not clock_query and "hora" in clean:
            natural_markers = (
                "qué hora", "que hora", "decime la hora", "dime la hora",
                "me decis la hora", "me decís la hora", "me dices la hora",
                "podés decirme la hora", "podes decirme la hora", "puedes decirme la hora",
                "hora tenemos", "hora es",
            )
            contextual_exclusions = (
                "abre", "cierra", "llega", "llegar", "tarda", "tardar", "tardaría",
                "tardaria", "demora", "demorar", "hora es en", "hora en ",
            )
            clock_query = any(marker in clean for marker in natural_markers) and not any(
                term in clean for term in contextual_exclusions
            )

        if clock_query:
            return IntentResolution(
                intent="clock",
                tool_name="clock",
                tool_args={"format": "time"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )
        return None

    def _match_volume(self, clean: str, raw_text: str) -> IntentResolution | None:
        # Mute
        if clean in {"silencio", "mute", "mutear", "silenciá", "silencia"}:
            return IntentResolution(
                intent="volume",
                tool_name="volume",
                tool_args={"action": "mute"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        # Step up
        if clean in {"subí el volumen", "sube el volumen", "subir volumen", "aumentar volumen", "más volumen", "mas volumen"}:
            return IntentResolution(
                intent="volume",
                tool_name="volume",
                tool_args={"action": "step_up", "step": 10},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        # Step down
        if clean in {"bajá el volumen", "baja el volumen", "bajar volumen", "disminuir volumen", "menos volumen"}:
            return IntentResolution(
                intent="volume",
                tool_name="volume",
                tool_args={"action": "step_down", "step": 10},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        # ASR-tolerant phrasing. "sonido"/"audio" are safe volume aliases only
        # when an explicit direction is present; conceptual audio questions stay chat.
        if any(noun in clean for noun in ("volumen", "sonido", "audio")):
            if any(term in clean for term in (
                "más", "mas", "subí", "subi", "sube", "subir", "aumenta", "aumentar",
                "subime", "subeme", "levantá", "levanta"
            )):
                return IntentResolution(
                    intent="volume", tool_name="volume",
                    tool_args={"action": "step_up", "step": 10},
                    requires_llm=False, confidence=0.98, raw_text=raw_text,
                )
            if any(term in clean for term in (
                "menos", "bajá", "baja", "bajar", "disminuí", "disminui", "disminuir",
                "bajame", "bájame", "bajeme"
            )):
                return IntentResolution(
                    intent="volume", tool_name="volume",
                    tool_args={"action": "step_down", "step": 10},
                    requires_llm=False, confidence=0.98, raw_text=raw_text,
                )

        # Set specific level: e.g. "volumen al 70%", "poné el volumen en 50", "volumen 80"
        match_set = re.search(
            r"^(?:(?:poné|pone|pon|fijá|fija|colocá|coloca|establecé|establece)\s+)?(?:el\s+)?volumen(?:\s+(?:al|en|a))?\s+(\d{1,3})\s*%?$",
            clean,
        )
        if match_set:
            val = int(match_set.group(1))
            if 0 <= val <= 100:
                return IntentResolution(
                    intent="volume",
                    tool_name="volume",
                    tool_args={"action": "set", "level": val},
                    requires_llm=False,
                    confidence=1.0,
                    raw_text=raw_text,
                )

        # Get volume
        if clean in {"cuál es el volumen", "cual es el volumen", "volumen actual", "en cuánto está el volumen", "en cuanto esta el volumen"}:
            return IntentResolution(
                intent="volume",
                tool_name="volume",
                tool_args={"action": "get"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        return None

    def _match_reminders(self, clean: str, raw_text: str) -> IntentResolution | None:
        if clean in {
            "recordatorios", "mis recordatorios", "listar recordatorios",
            "ver recordatorios", "qué recordatorios tengo", "que recordatorios tengo",
        }:
            return IntentResolution(
                intent="reminders_list",
                tool_name="reminders",
                tool_args={"action": "list"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        if clean in {
            "cancelar recordatorio", "cancela el recordatorio", "cancelá el recordatorio",
            "borrar recordatorio", "eliminar recordatorio",
        }:
            return IntentResolution(
                intent="reminders_cancel",
                tool_name="reminders",
                tool_args={"action": "cancel"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        request = extract_reminder_request(raw_text)
        if request is not None:
            return IntentResolution(
                intent="reminders_create",
                tool_name="reminders",
                tool_args={
                    "action": "create",
                    "text": request.content,
                    "when": request.when_text,
                },
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )
        return None

    def _match_timer(self, clean: str, raw_text: str) -> IntentResolution | None:
        # List
        if clean in {"listar temporizadores", "ver temporizadores", "qué temporizadores hay", "que temporizadores hay", "temporizadores activos", "temporizadores"}:
            return IntentResolution(
                intent="timer",
                tool_name="timer",
                tool_args={"action": "list"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        # Cancel
        if clean in {"cancelar temporizador", "cancela el temporizador", "pará el temporizador", "para el temporizador", "borrar temporizador", "cancelar alarma"}:
            return IntentResolution(
                intent="timer",
                tool_name="timer",
                tool_args={"action": "cancel"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        # Create timer with duration
        # Patterns like: "temporizador de 5 minutos", "poné un temporizador de 30 segundos", "alarma de 1 hora"
        timer_create_pattern = re.search(
            r"(?:poné|pone|pon|iniciá|inicia|creá|crea|configurá|configura\s+)?(?:un\s+)?(?:temporizador|alarma)\s+(?:de\s+)?(\d+)\s*(segundos?|segs?|minutos?|mins?|horas?|hs?)",
            clean,
        )
        if timer_create_pattern:
            num = int(timer_create_pattern.group(1))
            unit = timer_create_pattern.group(2).lower()
            if unit.startswith("seg"):
                seconds = num
            elif unit.startswith("min"):
                seconds = num * 60
            elif unit.startswith("h"):
                seconds = num * 3600
            else:
                seconds = num

            return IntentResolution(
                intent="timer",
                tool_name="timer",
                tool_args={"action": "create", "seconds": seconds},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        return None

    def _match_music(self, clean: str, raw_text: str) -> IntentResolution | None:
        # Source-qualified playback commands are deterministic: Core decides the
        # provider and the music tool validates the resulting query.
        source_prefixes = (
            (("poné en youtube ", "pone en youtube ", "pon en youtube ", "reproducí en youtube ", "reproduce en youtube ", "buscá en youtube ", "busca en youtube "), "youtube"),
            (("poné de youtube ", "pone de youtube ", "reproducí de youtube ", "reproduce de youtube "), "youtube"),
            (("poné de mi música ", "pone de mi música ", "poné de mi musica ", "pone de mi musica ", "reproducí de mi música ", "reproduce de mi música ", "poné música local ", "pone música local ", "poné musica local ", "pone musica local "), "local"),
        )
        for prefixes, source in source_prefixes:
            for prefix in prefixes:
                remainder = self._strip_prefix_preserving_case(raw_text, prefix)
                if remainder:
                    return IntentResolution(
                        intent="music_play",
                        tool_name="music",
                        tool_args={"action": "play", "query": remainder, "source": source},
                        requires_llm=False,
                        confidence=1.0,
                        raw_text=raw_text,
                    )

        for prefix in (
            "poné la canción ", "pone la canción ", "poné la cancion ", "pone la cancion ",
            "reproducí la canción ", "reproduce la canción ", "reproducí la cancion ", "reproduce la cancion ",
            "poné música de ", "pone música de ", "poné musica de ", "pone musica de ",
        ):
            remainder = self._strip_prefix_preserving_case(raw_text, prefix)
            if remainder:
                return IntentResolution(
                    intent="music_play",
                    tool_name="music",
                    tool_args={"action": "play", "query": remainder, "source": "auto"},
                    requires_llm=False,
                    confidence=1.0,
                    raw_text=raw_text,
                )

        if clean in {
            "poné música", "pone música", "pon música", "reproducí música", "reproduce música",
            "reproducir música", "tocá música", "toca música", "poner música", "poner musica",
        }:
            return IntentResolution(
                intent="music_play",
                tool_name="music",
                tool_args={"action": "play"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        if clean in {"pausá la música", "pausa la música", "pausar música", "pausar musica", "pausá", "pausa"}:
            return IntentResolution(
                intent="music_pause",
                tool_name="music",
                tool_args={"action": "pause"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        if clean in {
            "reanudá la música", "reanuda la música", "reanudar música", "reanudar musica",
            "seguí la música", "sigue la música", "continuar música", "continuar musica", "reanudá", "reanuda",
        }:
            return IntentResolution(
                intent="music_resume",
                tool_name="music",
                tool_args={"action": "resume"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        if clean in {
            "siguiente canción", "siguiente tema", "pasá de tema", "pasa de tema",
            "cambiá de canción", "cambia de canción", "siguiente pista", "próxima canción", "proxima cancion",
            "siguiente", "siguiente cancion",
        }:
            return IntentResolution(
                intent="music_next",
                tool_name="music",
                tool_args={"action": "next"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        if clean in {
            "pará la música", "para la música", "detené la música", "deten la música",
            "parar música", "detener música", "stop música", "stop musica", "parar musica",
            "detener musica", "para musica", "pará musica",
        }:
            return IntentResolution(
                intent="music_stop",
                tool_name="music",
                tool_args={"action": "stop"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        if clean in {
            "estado de la música", "estado de la musica", "qué está sonando", "que esta sonando",
            "qué suena", "que suena",
        }:
            return IntentResolution(
                intent="music_status",
                tool_name="music",
                tool_args={"action": "status"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        return None

    def _match_notes(self, clean: str, raw_text: str) -> IntentResolution | None:
        # List notes
        if clean in {
            "leeme las notas", "léeme las notas", "qué notas tengo", "que notas tengo",
            "listar notas", "ver notas", "cuáles son mis notas", "cuales son mis notas", "mis notas",
            "notas tengo", "notas", "qué notas", "que notas",
            "qué anotaste", "que anotaste", "qué anotaste recién", "que anotaste recien",
            "qué fue lo que anotaste", "que fue lo que anotaste",
            "qué nota guardaste", "que nota guardaste", "qué guardaste en notas", "que guardaste en notas",
        }:
            return IntentResolution(
                intent="notes_list",
                tool_name="notes",
                tool_args={"action": "list"},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )

        # Create note: prefixes
        prefixes = (
            "anotá que ", "anota que ", "anotá: ", "anota: ", "anotá ", "anota ", "anotar ",
            "anotame que ", "anotáme que ", "anotame ", "anotáme ",
            "apuntá que ", "apunta que ", "apuntame que ", "apuntáme que ", "apuntá ", "apunta ",
            "recordá que ", "recorda que ", "recuérdame que ", "recuerdame que ",
            "guardame que ", "guardáme que ", "guardame ", "guardáme ", "guardá que ", "guarda que ",
            "tomá nota que ", "toma nota que ", "tomá nota: ", "toma nota: ", "tomá nota ", "toma nota ",
            "guardá una nota que dice ", "guarda una nota que dice ", "guardá una nota ", "guarda una nota ",
            "creá una nota que dice ", "crea una nota que dice ", "creá una nota ", "crea una nota ",
            "guardar nota ", "crear nota ", "nota: ", "nota ",
        )
        for prefix in prefixes:
            remainder = self._strip_prefix_preserving_case(raw_text, prefix)
            if remainder:
                content = remainder.strip()
                if content:
                    return IntentResolution(
                        intent="notes_create",
                        tool_name="notes",
                        tool_args={"action": "create", "text": content},
                        requires_llm=False,
                        confidence=1.0,
                        raw_text=raw_text,
                    )

        return None

    def _match_system_status(self, clean: str, raw_text: str) -> IntentResolution | None:
        status_exact = {
            "estado del sistema", "cómo está el sistema", "como está el sistema", "como esta el sistema",
            "diagnóstico del sistema", "diagnostico del sistema", "estado de la batería", "estado de la bateria",
            "cuánta batería queda", "cuanta bateria queda", "batería restante", "bateria restante",
            "memoria ram usada", "uso de cpu", "estado del hardware", "diagnóstico", "diagnostico",
        }
        status_query = clean in status_exact
        if not status_query and any(term in clean for term in ("ram", "cpu", "memoria", "batería", "bateria", "hardware")):
            status_markers = (
                "cómo está", "como esta", "cómo viene", "como viene", "estado",
                "uso", "cuánto", "cuanto", "disponible", "libre", "queda", "restante"
            )
            status_query = any(marker in clean for marker in status_markers)
        if status_query:
            return IntentResolution(
                intent="system_status",
                tool_name="system_status",
                tool_args={},
                requires_llm=False,
                confidence=1.0,
                raw_text=raw_text,
            )
        return None

    @staticmethod
    def _match_fresh_web_question(clean: str, raw_text: str) -> IntentResolution | None:
        """Route natural questions that explicitly require fresh public data to web."""
        question_markers = (
            "qué ", "que ", "cómo ", "como ", "cuál ", "cual ", "cuánto ", "cuanto ",
            "dónde ", "donde ", "quién ", "quien ", "hay ", "pasó ", "paso ",
        )
        is_question = raw_text.lstrip().startswith("¿") or raw_text.rstrip().endswith("?")
        is_question = is_question or any(clean.startswith(marker) for marker in question_markers)
        if not is_question:
            return None

        freshness_markers = (
            " hoy", "hoy ", " ahora", "ahora ", "actualmente", " actual", "actual ",
            "último", "ultimo", "última", "ultima", "reciente", "esta semana",
            "este mes", "cotización", "cotizacion", "precio de hoy", "precio actual",
            "en este momento",
        )
        if not any(marker in f" {clean} " for marker in freshness_markers):
            return None

        tool_args: dict[str, Any] = {"query": raw_text.strip()}
        news_markers = (
            "qué pasó", "que paso", "noticias", "novedades", "últimas noticias",
            "ultimas noticias", "qué ocurrió", "que ocurrio",
        )
        if any(marker in clean for marker in news_markers):
            tool_args["category"] = "news"
            if "hoy" in clean or "ahora" in clean:
                tool_args["freshness"] = "day"
            elif "esta semana" in clean:
                tool_args["freshness"] = "week"
            elif "este mes" in clean:
                tool_args["freshness"] = "month"
        return IntentResolution(
            intent="web_search",
            tool_name="web_search",
            tool_args=tool_args,
            requires_llm=True,
            confidence=1.0,
            raw_text=raw_text,
        )

    def _match_web_search(self, clean: str, raw_text: str) -> IntentResolution | None:
        # Natural imperative forms such as "buscame"/"averiguame" are a direct
        # request for external information, not conversational chat.
        collapsed = " ".join(raw_text.strip().split()).lstrip("¿?¡!.,;:")
        imperative = re.match(
            r"(?i)^(?:busc(?:a|á)me|averigu(?:a|á)me|investig(?:a|á)me)(?:\s+en\s+(?:internet|la\s+web))?\s+(.+)$",
            collapsed,
        )
        if imperative:
            query = imperative.group(1).strip()
            query_clean = " ".join(query.lower().split()).strip(" ¿?¡!.,;:")
            tool_args: dict[str, Any] = {"query": query}
            if any(marker in query_clean for marker in ("noticias", "novedades", "qué pasó", "que paso")):
                tool_args["category"] = "news"
                if "hoy" in query_clean or "ahora" in query_clean:
                    tool_args["freshness"] = "day"
                elif "esta semana" in query_clean:
                    tool_args["freshness"] = "week"
                elif "este mes" in query_clean:
                    tool_args["freshness"] = "month"
                clean_query = re.sub(
                    r"(?i)^(?:noticias|novedades)(?:\s+de|\s+sobre)?\s+",
                    "",
                    query,
                )
                clean_query = re.sub(
                    r"(?i)\s+(?:de\s+)?(?:hoy|ahora|esta\s+semana|este\s+mes)\s*$",
                    "",
                    clean_query,
                ).strip()
                if clean_query:
                    tool_args["query"] = clean_query
            return IntentResolution(
                intent="web_search",
                tool_name="web_search",
                tool_args=tool_args,
                requires_llm=True,
                confidence=1.0,
                raw_text=raw_text,
            )

        search_prefixes = (
            "buscá en internet ", "busca en internet ", "buscar en internet ",
            "buscá en la web ", "busca en la web ", "buscar en la web ",
            "buscá en google ", "busca en google ", "buscar en google ",
            "buscá información sobre ", "busca información sobre ", "buscar información sobre ",
            "buscá informacion sobre ", "busca informacion sobre ", "buscar informacion sobre ",
            "buscá noticias de ", "busca noticias de ", "buscar noticias de ",
            "buscá qué es ", "busca qué es ", "buscar qué es ",
            "buscá que es ", "busca que es ", "buscar que es ",
            "buscá quién fue ", "busca quién fue ", "buscar quién fue ",
            "buscá quien fue ", "busca quien fue ", "buscar quien fue ",
            "buscá ", "busca ", "buscar ",
        )
        # Check explicit web search triggers
        for prefix in search_prefixes:
            remainder = self._strip_prefix_preserving_case(raw_text, prefix)
            if remainder is None:
                continue
            query = remainder
            query_clean = " ".join(query.lower().split()).strip(" ¿?¡!.,;:")
            # Filter out single words or trivial phrases if it was just "busca"
            if prefix in {"buscá ", "busca ", "buscar "} and not any(
                k in query_clean for k in ("en internet", "en la web", "noticias", "precio", "clima")
            ):
                continue
            if query:
                tool_args = {"query": query}
                if "noticias" in query_clean:
                    tool_args["category"] = "news"
                return IntentResolution(
                    intent="web_search",
                    tool_name="web_search",
                    tool_args=tool_args,
                    requires_llm=True,
                    confidence=1.0,
                    raw_text=raw_text,
                )

        # Live weather/temperature questions are always external-data intents.
        # They must never fall through to the conversational model to guess.
        weather_terms = (
            "clima", "pronóstico", "pronostico", "temperatura",
            "va a llover", "lloverá", "llovera", "tiempo en ",
        )
        weather_markers = (
            "ahora", "actual", "hoy", "mañana", "manana",
            "cómo va", "como va", "cuánto hace", "cuanto hace", " en ",
        )
        if any(term in clean for term in weather_terms) and any(marker in clean for marker in weather_markers):
            return IntentResolution(
                intent="web_search",
                tool_name="web_search",
                tool_args={"query": raw_text.strip()},
                requires_llm=True,
                confidence=1.0,
                raw_text=raw_text,
            )
        return None

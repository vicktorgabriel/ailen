"""Unit tests for deterministic IntentResolver."""

from ailen.tools.intent_resolver import IntentResolver


def test_intent_resolver_clock() -> None:
    resolver = IntentResolver()
    for phrase in ["¿Qué hora es?", "qué hora es", "decime la hora", "hora actual"]:
        res = resolver.resolve(phrase)
        assert res.intent == "clock"
        assert res.tool_name == "clock"
        assert res.tool_args == {"format": "time"}
        assert res.requires_llm is False
        assert res.confidence == 1.0

    for phrase in ["qué día es hoy", "fecha de hoy", "cuál es la fecha"]:
        res = resolver.resolve(phrase)
        assert res.intent == "clock"
        assert res.tool_name == "clock"
        assert res.tool_args == {"format": "date"}
        assert res.requires_llm is False
        assert res.confidence == 1.0


def test_intent_resolver_timer() -> None:
    resolver = IntentResolver()
    res1 = resolver.resolve("Poné un temporizador de 5 minutos")
    assert res1.intent == "timer"
    assert res1.tool_name == "timer"
    assert res1.tool_args == {"action": "create", "seconds": 300}
    assert res1.requires_llm is False

    res2 = resolver.resolve("temporizador de 30 segundos")
    assert res2.tool_args == {"action": "create", "seconds": 30}

    res_list = resolver.resolve("listar temporizadores")
    assert res_list.tool_args == {"action": "list"}

    res_cancel = resolver.resolve("cancelar temporizador")
    assert res_cancel.tool_args == {"action": "cancel"}


def test_intent_resolver_volume() -> None:
    resolver = IntentResolver()
    res_up = resolver.resolve("Subí el volumen")
    assert res_up.intent == "volume"
    assert res_up.tool_name == "volume"
    assert res_up.tool_args == {"action": "step_up", "step": 10}

    res_down = resolver.resolve("Bajar volumen")
    assert res_down.tool_args == {"action": "step_down", "step": 10}

    res_set = resolver.resolve("Poné el volumen al 70%")
    assert res_set.tool_args == {"action": "set", "level": 70}

    res_mute = resolver.resolve("Silencio")
    assert res_mute.tool_args == {"action": "mute"}


def test_intent_resolver_music() -> None:
    resolver = IntentResolver()
    assert resolver.resolve("Poné música").tool_args == {"action": "play"}
    assert resolver.resolve("Pausá la música").tool_args == {"action": "pause"}
    assert resolver.resolve("Reanudá la música").tool_args == {"action": "resume"}
    assert resolver.resolve("Siguiente canción").tool_args == {"action": "next"}
    assert resolver.resolve("Pará la música").tool_args == {"action": "stop"}
    assert resolver.resolve("Qué está sonando").tool_args == {"action": "status"}


def test_intent_resolver_notes() -> None:
    resolver = IntentResolver()
    res_create = resolver.resolve("Anotá comprar leche y pan")
    assert res_create.intent == "notes_create"
    assert res_create.tool_name == "notes"
    assert res_create.tool_args == {"action": "create", "text": "comprar leche y pan"}

    res_list = resolver.resolve("Leeme las notas")
    assert res_list.intent == "notes_list"
    assert res_list.tool_args == {"action": "list"}


def test_intent_resolver_system_status() -> None:
    resolver = IntentResolver()
    for phrase in ["Estado del sistema", "¿Cómo está el sistema?", "diagnóstico del sistema", "cuánta batería queda"]:
        res = resolver.resolve(phrase)
        assert res.intent == "system_status"
        assert res.tool_name == "system_status"
        assert res.requires_llm is False


def test_intent_resolver_web_search() -> None:
    resolver = IntentResolver()
    res = resolver.resolve("Buscá en internet el clima en Buenos Aires")
    assert res.intent == "web_search"
    assert res.tool_name == "web_search"
    assert res.tool_args == {"query": "el clima en Buenos Aires"}
    assert res.requires_llm is True  # Web search requires LLM to synthesize the results

    news = resolver.resolve("Buscá en internet noticias de Python")
    assert news.tool_args == {"query": "noticias de Python", "category": "news"}


def test_intent_resolver_strict_negative_phrases() -> None:
    resolver = IntentResolver()
    negatives = [
        "¿Cuál es el volumen de un cilindro?",
        "fórmula de volumen de una esfera",
        "¿Qué es el volumen?",
        "¿Qué batería usa esta notebook?",
        "¿Dónde comprar batería para auto?",
        "Explicame qué es un temporizador",
        "¿Cómo funciona un temporizador?",
        "¿Qué es la música clásica?",
        "Historia de la música",
        "¿A qué hora abre la panadería?",
        "¿A qué hora cierra el banco?",
    ]
    for phrase in negatives:
        res = resolver.resolve(phrase)
        assert res.intent == "chat", f"Negative phrase incorrectly classified: '{phrase}' -> {res.intent}"
        assert res.tool_name is None, f"Tool assigned to negative phrase: '{phrase}' -> {res.tool_name}"
        assert res.requires_llm is True


def test_intent_resolver_empty_or_whitespace() -> None:
    resolver = IntentResolver()
    assert resolver.resolve("").intent == "chat"
    assert resolver.resolve("   ").intent == "chat"


def test_intent_resolver_ambiguous_questions_do_not_trigger_tools() -> None:
    resolver = IntentResolver()
    ambiguous = [
        "¿Cuál es el volumen de un cilindro?",
        "¿Qué batería usa esta notebook?",
        "Explicame cómo funciona un temporizador",
        "¿Qué hora tardaría en llegar?",
        "¿Cómo funciona Spotify?",
        "¿Qué significa pausar un proceso?",
    ]
    for phrase in ambiguous:
        resolution = resolver.resolve(phrase)
        assert resolution.intent == "chat", phrase
        assert resolution.tool_name is None, phrase
        assert resolution.requires_llm is True, phrase


def test_intent_resolver_explicit_web_search_overrides_negative_keyword() -> None:
    resolver = IntentResolver()
    resolution = resolver.resolve("buscá en internet el volumen de un cilindro")
    assert resolution.intent == "web_search"
    assert resolution.tool_name == "web_search"
    assert resolution.tool_args["query"] == "el volumen de un cilindro"


def test_intent_resolver_notes_create_preserves_original_casing() -> None:
    resolver = IntentResolver()
    resolution = resolver.resolve("Anotá que Reunión con Pedro a las 15:00 en Devoto")
    assert resolution.intent == "notes_create"
    assert resolution.tool_args["text"] == "Reunión con Pedro a las 15:00 en Devoto"


def test_intent_resolver_web_query_slices_raw_text_correctly() -> None:
    resolver = IntentResolver()
    resolution = resolver.resolve("Buscá en internet Clima Buenos Aires")
    assert resolution.intent == "web_search"
    assert resolution.tool_args["query"] == "Clima Buenos Aires"


def test_intent_resolver_notes_create_with_leading_question_mark() -> None:
    resolver = IntentResolver()
    resolution = resolver.resolve("¿anotá que comprar pilas AA?")
    assert resolution.intent == "notes_create"
    assert resolution.tool_args["text"] == "comprar pilas AA?"


def test_intent_resolver_timer_create_variants() -> None:
    resolver = IntentResolver()
    assert resolver.resolve("temporizador de 5 minutos").tool_args["seconds"] == 300
    assert resolver.resolve("poné una alarma de 30 segundos").tool_args["seconds"] == 30
    assert resolver.resolve("alarma de 1 hora").tool_args["seconds"] == 3600


def test_intent_resolver_volume_set_level() -> None:
    resolver = IntentResolver()
    resolution = resolver.resolve("volumen al 70%")
    assert resolution.tool_name == "volume"
    assert resolution.tool_args == {"action": "set", "level": 70}


def test_intent_resolver_asr_tolerant_phrases() -> None:
    resolver = IntentResolver()
    assert resolver.resolve("hora es").tool_name == "clock"
    assert resolver.resolve("notas tengo").tool_args == {"action": "list"}
    note = resolver.resolve("nota comprar estaño mañana")
    assert note.tool_name == "notes"
    assert note.tool_args == {"action": "create", "text": "comprar estaño mañana"}
    vol = resolver.resolve("ajá un poquito más el volumen")
    assert vol.tool_name == "volume"
    assert vol.tool_args == {"action": "step_up", "step": 10}

def test_intent_resolver_natural_clock_variants() -> None:
    resolver = IntentResolver()
    positives = [
        "me podés decir qué hora es",
        "decime qué hora es por favor",
        "qué hora tenemos ahora",
        "me decis la hora",
    ]
    for phrase in positives:
        result = resolver.resolve(phrase)
        assert result.tool_name == "clock", phrase
        assert result.tool_args == {"format": "time"}

    for phrase in ["qué hora tardaría en llegar", "a qué hora abre la farmacia", "qué hora es en Tokio"]:
        result = resolver.resolve(phrase)
        assert result.tool_name is None, phrase


def test_intent_resolver_natural_note_variants() -> None:
    resolver = IntentResolver()
    expected = {
        "recordá que tengo que comprar leche": "tengo que comprar leche",
        "guardame que tengo que comprar pan": "tengo que comprar pan",
        "anotame la compra": "la compra",
        "apuntá comprar estaño mañana": "comprar estaño mañana",
    }
    for phrase, text in expected.items():
        result = resolver.resolve(phrase)
        assert result.tool_name == "notes", phrase
        assert result.tool_args == {"action": "create", "text": text}

    for phrase in ["qué anotaste recién", "qué fue lo que anotaste", "qué nota guardaste"]:
        result = resolver.resolve(phrase)
        assert result.tool_name == "notes", phrase
        assert result.tool_args["action"] == "list"


def test_intent_resolver_natural_sound_and_status_variants() -> None:
    resolver = IntentResolver()
    down = resolver.resolve("me podés bajar un poco el sonido")
    assert down.tool_name == "volume"
    assert down.tool_args == {"action": "step_down", "step": 10}
    up = resolver.resolve("subime un poco el audio")
    assert up.tool_name == "volume"
    assert up.tool_args == {"action": "step_up", "step": 10}
    ram = resolver.resolve("cómo viene la ram")
    assert ram.tool_name == "system_status"
    assert ram.requires_llm is False
    cpu = resolver.resolve("cuánto uso de cpu tengo")
    assert cpu.tool_name == "system_status"
    # Conceptual audio wording must not become a volume command.
    assert resolver.resolve("explicame cómo funciona el audio digital").tool_name is None

def test_intent_resolver_persistent_reminders_require_explicit_time() -> None:
    resolver = IntentResolver()

    relative = resolver.resolve("Recordame apagar el horno en 20 minutos")
    assert relative.intent == "reminders_create"
    assert relative.tool_name == "reminders"
    assert relative.tool_args == {
        "action": "create",
        "text": "apagar el horno",
        "when": "en 20 minutos",
    }
    assert relative.requires_llm is False

    absolute = resolver.resolve("Recordáme comprar estaño mañana a las 10:30")
    assert absolute.tool_name == "reminders"
    assert absolute.tool_args["text"] == "comprar estaño"
    assert absolute.tool_args["when"] == "mañana a las 10:30"

    # No explicit due time: preserve the established atemporal note behavior.
    note = resolver.resolve("recordá que tengo que comprar leche")
    assert note.tool_name == "notes"
    assert note.tool_args == {"action": "create", "text": "tengo que comprar leche"}

    assert resolver.resolve("mis recordatorios").tool_args == {"action": "list"}
    assert resolver.resolve("cancelar recordatorio").tool_args == {"action": "cancel"}

def test_weather_queries_route_to_web_search() -> None:
    resolver = IntentResolver()
    for text in (
        "Cuál es la temperatura actual en Las Lajas",
        "Cómo va a estar el clima hoy en Las Lajas",
        "Va a llover mañana en Neuquén",
    ):
        result = resolver.resolve(text)
        assert result.tool_name == "web_search"
        assert result.intent == "web_search"
        assert result.tool_args["query"] == text


def test_natural_fresh_questions_route_to_web_without_explicit_search_command() -> None:
    resolver = IntentResolver()
    cases = (
        "¿Cómo está el dólar hoy?",
        "¿Qué pasó hoy con OpenAI?",
        "¿Cuál es el precio actual de Bitcoin?",
        "¿Hay novedades esta semana de Python?",
    )
    for text in cases:
        result = resolver.resolve(text)
        assert result.intent == "web_search", text
        assert result.tool_name == "web_search", text
        assert result.confidence == 1.0


def test_freshness_words_in_casual_chat_do_not_trigger_web() -> None:
    resolver = IntentResolver()
    for text in (
        "Hoy estoy cansado",
        "Ahora me voy al taller",
        "Esta semana fue larga",
        "Lo último que hice salió bien",
    ):
        result = resolver.resolve(text)
        assert result.intent == "chat", text
        assert result.tool_name is None, text


def test_local_clock_still_precedes_fresh_web_fallback() -> None:
    resolver = IntentResolver()
    result = resolver.resolve("¿Qué día es hoy?")
    assert result.intent == "clock"
    assert result.tool_name == "clock"

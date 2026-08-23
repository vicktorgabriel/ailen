"""Unit tests for deterministic IntentResolver."""

from ailen.tools.intent_resolver import IntentResolver


def test_intent_resolver_clock() -> None:
    resolver = IntentResolver()
    for phrase in ["¿Qué hora es?", "qué hora es", "decime la hora", "hora actual", "qué día es hoy"]:
        res = resolver.resolve(phrase)
        assert res.intent == "clock"
        assert res.tool_name == "clock"
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

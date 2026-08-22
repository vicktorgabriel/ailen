"""Unit tests for deterministic fast-path intent classifier and rule-based routing."""

from ailen.ai.router import (
    ROUTE_RULE_ONLY,
    RouteRequest,
    RuleBasedRouter,
    classify_fast_path_intent,
)


def test_classify_fast_path_intent() -> None:
    assert classify_fast_path_intent("¿Qué hora es?") == "clock"
    assert classify_fast_path_intent("Poné un temporizador de 10 minutos") == "timer"
    assert classify_fast_path_intent("Subir volumen") == "volume"
    assert classify_fast_path_intent("Pausar música") == "playback"
    assert classify_fast_path_intent("Estado del sistema") == "system_status"
    assert classify_fast_path_intent("Anotar comprar pan") == "notes"
    assert classify_fast_path_intent("Explicame la teoría de la relatividad") is None


def test_router_handles_fast_path_intents() -> None:
    router = RuleBasedRouter()
    for intent in ["clock", "timer", "volume", "playback", "system_status", "notes"]:
        req = RouteRequest(intent=intent)
        plan = router.route(req)
        assert plan.primary_backend == ROUTE_RULE_ONLY
        assert plan.reason_code == "RULE_ONLY_INTENT"


def test_fast_path_avoids_ambiguous_technical_phrases() -> None:
    assert classify_fast_path_intent("¿Cuál es el volumen de un cilindro?") is None
    assert classify_fast_path_intent("¿Qué batería usa este equipo?") is None
    assert classify_fast_path_intent("Explicame cómo funciona una alarma") is None
    assert classify_fast_path_intent("¿Qué significa pausa musical?") is None

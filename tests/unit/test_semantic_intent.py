"""Tests for bounded local semantic tool-intent fallback."""

from pathlib import Path
from unittest.mock import MagicMock

from ailen.ai.fake import FakeAiBackend
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.tools.builtin import ClockTool, NotesTool, TimerTool, VolumeTool, WebSearchTool
from ailen.tools.builtin.web_search import FakeWebSearchProvider
from ailen.tools.registry import ToolRegistry
from ailen.tools.semantic_intent import SemanticToolIntentResolver


def _repo(tmp_path: Path) -> MemoryRepository:
    mgr = SQLiteManager(str(tmp_path / "semantic.db"))
    MigrationRunner(mgr).run_migrations()
    return MemoryRepository(mgr)


def test_semantic_resolver_accepts_valid_local_allowlisted_tool(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    backend = FakeAiBackend(canned_response=(
        '{"kind":"tool","tool":"notes","arguments":{"action":"search","query":"comprar mañana"},"confidence":0.9}'
    ))
    generate_spy = MagicMock(wraps=backend.generate)
    backend.generate = generate_spy
    registry = ToolRegistry([ClockTool(), NotesTool(repository=repo), VolumeTool()])
    resolver = SemanticToolIntentResolver(backend, registry, repo)

    result = resolver.resolve(
        "cosa tengo que comprar mañana",
        session_id=None,
        mode=SocialMode.WORKSHOP,
        privacy_level=PrivacyLevel.PRIVATE,
    )

    assert result is not None
    assert result.tool_name == "notes"
    assert result.tool_args["action"] == "search"
    assert result.tool_args["query"] == "comprar mañana"
    assert result.source == "semantic_tool"
    assert result.latency_ms >= 0.0
    request = generate_spy.call_args.args[0]
    assert "Nunca inventes texto faltante para crear una nota" in request.messages[0].content


def test_semantic_resolver_rejects_network_tool_even_if_model_proposes_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    backend = FakeAiBackend(canned_response=(
        '{"kind":"tool","tool":"web_search","arguments":{"query":"algo"},"confidence":0.99}'
    ))
    registry = ToolRegistry([WebSearchTool(), ClockTool()])
    resolver = SemanticToolIntentResolver(backend, registry, repo)

    result = resolver.resolve(
        "busca algo",
        session_id=None,
        mode=SocialMode.WORKSHOP,
        privacy_level=PrivacyLevel.PRIVATE,
    )
    assert result is None


def test_semantic_resolver_rejects_low_confidence_and_bad_args(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    registry = ToolRegistry([VolumeTool()])

    low = SemanticToolIntentResolver(
        FakeAiBackend(canned_response=(
            '{"kind":"tool","tool":"volume","arguments":{"action":"step_up","step":10},"confidence":0.4}'
        )),
        registry,
        repo,
    )
    assert low.resolve(
        "mas volumen", session_id=None, mode=SocialMode.WORKSHOP, privacy_level=PrivacyLevel.PRIVATE
    ) is None

    bad = SemanticToolIntentResolver(
        FakeAiBackend(canned_response=(
            '{"kind":"tool","tool":"volume","arguments":{"action":"set","level":999},"confidence":0.99}'
        )),
        registry,
        repo,
    )
    assert bad.resolve(
        "volumen fuerte", session_id=None, mode=SocialMode.WORKSHOP, privacy_level=PrivacyLevel.PRIVATE
    ) is None

def test_semantic_resolver_ignores_ordinary_chat_without_calling_backend(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    backend = FakeAiBackend(canned_response=(
        '{"kind":"tool","tool":"clock","arguments":{"format":"time"},"confidence":1.0}'
    ))
    registry = ToolRegistry([ClockTool()])
    resolver = SemanticToolIntentResolver(backend, registry, repo)
    assert resolver.resolve(
        "hola como estas", session_id=None, mode=SocialMode.WORKSHOP, privacy_level=PrivacyLevel.PRIVATE
    ) is None


def test_semantic_resolver_attempts_natural_sound_and_countdown_phrases(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    registry = ToolRegistry([VolumeTool(), TimerTool(), ClockTool()])
    resolver = SemanticToolIntentResolver(FakeAiBackend(), registry, repo)
    assert resolver.should_attempt("me podés bajar un poco el sonido")
    assert resolver.should_attempt("bajame el audio")
    assert resolver.should_attempt("poné una cuenta regresiva de cinco minutos")


def test_semantic_resolver_does_not_route_on_generic_temporal_words(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    registry = ToolRegistry([
        WebSearchTool(provider=FakeWebSearchProvider()),
        ClockTool(),
    ])
    resolver = SemanticToolIntentResolver(
        FakeAiBackend(),
        registry,
        repo,
        allow_network_tools=True,
    )

    assert resolver.should_attempt("che, hoy está bastante fresco") is False
    assert resolver.should_attempt("hoy tuve un día bastante largo") is False
    assert resolver.should_attempt("a esta hora suelo estar cansado") is False
    assert resolver.should_attempt("cambiaron la fecha de entrega") is False
    assert resolver.should_attempt("eso último me dejó pensando") is False
    assert resolver.should_attempt("ahora entiendo cómo funciona") is False
    assert resolver.should_attempt("me decís qué hora es") is True
    assert resolver.should_attempt("cuál es la fecha") is True
    assert resolver.should_attempt("qué novedades hubo hoy sobre Python") is True


def test_semantic_history_hints_do_not_match_inside_unrelated_words(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    session = repo.create_session(mode=SocialMode.WORKSHOP)
    repo.add_message(
        session_id=session.session_id,
        role="assistant",
        content="Puedo ayudarte con tareas prácticas en tu entorno inmediato.",
        mode=SocialMode.WORKSHOP,
    )
    resolver = SemanticToolIntentResolver(
        FakeAiBackend(canned_response=(
            '{"kind":"tool","tool":"notes","arguments":{"action":"list"},"confidence":0.99}'
        )),
        ToolRegistry([ClockTool(), NotesTool(repository=repo)]),
        repo,
    )

    assert resolver.should_attempt("qué podés hacer", session.session_id) is False
    assert resolver.resolve(
        "qué podés hacer",
        session_id=session.session_id,
        mode=SocialMode.WORKSHOP,
        privacy_level=PrivacyLevel.PRIVATE,
    ) is None


def test_semantic_history_never_opens_gate_for_unrelated_short_reply(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    session = repo.create_session(mode=SocialMode.WORKSHOP)
    repo.add_message(
        session_id=session.session_id,
        role="assistant",
        content="La hora actual es la una y diez.",
        mode=SocialMode.WORKSHOP,
    )
    backend = FakeAiBackend(canned_response=(
        '{"kind":"tool","tool":"clock","arguments":{},"confidence":0.99}'
    ))
    generate_spy = MagicMock(wraps=backend.generate)
    backend.generate = generate_spy
    resolver = SemanticToolIntentResolver(
        backend,
        ToolRegistry([ClockTool()]),
        repo,
    )

    assert resolver.should_attempt("muy bien", session.session_id) is False
    assert resolver.resolve(
        "muy bien",
        session_id=session.session_id,
        mode=SocialMode.WORKSHOP,
        privacy_level=PrivacyLevel.PRIVATE,
    ) is None
    generate_spy.assert_not_called()

def test_semantic_resolver_allows_available_network_tool_when_policy_enables_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    backend = FakeAiBackend(canned_response=(
        '{"kind":"tool","tool":"web_search","arguments":{"query":"noticias de AILEN"},"confidence":0.99}'
    ))
    generate_spy = MagicMock(wraps=backend.generate)
    backend.generate = generate_spy
    registry = ToolRegistry([
        WebSearchTool(provider=FakeWebSearchProvider()),
        ClockTool(),
    ])
    resolver = SemanticToolIntentResolver(
        backend,
        registry,
        repo,
        allow_network_tools=True,
    )

    result = resolver.resolve(
        "averigua en internet noticias de AILEN",
        session_id=None,
        mode=SocialMode.WORKSHOP,
        privacy_level=PrivacyLevel.PRIVATE,
    )

    assert result is not None
    assert result.tool_name == "web_search"
    assert result.source == "semantic_tool"
    request = generate_spy.call_args.args[0]
    assert "Nunca inventes texto faltante para crear una nota" not in request.messages[0].content
    assert "category=news" in request.messages[0].content

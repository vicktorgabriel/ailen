"""Tests for bounded local semantic tool-intent fallback."""

from pathlib import Path

from ailen.ai.fake import FakeAiBackend
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.tools.builtin import ClockTool, NotesTool, VolumeTool, WebSearchTool
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
    assert result.source == "semantic_local"
    assert result.latency_ms >= 0.0


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

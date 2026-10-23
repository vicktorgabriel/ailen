"""Human approvals are short lived, argument bound and consumed exactly once."""

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from typing import Any, ClassVar

import pytest

from ailen.core.confirmation import ConfirmationService, ConfirmationState
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult
from ailen.tools.executor import ToolExecutor
from ailen.tools.registry import ToolRegistry


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_request_is_opaque_immutable_and_contains_no_argument_values() -> None:
    service = ConfirmationService()
    first = service.request("send_form", {"token": "private-test-value"})
    second = service.request("send_form", {"token": "private-test-value"})
    assert first.id != second.id
    assert len(first.id) >= 32
    assert first.state is ConfirmationState.PENDING
    assert first.arguments_hash == second.arguments_hash
    assert "private-test-value" not in repr(first)
    assert "token" not in first.summary
    assert 0 < len(first.summary) <= 200
    assert (first.expires_at - first.created_at).total_seconds() == 60
    with pytest.raises(FrozenInstanceError):
        first.summary = "altered"  # type: ignore[misc]


@pytest.mark.parametrize("approved", [False, True])
def test_expiration_including_previously_approved_request(approved: bool) -> None:
    clock = Clock()
    service = ConfirmationService(ttl_seconds=2, clock=clock)
    request = service.request("send_form", {"value": 1})
    if approved:
        assert service.resolve(request.id, True, source="panel")
    clock.now = 2
    status = service.status(request.id)
    assert status is not None and status.state is ConfirmationState.EXPIRED
    assert not service.resolve(request.id, True, source="panel")
    assert not service.consume(request.id, "send_form", {"value": 1})


@pytest.mark.parametrize(
    ("confidence", "truncated"),
    [(None, False), (0.71, False), (0.99, True), (math.nan, False),
     (math.inf, False), (-1.0, False), (1.01, False), (True, False)],
)
def test_doubtful_voice_cannot_approve(
    confidence: float | None, truncated: bool,
) -> None:
    service = ConfirmationService()
    request = service.request("send_form", {})
    assert not service.resolve(
        request.id, True, source="voice", stt_confidence=confidence,
        truncated=truncated,
    )
    assert not service.consume(request.id, "send_form", {})


def test_voice_threshold_is_configurable_and_inclusive() -> None:
    service = ConfirmationService(voice_min_confidence=0.8)
    request = service.request("send_form", {})
    assert not service.resolve(request.id, True, "voice", 0.79, False)
    assert service.resolve(request.id, True, "voice", 0.8, False)
    assert service.consume(request.id, "send_form", {})


def test_panel_approval_is_bound_to_tool_and_canonical_arguments() -> None:
    service = ConfirmationService()
    args = {"b": [1, 2], "a": "test"}
    request = service.request("send_form", args)
    assert not service.resolve(
        request.id, True, "panel", arguments={"b": [1, 3], "a": "test"},
    )
    assert service.resolve(request.id, True, "panel", arguments=args)
    assert not service.consume(request.id, "other_tool", args)
    assert not service.consume(request.id, "send_form", {"a": "changed"})
    assert service.consume(request.id, "send_form", {"a": "test", "b": [1, 2]})
    assert not service.consume(request.id, "send_form", args)
    assert service.status(request.id) is None


def test_denied_request_cannot_be_approved_later() -> None:
    service = ConfirmationService()
    request = service.request("send_form", {})
    assert service.resolve(request.id, False, "panel")
    assert not service.resolve(request.id, True, "panel")
    status = service.status(request.id)
    assert status is not None and status.state is ConfirmationState.DENIED
    assert not service.consume(request.id, "send_form", {})


def test_pending_limit_and_expiration_reclaim_capacity() -> None:
    clock = Clock()
    service = ConfirmationService(max_pending=1, ttl_seconds=1, clock=clock)
    service.request("send_form", {})
    with pytest.raises(RuntimeError, match="limit"):
        service.request("send_form", {})
    clock.now = 1
    assert service.request("send_form", {}).state is ConfirmationState.PENDING


def test_approved_requests_cannot_grow_total_storage_without_bound() -> None:
    service = ConfirmationService(max_pending=1)
    for _ in range(2):
        request = service.request("send_form", {})
        assert service.resolve(request.id, True, "panel")
    with pytest.raises(RuntimeError, match="limit"):
        service.request("send_form", {})


@pytest.mark.parametrize("args", [{"value": math.nan}, {"nested": {1: "a"}}, {"value": (1,)}])
def test_argument_hash_rejects_non_json_or_ambiguous_values(args: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="finite JSON"):
        ConfirmationService().request("send_form", args)


def test_unknown_id_or_source_does_not_resolve() -> None:
    service = ConfirmationService()
    request = service.request("send_form", {})
    assert not service.resolve("missing", True, "panel")
    assert not service.consume("missing", "send_form", {})
    assert not service.resolve(request.id, True, "llm")  # type: ignore[arg-type]
    assert not service.consume(request.id, "send_form", {})


def test_consumption_is_atomic_under_concurrent_replay() -> None:
    service = ConfirmationService()
    request = service.request("send_form", {})
    assert service.resolve(request.id, True, "panel")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(
            lambda _: service.consume(request.id, "send_form", {}), range(32),
        ))
    assert sum(results) == 1


class ConfirmedTool:
    name = "send_form"
    description = "Test external action"
    schema: ClassVar[dict[str, Any]] = {
        "properties": {"value": {"type": "int", "default": 1}},
    }
    permissions: ClassVar[list[str]] = []
    allowed_modes: ClassVar[set[SocialMode]] = {SocialMode.HOME}
    privacy_level = PrivacyLevel.PUBLIC
    requires_network = False
    destructive = False
    timeout_seconds = 1.0

    def __init__(self) -> None:
        self.calls = 0

    def requires_confirmation(self, arguments: dict[str, Any]) -> bool:
        return arguments["value"] > 0

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, tool_name=self.name)


def test_executor_fails_closed_without_service_even_with_forged_id() -> None:
    tool = ConfirmedTool()
    result = ToolExecutor(ToolRegistry([tool])).execute(
        tool.name, context=ToolContext(mode=SocialMode.HOME, confirmation_id="forged"),
    )
    assert result.status_code == "CONFIRMATION_REQUIRED"
    assert not result.success and tool.calls == 0


def test_executor_requests_then_consumes_exact_approval_once() -> None:
    service = ConfirmationService()
    tool = ConfirmedTool()
    executor = ToolExecutor(ToolRegistry([tool]), confirmation_service=service)
    context = ToolContext(mode=SocialMode.HOME)
    first = executor.execute(tool.name, context=context)
    assert first.status_code == "CONFIRMATION_REQUIRED" and tool.calls == 0
    confirmation_id = first.data["confirmation_id"]
    assert service.resolve(confirmation_id, True, "panel")
    context.confirmation_id = confirmation_id
    assert executor.execute(tool.name, {"value": 1}, context).success
    assert executor.execute(tool.name, {"value": 1}, context).status_code == "CONFIRMATION_REQUIRED"
    assert tool.calls == 1


def test_executor_changed_arguments_do_not_reuse_approval() -> None:
    service = ConfirmationService()
    tool = ConfirmedTool()
    executor = ToolExecutor(ToolRegistry([tool]), confirmation_service=service)
    request = service.request(tool.name, {"value": 1})
    assert service.resolve(request.id, True, "panel")
    result = executor.execute(
        tool.name, {"value": 2}, ToolContext(mode=SocialMode.HOME, confirmation_id=request.id),
    )
    assert result.status_code == "CONFIRMATION_REQUIRED" and tool.calls == 0


def test_nonconfirming_arguments_execute_without_service() -> None:
    tool = ConfirmedTool()
    result = ToolExecutor(ToolRegistry([tool])).execute(
        tool.name, {"value": 0}, ToolContext(mode=SocialMode.HOME),
    )
    assert result.success and tool.calls == 1


def test_executor_confirmation_capacity_fails_closed() -> None:
    service = ConfirmationService(max_pending=1)
    service.request("send_form", {})
    tool = ConfirmedTool()
    result = ToolExecutor(ToolRegistry([tool]), confirmation_service=service).execute(
        tool.name, {}, ToolContext(mode=SocialMode.HOME),
    )
    assert result.status_code == "CONFIRMATION_REQUIRED" and tool.calls == 0


def test_executor_invalid_schema_does_not_consume_approved_request() -> None:
    service = ConfirmationService()
    tool = ConfirmedTool()
    request = service.request(tool.name, {"value": 1})
    assert service.resolve(request.id, True, "panel")
    result = ToolExecutor(ToolRegistry([tool]), confirmation_service=service).execute(
        tool.name, {"value": "invalid"},
        ToolContext(mode=SocialMode.HOME, confirmation_id=request.id),
    )
    assert result.status_code == "INVALID_ARGS" and tool.calls == 0
    assert service.consume(request.id, tool.name, {"value": 1})


def test_executor_policy_cannot_mutate_execution_arguments() -> None:
    class MutatingPolicyTool(ConfirmedTool):
        def requires_confirmation(self, arguments: dict[str, Any]) -> bool:
            arguments["value"] = 99
            return True

        def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
            assert arguments == {"value": 1}
            return super().execute(arguments, context)

    service = ConfirmationService()
    tool = MutatingPolicyTool()
    request = service.request(tool.name, {"value": 1})
    assert service.resolve(request.id, True, "panel")
    result = ToolExecutor(ToolRegistry([tool]), confirmation_service=service).execute(
        tool.name, {"value": 1}, ToolContext(mode=SocialMode.HOME, confirmation_id=request.id),
    )
    assert result.success and tool.calls == 1


@pytest.mark.parametrize("invalid", [{"nested": {1: "a"}}, {"value": "a" * 65537}])
def test_invalid_arguments_fail_closed_without_consuming_request(invalid: dict[str, Any]) -> None:
    service = ConfirmationService()
    request = service.request("send_form", {})
    assert not service.resolve(request.id, True, "panel", arguments=invalid)
    assert service.resolve(request.id, True, "panel")
    assert not service.consume(request.id, "send_form", invalid)
    assert service.consume(request.id, "send_form", {})


def test_safe_action_summary_is_sanitized_and_bounded() -> None:
    service = ConfirmationService()
    request = service.request("files", {"content": "sensitive-marker"}, summary=(
        "\x1bSobrescribir\nnotes.txt\u202e sensitive-marker " + "a" * 250
    ))
    assert request.summary.startswith("Sobrescribir notes.txt")
    assert len(request.summary) <= 200
    assert "\x1b" not in request.summary and "\u202e" not in request.summary
    assert "sensitive-marker" not in request.summary


def test_executor_uses_tool_action_summary() -> None:
    class SummarizedTool(ConfirmedTool):
        def confirmation_summary(self, arguments: dict[str, Any]) -> str:
            return "Enviar formulario de prueba."

    tool = SummarizedTool()
    service = ConfirmationService()
    result = ToolExecutor(ToolRegistry([tool]), confirmation_service=service).execute(
        tool.name, {}, ToolContext(mode=SocialMode.HOME),
    )
    request = service.status(result.data["confirmation_id"])
    assert request is not None and request.summary == "Enviar formulario de prueba."
    assert result.message == request.summary


def test_audit_redacts_nested_content_and_long_strings() -> None:
    executor = ToolExecutor(ToolRegistry())
    redacted = executor._redact_args({
        "content": "short-sensitive", "nested": {"content": "nested-sensitive"},
        "values": ["a" * 201, "safe"],
        "long": {"content": "b" * 202},
    })
    assert "short-sensitive" not in str(redacted)
    assert "nested-sensitive" not in str(redacted)
    assert redacted["values"] == ["[redacted len=201]", "safe"]
    assert redacted["long"]["content"] == "[redacted len=202]"

#!/usr/bin/env python3
"""Privacy-bounded validation for configured remote AI providers.

The command is dry-run by default. ``--execute`` is required before it builds
an adapter that may contact a provider. Reports contain identifiers, health,
timings and lengths only: never prompts, responses, credentials or memory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ailen.ai.contracts import (
    AiErrorKind,
    AiRequest,
    AiResponse,
    BackendCapabilities,
    BackendHealth,
    ChatMessage,
)
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.privacy import OutboundPrivacyPolicy
from ailen.ai.remote_backend import build_remote_backend
from ailen.ai.router import RoutePlan
from ailen.ai.secrets import SecretResolver
from ailen.core.config import AILENConfig, load_config
from ailen.domain.enums import PrivacyLevel, ServiceStatus

PRIVATE_MARKER = "VALIDATION_PRIVATE_MARKER_DO_NOT_SEND_7f31"
FACE_MARKER_RE = re.compile(r"\[\[face:([a-z][a-z0-9_]{0,63})\]\]")


@dataclass(frozen=True)
class PromptCase:
    case_id: str
    category: str
    text: str
    expect_face_marker: bool = False


@dataclass
class ProbeRecord:
    case_id: str
    category: str
    provider_requested: str
    provider_effective: str
    model_requested: str
    model_effective: str
    health: str
    provider_setup_ms: float | None
    provider_ready_ms: float | None
    first_text_ms: float | None
    total_ms: float
    request_chars: int | None
    provider_tool_count: int | None
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str
    error_kind: str | None
    retry_after_seconds: float | None
    response_chars: int
    streaming_observed: bool
    sanitization_passed: bool
    face_marker_valid: bool | None


def synthetic_cases() -> list[PromptCase]:
    """Return public synthetic prompts with no installation or user data."""

    return [
        PromptCase("casual_greeting", "casual", "Hola, ¿cómo va? Respondé breve y natural."),
        PromptCase(
            "rioplatense_chat",
            "rioplatense",
            "Está bastante fresco hoy. Reaccioná naturalmente, sin buscar datos.",
        ),
        PromptCase(
            "bounded_followup",
            "followup",
            "Contexto sintético público: elegimos té. Sugerí un acompañamiento simple.",
        ),
        PromptCase(
            "empathy",
            "empathy",
            "Fue un día complicado. Respondé con empatía breve y sin listas.",
        ),
        PromptCase(
            "light_humor",
            "humor",
            "Se me enfrió el mate otra vez. Respondé con humor leve.",
        ),
        PromptCase(
            "technical_short",
            "technical",
            "Explicá en dos frases la diferencia entre latencia y throughput.",
        ),
        PromptCase(
            "brief_request",
            "brief",
            "Contestá en una frase por qué conviene medir antes de optimizar.",
        ),
        PromptCase(
            "bounded_face_marker",
            "expression",
            "Respondé con entusiasmo moderado y un marcador facial permitido si corresponde.",
            expect_face_marker=True,
        ),
    ]


def _safe_request(
    case: PromptCase,
    timeout_seconds: float,
    max_tokens: int,
) -> tuple[AiRequest, bool]:
    raw = AiRequest(
        request_id=f"remote-validation-{case.case_id}-{secrets.token_hex(3)}",
        system_context=f"private persona {PRIVATE_MARKER}",
        messages=[
            ChatMessage(role="assistant", content=f"private history {PRIVATE_MARKER}"),
            ChatMessage(role="user", content=case.text),
        ],
        retrieved_memory=[f"private memory {PRIVATE_MARKER}"],
        allowed_tools=["private_tool"],
        max_output_tokens=max_tokens,
        temperature=0.55,
        timeout_seconds=timeout_seconds,
        privacy_level=PrivacyLevel.PRIVATE,
        metadata={
            "input_modality": "voice",
            "persona_description": PRIVATE_MARKER,
            "runtime_context": {"path": f"/home/{PRIVATE_MARKER}"},
            "conversational_expressions": ["happy", "curious", "excited"],
        },
    )
    safe = OutboundPrivacyPolicy.sanitize_request_for_destination(
        raw,
        destination="remote:validation",
        allow_sanitized_private=True,
    )
    serialized = " ".join(
        [safe.system_context]
        + [message.content for message in safe.messages]
        + safe.retrieved_memory
        + [str(safe.metadata)]
    )
    passed = (
        PRIVATE_MARKER not in serialized
        and len(safe.messages) == 1
        and safe.messages[0].content == case.text
        and not safe.retrieved_memory
        and not safe.allowed_tools
    )
    return safe, passed


def _quality_flags(text: str, case: PromptCase) -> bool | None:
    if not case.expect_face_marker:
        return None
    matches = FACE_MARKER_RE.findall(text)
    return len(matches) <= 1 and all(
        item in {"happy", "curious", "excited"} for item in matches
    )


def _probe_provider(
    provider_id: str,
    provider: Any,
    cases: list[PromptCase],
    timeout_seconds: float,
    max_tokens: int,
) -> tuple[dict[str, Any], list[ProbeRecord]]:
    """Probe an already-constructed provider; caller owns network consent."""

    health_started = time.monotonic()
    health = provider.health()
    health_ms = (time.monotonic() - health_started) * 1000.0
    capabilities = provider.capabilities()
    summary: dict[str, Any] = {
        "provider": provider_id,
        "model_requested": provider.model,
        "health": health.status.value,
        "health_latency_ms": round(health_ms, 1),
        "supports_streaming_declared": capabilities.supports_streaming,
    }
    if health.status not in {
        ServiceStatus.HEALTHY,
        ServiceStatus.DEGRADED,
        ServiceStatus.UNKNOWN,
    }:
        return summary, []

    records: list[ProbeRecord] = []
    for case in cases:
        request, sanitization_passed = _safe_request(case, timeout_seconds, max_tokens)
        deltas = 0

        def accept_delta(_delta: str) -> bool:
            nonlocal deltas
            deltas += 1
            return True

        if capabilities.supports_streaming and hasattr(provider, "generate_stream"):
            response: AiResponse = provider.generate_stream(request, accept_delta)
        else:
            response = provider.generate(request)
        records.append(
            ProbeRecord(
                case_id=case.case_id,
                category=case.category,
                provider_requested=provider_id,
                provider_effective=response.provider,
                model_requested=provider.model,
                model_effective=response.model,
                health=health.status.value,
                provider_setup_ms=response.provider_setup_ms,
                provider_ready_ms=response.provider_ready_ms,
                first_text_ms=(
                    round(response.first_text_ms, 1)
                    if response.first_text_ms is not None
                    else None
                ),
                total_ms=round(response.latency_ms, 1),
                request_chars=response.request_chars,
                provider_tool_count=response.provider_tool_count,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                finish_reason=response.finish_reason,
                error_kind=response.error_kind.value if response.error_kind else None,
                retry_after_seconds=response.retry_after_seconds,
                response_chars=len(response.text),
                streaming_observed=bool(deltas and response.first_text_ms is not None),
                sanitization_passed=sanitization_passed,
                face_marker_valid=_quality_flags(response.text, case),
            )
        )
        print(
            f"[{provider_id}] case={case.case_id} model={response.model} "
            f"first_text={response.first_text_ms if response.first_text_ms is not None else 'unsupported'}ms "
            f"total={response.latency_ms:.1f}ms error="
            f"{response.error_kind.value if response.error_kind else 'none'} "
            f"chars={len(response.text)}",
            flush=True,
        )
        if response.error_kind is AiErrorKind.RATE_LIMIT:
            summary["cooldown_triggered"] = True
            summary["retry_after_seconds"] = response.retry_after_seconds
            break
    return summary, records


class _SyntheticBackend:
    def __init__(self, provider: str, responses: list[AiResponse]) -> None:
        self.provider = provider
        self.model = "synthetic"
        self.timeout_seconds = 1.0
        self._responses = list(responses)
        self.calls = 0

    def health(self) -> BackendHealth:
        return BackendHealth(ServiceStatus.HEALTHY, "synthetic")

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities()

    def generate(self, _request: AiRequest) -> AiResponse:
        self.calls += 1
        return self._responses[min(self.calls - 1, len(self._responses) - 1)]


def simulated_fallback_checks() -> dict[str, Any]:
    """Exercise fallback/cooldown without touching a network."""

    request = AiRequest(
        request_id="simulated-fallback",
        messages=[ChatMessage(role="user", content="synthetic")],
        privacy_level=PrivacyLevel.PUBLIC,
    )
    fallback = _SyntheticBackend(
        "remote:fallback",
        [AiResponse(text="synthetic ok", provider="remote:fallback", model="synthetic")],
    )
    limited = _SyntheticBackend(
        "remote:limited",
        [AiResponse(
            text="",
            finish_reason="rate_limited",
            provider="remote:limited",
            model="synthetic",
            error_kind=AiErrorKind.RATE_LIMIT,
            retry_after_seconds=30.0,
        )],
    )
    orchestrator = AiOrchestrator(
        backends={"remote:limited": limited, "remote:fallback": fallback}
    )
    route = RoutePlan(
        "remote:limited", ["remote:fallback"], allow_sanitized_external=True
    )
    first, _ = orchestrator.execute(request, route)
    second, _ = orchestrator.execute(request, route)

    timed_out = _SyntheticBackend(
        "remote:timed_out",
        [AiResponse(
            text="",
            finish_reason="timeout",
            provider="remote:timed_out",
            model="synthetic",
            error_kind=AiErrorKind.TIMEOUT,
        )],
    )
    timeout_fallback = _SyntheticBackend(
        "remote:fallback",
        [AiResponse(text="synthetic ok", provider="remote:fallback", model="synthetic")],
    )
    timeout_response, _ = AiOrchestrator(
        backends={"remote:timed_out": timed_out, "remote:fallback": timeout_fallback}
    ).execute(
        request,
        RoutePlan(
            "remote:timed_out", ["remote:fallback"], allow_sanitized_external=True
        ),
    )
    return {
        "rate_limit_fallback_passed": first.provider == "remote:fallback",
        "cooldown_passed": limited.calls == 1 and second.provider == "remote:fallback",
        "timeout_fallback_passed": timeout_response.provider == "remote:fallback",
        "classified_rate_limit": (
            first.attempts[0].error_kind.value if first.attempts else None
        ),
        "classified_timeout": (
            timeout_response.attempts[0].error_kind.value
            if timeout_response.attempts
            else None
        ),
    }


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 1) if values else None


def build_report(
    cfg: AILENConfig,
    provider_ids: list[str],
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    cases = synthetic_cases()[:limit]
    summaries: list[dict[str, Any]] = []
    records: list[ProbeRecord] = []
    resolver = SecretResolver()
    for provider_id in provider_ids:
        provider_cfg = cfg.ai.remote.providers[provider_id]
        key = resolver.resolve(
            env_var=provider_cfg.api_key_env,
            file_name=provider_cfg.api_key_file,
        )
        provider = build_remote_backend(provider_id, provider_cfg, api_key=key)
        summary, provider_records = _probe_provider(
            f"remote:{provider_id}",
            provider,
            cases,
            timeout_seconds,
            min(max(32, cfg.ai.max_tokens), 128),
        )
        summaries.append(summary)
        records.extend(provider_records)

    aggregates: dict[str, Any] = {}
    for provider_id in provider_ids:
        route = f"remote:{provider_id}"
        selected = [record for record in records if record.provider_requested == route]
        aggregates[route] = {
            "turns_attempted": len(selected),
            "turns_completed": sum(record.response_chars > 0 for record in selected),
            "first_text_avg_ms": _mean(
                [record.first_text_ms for record in selected if record.first_text_ms is not None]
            ),
            "total_avg_ms": _mean([record.total_ms for record in selected]),
            "request_chars_avg": _mean(
                [float(record.request_chars) for record in selected if record.request_chars is not None]
            ),
            "provider_input_tokens_avg": _mean(
                [float(record.input_tokens) for record in selected if record.input_tokens is not None]
            ),
            "sanitization_passed": all(record.sanitization_passed for record in selected),
            "streaming_observed": any(record.streaming_observed for record in selected),
        }
    return {
        "schema_version": 2,
        "session_id": f"remote-ai-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}",
        "created_at": datetime.now(UTC).isoformat(),
        "lab_host": "ASRock contended",
        "load_average": list(os.getloadavg()),
        "local_ai_enabled": cfg.ai.local.enabled,
        "local_or_lan_used": False,
        "privacy_mode": "SANITIZED_REMOTE_CURRENT_TURN_ONLY",
        "prompts_persisted": False,
        "responses_persisted": False,
        "provider_summaries": summaries,
        "records": [asdict(record) for record in records],
        "aggregates": aggregates,
        "simulated_checks": simulated_fallback_checks(),
    }


def _write_report(report: dict[str, Any], output_root: Path) -> Path:
    session_dir = output_root / str(report["session_id"])
    session_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    json_path = session_dir / "summary.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    json_path.chmod(0o600)
    lines = [
        "# Remote AI validation",
        "",
        f"- Session: `{report['session_id']}`",
        "- Host: ASRock contended; external load was not modified",
        "- Privacy: current synthetic turn only; prompts/responses not persisted",
        "- Local/LAN inference used: no",
        "",
        "| Provider | Attempts | Completed | First text avg | Total avg |",
        "|---|---:|---:|---:|---:|",
    ]
    for provider_id, aggregate in report["aggregates"].items():
        lines.append(
            f"| {provider_id} | {aggregate['turns_attempted']} | "
            f"{aggregate['turns_completed']} | {aggregate['first_text_avg_ms']} ms | "
            f"{aggregate['total_avg_ms']} ms |"
        )
    lines.extend([
        "",
        "Simulated error paths: " + json.dumps(report["simulated_checks"], sort_keys=True),
        "",
    ])
    markdown_path = session_dir / "summary.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    markdown_path.chmod(0o600)
    return session_dir


def _configured_provider_ids(cfg: AILENConfig) -> list[str]:
    return [
        provider_id
        for provider_id, provider in sorted(
            cfg.ai.remote.providers.items(), key=lambda item: item[1].priority
        )
        if cfg.ai.remote.enabled and provider.enabled
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/ailen.toml")
    parser.add_argument(
        "--providers",
        default="configured",
        help="configured or comma-separated provider IDs from ai.remote.providers",
    )
    parser.add_argument("--limit", type=int, default=8, choices=range(1, 9))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output-root", default="runtime/lab/external_ai_validation")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="explicitly allow synthetic requests to configured remote providers",
    )
    return parser.parse_args(argv)


def _validate_selection(
    cfg: AILENConfig,
    provider_ids: list[str],
) -> tuple[bool, str]:
    if not cfg.ai.remote.enabled or not cfg.ai.allow_remote:
        return False, "remote providers are disabled"
    if not cfg.ai.allow_sanitized_external_prompts:
        return False, "sanitized-current-turn remote prompts are not authorized"
    if not provider_ids:
        return False, "no enabled remote provider was selected"
    unknown = [item for item in provider_ids if item not in cfg.ai.remote.providers]
    if unknown:
        return False, f"unknown remote provider IDs: {', '.join(unknown)}"
    disabled = [item for item in provider_ids if not cfg.ai.remote.providers[item].enabled]
    if disabled:
        return False, f"remote providers are not enabled: {', '.join(disabled)}"
    return True, ""


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    cfg = load_config(args.config)
    provider_ids = (
        _configured_provider_ids(cfg)
        if args.providers == "configured"
        else [part.strip() for part in args.providers.split(",") if part.strip()]
    )
    selected, reason = _validate_selection(cfg, provider_ids)
    if not selected:
        print(f"REFUSED: {reason}.")
        return 2
    if not args.execute:
        print(
            "DRY RUN: configured remote providers: "
            + ", ".join(provider_ids)
            + ". Add --execute only with explicit API consent; no request was sent."
        )
        return 0
    print(
        "Remote validation with explicit consent: "
        + " -> ".join(f"remote:{item}" for item in provider_ids)
        + " | ASRock contended",
        flush=True,
    )
    try:
        report = build_report(
            cfg,
            provider_ids,
            limit=args.limit,
            timeout_seconds=max(1.0, args.timeout),
        )
        session_dir = _write_report(report, Path(args.output_root))
    except Exception as exc:  # noqa: BLE001
        print(f"VALIDATION FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"Validation artifact: {session_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

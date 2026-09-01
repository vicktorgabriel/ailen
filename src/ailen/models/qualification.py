"""Versioned evidence manifests for qualifying local quantized LLM artifacts.

The catalog may describe candidates, but only a completed manifest can support
an installation-specific qualification decision. This module never downloads
weights and never treats an ASRock laboratory result as proof for recycled
target hardware.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ailen.models.catalog import (
    ModelDescriptor,
    ModelQualificationStatus,
)

_HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass
class ModelArtifactEvidence:
    """Exact, reviewable identity of one model artifact."""

    source_url: str
    source_reference: str
    license_name: str
    quantization: str
    artifact_format: str
    size_bytes: int
    sha256: str
    lfs_oid: str = ""
    runtime: str = ""
    context_tokens: int = 0
    chat_template: str = ""


@dataclass
class ModelBenchmarkEvidence:
    """One real measurement on an identified hardware target."""

    hardware_id: str
    total_ram_mb: int
    runtime: str
    rss_peak_mb: int
    ttfa_ms: float
    tokens_per_second: float
    quality_score: float
    prompt_set: str
    measured_at: str
    notes: str = ""

    def validate(self) -> None:
        if not self.hardware_id.strip() or not self.runtime.strip():
            raise ValueError("benchmark hardware_id and runtime are required")
        if self.total_ram_mb <= 0 or self.rss_peak_mb <= 0:
            raise ValueError("benchmark RAM measurements must be positive")
        if self.ttfa_ms <= 0 or self.tokens_per_second <= 0:
            raise ValueError("benchmark latency and throughput must be positive")
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("benchmark quality_score must be between 0 and 1")
        if not self.prompt_set.strip() or not self.measured_at.strip():
            raise ValueError("benchmark prompt_set and measured_at are required")


@dataclass
class ModelQualificationManifest:
    """Qualification record kept separately from downloadable model weights."""

    model_id: str
    artifact: ModelArtifactEvidence
    status: ModelQualificationStatus = ModelQualificationStatus.CANDIDATE
    evidence: list[ModelBenchmarkEvidence] = field(default_factory=list)
    schema_version: int = 1
    rejection_reason: str = ""

    def missing_for_qualification(self) -> list[str]:
        """List missing proof without silently promoting a candidate."""
        missing: list[str] = []
        artifact = self.artifact
        if not artifact.source_url.startswith("https://"):
            missing.append("exact_https_source")
        if not artifact.source_reference.strip():
            missing.append("source_reference")
        if not artifact.license_name.strip():
            missing.append("license")
        if not artifact.quantization.strip() or not artifact.artifact_format.strip():
            missing.append("format_and_quantization")
        if artifact.size_bytes <= 0:
            missing.append("artifact_size")
        if not (_HEX_64_RE.fullmatch(artifact.sha256) or artifact.lfs_oid.strip()):
            missing.append("verifiable_digest")
        if not artifact.runtime.strip():
            missing.append("runtime")
        if artifact.context_tokens <= 0:
            missing.append("effective_context")
        if not artifact.chat_template.strip():
            missing.append("chat_template")
        valid_target_evidence = False
        for item in self.evidence:
            try:
                item.validate()
            except ValueError:
                continue
            valid_target_evidence = True
            break
        if not valid_target_evidence:
            missing.append("target_hardware_evidence")
        return missing

    def can_mark_qualified(self) -> bool:
        return not self.missing_for_qualification()

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"unsupported qualification schema_version: {self.schema_version}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.model_id):
            raise ValueError("invalid model_id")
        for item in self.evidence:
            item.validate()
        if self.status is ModelQualificationStatus.QUALIFIED and not self.can_mark_qualified():
            missing = ", ".join(self.missing_for_qualification())
            raise ValueError(f"model cannot be qualified; missing: {missing}")
        if self.status is ModelQualificationStatus.REJECTED and not self.rejection_reason.strip():
            raise ValueError("rejected model requires rejection_reason")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ModelQualificationManifest:
        artifact_raw = raw.get("artifact")
        evidence_raw = raw.get("evidence", [])
        if not isinstance(artifact_raw, dict) or not isinstance(evidence_raw, list):
            raise TypeError("qualification manifest requires artifact object and evidence list")
        try:
            status = ModelQualificationStatus(str(raw.get("status", "candidate")))
            artifact = ModelArtifactEvidence(**artifact_raw)
            evidence = [ModelBenchmarkEvidence(**item) for item in evidence_raw]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid qualification manifest: {exc}") from exc
        manifest = cls(
            schema_version=int(raw.get("schema_version", 0)),
            model_id=str(raw.get("model_id", "")),
            artifact=artifact,
            status=status,
            evidence=evidence,
            rejection_reason=str(raw.get("rejection_reason", "")),
        )
        manifest.validate()
        return manifest


def qualification_template(descriptor: ModelDescriptor) -> ModelQualificationManifest:
    """Create an honest candidate template from catalog facts only."""
    return ModelQualificationManifest(
        model_id=descriptor.model_id,
        artifact=ModelArtifactEvidence(
            source_url=descriptor.source_url,
            source_reference=descriptor.source_reference or "",
            license_name=descriptor.license_name,
            quantization=descriptor.quantization,
            artifact_format=descriptor.artifact_format,
            size_bytes=descriptor.disk_size_bytes,
            sha256=descriptor.sha256,
            runtime=descriptor.runtime,
            context_tokens=descriptor.context_default,
            chat_template=descriptor.chat_template,
        ),
        status=ModelQualificationStatus.CANDIDATE,
    )

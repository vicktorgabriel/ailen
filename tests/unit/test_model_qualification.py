"""Tests for evidence-backed local model qualification manifests."""

import json
from pathlib import Path

import pytest

from ailen.models.catalog import ModelCatalog, ModelQualificationStatus
from ailen.models.qualification import (
    ModelBenchmarkEvidence,
    ModelQualificationManifest,
    qualification_template,
)


def test_catalog_candidate_produces_incomplete_honest_template() -> None:
    descriptor = ModelCatalog().get_model("qwen3.5-0.8b-q4_0")
    assert descriptor is not None

    manifest = qualification_template(descriptor)

    assert manifest.status is ModelQualificationStatus.CANDIDATE
    assert manifest.artifact.sha256 == descriptor.sha256
    assert manifest.evidence == []
    assert "target_hardware_evidence" in manifest.missing_for_qualification()
    assert manifest.can_mark_qualified() is False


def test_qualification_requires_artifact_identity_and_target_measurement() -> None:
    descriptor = ModelCatalog().get_model("qwen3.5-0.8b-q4_0")
    assert descriptor is not None
    candidate = qualification_template(descriptor)
    candidate.artifact.chat_template = "synthetic-chat-template-v1"
    candidate.evidence.append(
        ModelBenchmarkEvidence(
            hardware_id="recycled-unit-01",
            total_ram_mb=4096,
            runtime="llama.cpp",
            rss_peak_mb=1650,
            ttfa_ms=820.0,
            tokens_per_second=12.5,
            quality_score=0.78,
            prompt_set="ailen-voice-v1",
            measured_at="2026-08-31T00:00:00Z",
        )
    )

    assert candidate.missing_for_qualification() == []
    assert candidate.can_mark_qualified() is True

    candidate.status = ModelQualificationStatus.QUALIFIED
    candidate.validate()


def test_qualified_manifest_without_evidence_fails_closed() -> None:
    descriptor = ModelCatalog().get_model("qwen3.5-0.8b-q4_0")
    assert descriptor is not None
    manifest = qualification_template(descriptor)
    manifest.status = ModelQualificationStatus.QUALIFIED

    with pytest.raises(ValueError, match="cannot be qualified"):
        manifest.validate()


def test_manifest_round_trip_is_versioned_and_does_not_embed_weights(tmp_path: Path) -> None:
    descriptor = ModelCatalog().get_model("qwen3.5-0.8b-q4_0")
    assert descriptor is not None
    manifest = qualification_template(descriptor)
    output = tmp_path / "qualification.json"
    output.write_text(manifest.to_json(), encoding="utf-8")

    raw = json.loads(output.read_text(encoding="utf-8"))
    loaded = ModelQualificationManifest.from_dict(raw)

    assert loaded.schema_version == 1
    assert loaded.model_id == descriptor.model_id
    assert loaded.artifact.size_bytes == descriptor.disk_size_bytes
    assert "weights" not in raw

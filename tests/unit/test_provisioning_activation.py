"""Tests for the stable install-plan -> runtime-selection boundary."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ailen.core.config import AILENConfig
from ailen.domain.enums import DeviceProfile
from ailen.hardware.contracts import (
    CpuInfo,
    HardwareCapabilityReport,
    OsFamily,
    RamInfo,
)
from ailen.models.catalog import ModelCatalog, ModelDescriptor, ModelPurpose
from ailen.models.store import ModelStore
from ailen.provisioning.activation import (
    LocalAiSelectionError,
    LocalAiSelectionStore,
)
from ailen.provisioning.planner import (
    HardwareModelQualification,
    HardwareQualificationStore,
    ProvisioningPlan,
    ProvisioningPlanner,
    hardware_class_id,
)
from ailen.runtime.runner import LabRunner


def _report(total_mb: int = 8192, available_mb: int = 6144) -> HardwareCapabilityReport:
    return HardwareCapabilityReport(
        timestamp_utc="2026-09-01T00:00:00Z",
        os_name="linux",
        os_version="test",
        os_distribution="test",
        os_family=OsFamily.LINUX,
        cpu=CpuInfo(
            model="synthetic",
            architecture="x86_64",
            physical_cores=4,
            logical_cores=8,
            flags=["avx2"],
            has_avx2=True,
        ),
        ram=RamInfo(
            total_bytes=total_mb * 1024**2,
            available_bytes=available_mb * 1024**2,
        ),
    )


def _descriptor(payload: bytes) -> ModelDescriptor:
    return ModelDescriptor(
        model_id="qualified-selection-model",
        display_name="Qualified selection model",
        family="test",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_0",
        parameter_class="small",
        context_default=4096,
        ram_requirement_mb=1200,
        vram_requirement_mb=1400,
        disk_size_bytes=len(payload),
        source_url="https://example.invalid/qualified.gguf",
        sha256=hashlib.sha256(payload).hexdigest(),
        downloadable=True,
        source_reference="synthetic/qualified",
        suitability_profiles=[DeviceProfile.HYBRID],
        purposes=[ModelPurpose.FAST, ModelPurpose.BALANCED],
        quality_rank=70,
        supported_runtimes=["llama.cpp", "ollama"],
        runtime_aliases=["qualified-selection-model:latest"],
    )


def _qualified_plan(
    report: HardwareCapabilityReport,
    descriptor: ModelDescriptor,
    *,
    runtime: str = "llama.cpp",
    context_tokens: int = 3072,
) -> ProvisioningPlan:
    evidence = HardwareModelQualification(
        model_id=descriptor.model_id,
        hardware_class=hardware_class_id(report),
        status="qualified",
        quality_score=0.82,
        ttfa_ms=510.0,
        tokens_per_second=18.0,
        runtime=runtime,
        context_tokens=context_tokens,
        evidence_reference="synthetic:target-hardware",
        execution_device="cpu",
        gpu_layers=0,
        peak_rss_mb=1300,
    )
    return ProvisioningPlanner(
        catalog=ModelCatalog([descriptor]),
        qualifications=HardwareQualificationStore([evidence]),
    ).plan(report)


def test_selection_store_activates_exact_verified_plan_atomically(tmp_path: Path) -> None:
    payload = b"tiny synthetic gguf"
    descriptor = _descriptor(payload)
    catalog = ModelCatalog([descriptor])
    report = _report()
    plan = _qualified_plan(report, descriptor)
    model_store = ModelStore(tmp_path / "models")
    model_store.ensure_directory()
    model_store.get_model_path(descriptor.model_id).write_bytes(payload)
    selection_store = LocalAiSelectionStore(tmp_path / "state" / "local-ai.json")

    selection = selection_store.activate(
        plan,
        catalog=catalog,
        model_store=model_store,
    )
    loaded = selection_store.load(
        report,
        catalog=catalog,
        model_store=model_store,
    )

    assert loaded == selection
    assert stat.S_IMODE(selection_store.path.stat().st_mode) == 0o600
    runtime_plan = loaded.to_model_plan(catalog)
    assert runtime_plan.selected_model_id == descriptor.model_id
    assert runtime_plan.runtime == "llama.cpp"
    assert runtime_plan.context_size == plan.context_tokens
    assert runtime_plan.model_descriptor is not None
    assert runtime_plan.model_descriptor.qualification_status.value == "qualified"


def test_selection_store_rejects_hardware_change_and_tampered_artifact(tmp_path: Path) -> None:
    payload = b"tiny synthetic gguf"
    descriptor = _descriptor(payload)
    catalog = ModelCatalog([descriptor])
    report = _report()
    plan = _qualified_plan(report, descriptor)
    model_store = ModelStore(tmp_path / "models")
    model_store.ensure_directory()
    model_path = model_store.get_model_path(descriptor.model_id)
    model_path.write_bytes(payload)
    selection_store = LocalAiSelectionStore(tmp_path / "state" / "local-ai.json")
    selection_store.activate(plan, catalog=catalog, model_store=model_store)

    with pytest.raises(LocalAiSelectionError, match="hardware class"):
        selection_store.load(_report(16384, 12000), catalog=catalog, model_store=model_store)

    model_path.write_bytes(b"tampered")
    with pytest.raises(LocalAiSelectionError, match="artifact"):
        selection_store.load(report, catalog=catalog, model_store=model_store)


def test_selection_store_rejects_loose_permissions_and_coerced_types(
    tmp_path: Path,
) -> None:
    payload = b"tiny synthetic gguf"
    descriptor = _descriptor(payload)
    catalog = ModelCatalog([descriptor])
    report = _report()
    plan = _qualified_plan(report, descriptor)
    model_store = ModelStore(tmp_path / "models")
    model_store.ensure_directory()
    model_store.get_model_path(descriptor.model_id).write_bytes(payload)
    selection_store = LocalAiSelectionStore(tmp_path / "state" / "local-ai.json")
    selection_store.activate(plan, catalog=catalog, model_store=model_store)

    selection_store.path.chmod(0o666)
    with pytest.raises(LocalAiSelectionError, match="unsafe"):
        selection_store.load(report, catalog=catalog, model_store=model_store)

    selection_store.path.chmod(0o600)
    raw = json.loads(selection_store.path.read_text(encoding="utf-8"))
    raw["context_tokens"] = "2048"
    selection_store.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LocalAiSelectionError, match="integer fields"):
        selection_store.load(report, catalog=catalog, model_store=model_store)


def test_selection_store_rejects_symlinked_model_artifact(tmp_path: Path) -> None:
    payload = b"tiny synthetic gguf"
    descriptor = _descriptor(payload)
    catalog = ModelCatalog([descriptor])
    report = _report()
    plan = _qualified_plan(report, descriptor)
    model_store = ModelStore(tmp_path / "models")
    model_store.ensure_directory()
    external = tmp_path / "external.gguf"
    external.write_bytes(payload)
    model_store.get_model_path(descriptor.model_id).symlink_to(external)

    with pytest.raises(LocalAiSelectionError, match="unsafe"):
        LocalAiSelectionStore(tmp_path / "selection.json").activate(
            plan,
            catalog=catalog,
            model_store=model_store,
        )


def test_selection_store_never_activates_candidate_plan(tmp_path: Path) -> None:
    descriptor = _descriptor(b"payload")
    candidate_plan = ProvisioningPlanner(catalog=ModelCatalog([descriptor])).plan(
        _report()
    )

    with pytest.raises(LocalAiSelectionError, match="qualified"):
        LocalAiSelectionStore(tmp_path / "local-ai.json").activate(
            candidate_plan,
            catalog=ModelCatalog([descriptor]),
            model_store=ModelStore(tmp_path / "models"),
        )


def test_runner_consumes_activated_runtime_instead_of_replanning_it() -> None:
    payload = b"payload"
    descriptor = _descriptor(payload)
    report = _report()
    plan = _qualified_plan(report, descriptor)
    selection_store = MagicMock()
    selection = LocalAiSelectionStore.selection_from_plan(plan)
    selection_store.load.return_value = selection
    config = AILENConfig()
    config.ai.local.enabled = True
    config.ai.local.model = ""
    config.ai.local.runtime = "auto"
    runner = LabRunner(config=config, local_selection_store=selection_store)

    with (
        patch("ailen.runtime.runner.HardwareDetector.detect", return_value=report),
        patch(
            "ailen.runtime.runner.LocalRuntimeManager.detect_available_runtimes",
            return_value=[],
        ),
        patch("ailen.runtime.runner.ModelCatalog", return_value=ModelCatalog([descriptor])),
    ):
        _hardware, runtime_plan = runner.inspect_and_plan()

    assert runtime_plan.runtime == "llama.cpp"
    assert runtime_plan.selected_model_id == descriptor.model_id
    selection_store.load.assert_called_once()


def test_factory_uses_activated_context_for_qualified_ollama_plan() -> None:
    from ailen.runtime.contracts import (
        ExternalRuntimeDescriptor,
        RuntimeHealth,
        RuntimeStatus,
        RuntimeType,
    )
    from ailen.runtime.factory import LabComponentFactory

    descriptor = _descriptor(b"payload")
    report = _report()
    plan = _qualified_plan(
        report,
        descriptor,
        runtime="ollama",
        context_tokens=1536,
    )
    config = AILENConfig()
    config.ai.local.enabled = True
    config.ai.local.model = ""
    config.ai.local.runtime = "auto"
    config.ai.local.context_tokens = 8192
    runtime = ExternalRuntimeDescriptor(
        runtime_type=RuntimeType.OLLAMA,
        executable_path="/usr/bin/ollama",
        endpoint="http://127.0.0.1:11434/v1",
        is_detected=True,
        status=RuntimeStatus.HEALTHY,
        health=RuntimeHealth(
            status=RuntimeStatus.HEALTHY,
            endpoint="http://127.0.0.1:11434/v1",
            is_running=True,
        ),
    )

    with patch(
        "ailen.runtime.inventory.RuntimeModelInventory.list_models",
        return_value=[descriptor.model_id],
    ):
        backends, _status = LabComponentFactory(config).build_ai_backends(
            model_plan=LocalAiSelectionStore.selection_from_plan(plan).to_model_plan(
                ModelCatalog([descriptor])
            ),
            runtime_descriptors=[runtime],
        )

    assert backends["local"].context_tokens == plan.context_tokens


def test_runner_does_not_read_activation_when_local_is_disabled() -> None:
    report = _report()
    selection_store = MagicMock()
    config = AILENConfig()
    config.ai.local.enabled = False
    runner = LabRunner(config=config, local_selection_store=selection_store)

    with (
        patch("ailen.runtime.runner.HardwareDetector.detect", return_value=report),
        patch(
            "ailen.runtime.runner.LocalRuntimeManager.detect_available_runtimes"
        ) as detect_runtimes,
    ):
        runner.inspect_and_plan()

    selection_store.load.assert_not_called()
    detect_runtimes.assert_not_called()


def test_selection_context_cannot_exceed_current_descriptor() -> None:
    payload = b"payload"
    descriptor = _descriptor(payload)
    report = _report()
    plan = _qualified_plan(report, descriptor)
    selection = LocalAiSelectionStore.selection_from_plan(plan)
    too_small = replace(descriptor, context_default=1024)

    with pytest.raises(LocalAiSelectionError, match="context"):
        selection.to_model_plan(ModelCatalog([too_small]))

"""Unit tests for qualification-gated local AI preparation."""

from unittest.mock import MagicMock, patch

from ailen.core.config import AILENConfig
from ailen.domain.enums import DeviceProfile
from ailen.hardware.contracts import (
    CpuInfo,
    HardwareCapabilityReport,
    OsFamily,
    RamInfo,
)
from ailen.models.catalog import ModelCatalog, ModelDescriptor, ModelPurpose
from ailen.provisioning.planner import (
    HardwareModelQualification,
    HardwareQualificationStore,
    ProvisioningPlanner,
    hardware_class_id,
)
from ailen.runtime.prepare import LabAiPreparer


def _hardware() -> HardwareCapabilityReport:
    return HardwareCapabilityReport(
        timestamp_utc="2026-09-01T00:00:00Z",
        os_name="linux",
        os_version="test",
        os_distribution="test",
        os_family=OsFamily.LINUX,
        cpu=CpuInfo(
            model="x86",
            architecture="x86_64",
            physical_cores=4,
            logical_cores=8,
            flags=["avx2"],
            has_avx2=True,
        ),
        ram=RamInfo(
            total_bytes=8 * 1024**3,
            available_bytes=6 * 1024**3,
        ),
    )


def _descriptor() -> ModelDescriptor:
    return ModelDescriptor(
        model_id="qualified-model",
        display_name="Qualified model",
        family="test",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_0",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=1200,
        vram_requirement_mb=1400,
        disk_size_bytes=563_036_064,
        source_url="https://example.com/model.gguf",
        sha256="5" * 64,
        downloadable=True,
        source_reference="test/qualified-model",
        suitability_profiles=[DeviceProfile.HYBRID],
        purposes=[ModelPurpose.FAST, ModelPurpose.BALANCED],
        quality_rank=50,
        supported_runtimes=["llama.cpp"],
    )


def test_prepare_ai_dry_run_is_honest_when_no_model_is_target_qualified(
    tmp_path,
) -> None:
    config = AILENConfig()
    model_store = MagicMock()
    model_store.base_dir = tmp_path
    runtimes = MagicMock()
    runtimes.detect_available_runtimes.return_value = []
    preparer = LabAiPreparer(
        config=config,
        store=model_store,
        runtime_manager=runtimes,
    )

    with patch("ailen.runtime.prepare.HardwareDetector.detect", return_value=_hardware()):
        report, code = preparer.run(auto_download=False, start_runtime=False)

    assert code == 0
    assert report.plan.primary_model_id is None
    assert report.plan.auto_download_allowed is False
    model_store.exists.assert_not_called()


def test_prepare_ai_downloads_only_a_target_qualified_artifact(tmp_path) -> None:
    config = AILENConfig()
    model_store = MagicMock()
    model_store.base_dir = tmp_path
    model_store.exists.return_value = False
    model_store.get_model_path.return_value = tmp_path / "model.gguf"
    runtimes = MagicMock()
    runtimes.detect_available_runtimes.return_value = []
    selection_store = MagicMock()
    selection_store.path = tmp_path / "selection.json"
    hardware = _hardware()
    descriptor = _descriptor()
    qualification = HardwareModelQualification(
        model_id=descriptor.model_id,
        hardware_class=hardware_class_id(hardware),
        status="qualified",
        quality_score=0.8,
        ttfa_ms=600.0,
        tokens_per_second=16.0,
        runtime="llama.cpp",
        context_tokens=2048,
        evidence_reference="synthetic:test",
    )
    planner = ProvisioningPlanner(
        catalog=ModelCatalog([descriptor]),
        qualifications=HardwareQualificationStore([qualification]),
    )
    preparer = LabAiPreparer(
        config=config,
        store=model_store,
        runtime_manager=runtimes,
        provisioning_planner=planner,
        selection_store=selection_store,
    )

    with (
        patch("ailen.runtime.prepare.HardwareDetector.detect", return_value=hardware),
        patch(
            "ailen.runtime.prepare.ModelDownloader.download",
            return_value=tmp_path / "model.gguf",
        ) as download,
    ):
        report, code = preparer.run(auto_download=True, start_runtime=False)

    assert code == 0
    assert report.model_installed is True
    download.assert_called_once_with(descriptor)
    selection_store.activate.assert_not_called()


def test_prepare_ai_activates_only_after_exact_artifact_verification(tmp_path) -> None:
    config = AILENConfig()
    model_store = MagicMock()
    model_store.base_dir = tmp_path
    model_store.exists.return_value = True
    model_store.verify.return_value = True
    model_store.get_model_path.return_value = tmp_path / "model.gguf"
    runtimes = MagicMock()
    runtimes.detect_available_runtimes.return_value = []
    selection_store = MagicMock()
    selection_store.path = tmp_path / "selection.json"
    hardware = _hardware()
    descriptor = _descriptor()
    qualification = HardwareModelQualification(
        model_id=descriptor.model_id,
        hardware_class=hardware_class_id(hardware),
        status="qualified",
        quality_score=0.8,
        ttfa_ms=600.0,
        tokens_per_second=16.0,
        runtime="llama.cpp",
        context_tokens=2048,
        evidence_reference="synthetic:test",
    )
    planner = ProvisioningPlanner(
        catalog=ModelCatalog([descriptor]),
        qualifications=HardwareQualificationStore([qualification]),
    )
    preparer = LabAiPreparer(
        config=config,
        store=model_store,
        runtime_manager=runtimes,
        provisioning_planner=planner,
        selection_store=selection_store,
    )

    with patch("ailen.runtime.prepare.HardwareDetector.detect", return_value=hardware):
        report, code = preparer.run(activate_selection=True)

    assert code == 0
    assert report.selection_activated is True
    assert report.selection_path == str(selection_store.path)
    selection_store.activate.assert_called_once_with(
        report.plan,
        catalog=planner.catalog,
        model_store=model_store,
    )


def test_prepare_ai_never_downloads_an_unqualified_candidate(tmp_path) -> None:
    config = AILENConfig()
    model_store = MagicMock()
    model_store.base_dir = tmp_path
    runtimes = MagicMock()
    runtimes.detect_available_runtimes.return_value = []
    planner = ProvisioningPlanner(catalog=ModelCatalog([_descriptor()]))
    preparer = LabAiPreparer(
        config=config,
        store=model_store,
        runtime_manager=runtimes,
        provisioning_planner=planner,
    )

    with (
        patch("ailen.runtime.prepare.HardwareDetector.detect", return_value=_hardware()),
        patch("ailen.runtime.prepare.ModelDownloader.download") as download,
    ):
        report, code = preparer.run(auto_download=True)

    assert code == 0
    assert report.plan.auto_download_allowed is False
    download.assert_not_called()


def test_prepare_ai_cannot_activate_an_unverified_candidate(tmp_path) -> None:
    config = AILENConfig()
    model_store = MagicMock()
    model_store.base_dir = tmp_path
    model_store.exists.return_value = False
    runtimes = MagicMock()
    runtimes.detect_available_runtimes.return_value = []
    selection_store = MagicMock()
    selection_store.path = tmp_path / "selection.json"
    preparer = LabAiPreparer(
        config=config,
        store=model_store,
        runtime_manager=runtimes,
        provisioning_planner=ProvisioningPlanner(
            catalog=ModelCatalog([_descriptor()])
        ),
        selection_store=selection_store,
    )

    with patch("ailen.runtime.prepare.HardwareDetector.detect", return_value=_hardware()):
        report, code = preparer.run(activate_selection=True)

    assert code == 1
    assert report.selection_activated is False
    selection_store.activate.assert_not_called()

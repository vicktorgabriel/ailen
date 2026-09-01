import pytest

from ailen.models.catalog import (
    ModelCatalog,
    ModelDescriptor,
    ModelQualificationStatus,
)


def test_catalog_listing_and_lookup() -> None:
    catalog = ModelCatalog()
    models = catalog.list_models()
    assert len(models) >= 5

    qwen35_tiny = catalog.get_model("qwen3.5-0.8b-q4_0")
    assert qwen35_tiny is not None
    assert qwen35_tiny.family == "qwen"
    assert qwen35_tiny.parameter_class == "tiny"
    assert qwen35_tiny.ram_requirement_mb == 900
    assert qwen35_tiny.downloadable is True
    assert qwen35_tiny.sha256 == "57d1997790d1744fba5b40a7317df71ea5e2acee28c47e78f0cce39c0703f8cf"
    assert qwen35_tiny.source_reference == "ggml-org/Qwen3.5-0.8B-GGUF"

    # Candidate models have downloadable=False pending hash verification
    qwen_candidate = catalog.get_model("qwen2.5-0.5b-instruct-q4_k_m")
    assert qwen_candidate is not None
    assert qwen_candidate.downloadable is False


def test_catalog_validation_rules() -> None:
    # 1. Invalid model_id containing path traversal characters
    with pytest.raises(ValueError, match="Invalid model_id"):
        ModelDescriptor(
            model_id="../evil-model",
            display_name="Evil",
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_0",
            parameter_class="tiny",
        ).validate()

    # 2. Downloadable without HTTPS
    with pytest.raises(ValueError, match="must use HTTPS URL"):
        ModelDescriptor(
            model_id="test-insecure",
            display_name="Test Insecure",
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_0",
            parameter_class="tiny",
            downloadable=True,
            source_url="http://insecure.example.com/model.gguf",
            sha256="0" * 64,
            source_reference="test",
        ).validate()

    # 3. Downloadable with invalid SHA-256 length
    with pytest.raises(ValueError, match="exact 64-char hex SHA256"):
        ModelDescriptor(
            model_id="test-bad-sha",
            display_name="Test Bad SHA",
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_0",
            parameter_class="tiny",
            downloadable=True,
            source_url="https://example.com/model.gguf",
            sha256="12345",
            source_reference="test",
        ).validate()

    # 4. Duplicate model ID in catalog
    m1 = ModelDescriptor(
        model_id="dup-id",
        display_name="M1",
        family="test",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_0",
        parameter_class="tiny",
    )
    m2 = ModelDescriptor(
        model_id="dup-id",
        display_name="M2",
        family="test",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_0",
        parameter_class="tiny",
    )
    with pytest.raises(ValueError, match="Duplicate model_id"):
        ModelCatalog(models=[m1, m2])


def test_catalog_suitable_models_default_to_verified_downloadable() -> None:
    from ailen.domain.enums import DeviceProfile

    catalog = ModelCatalog()
    models = catalog.find_suitable_models(
        profile=DeviceProfile.LOCAL,
        max_ram_mb=32_000,
        max_vram_mb=16_000,
        cpu_flags=["avx2"],
        os_name="linux",
        arch="x86_64",
    )
    assert models
    assert all(model.downloadable for model in models)
    assert {model.model_id for model in models} == {"qwen3.5-0.8b-q4_0", "qwen3.5-0.8b-q8_0"}

    historical = catalog.find_suitable_models(
        profile=DeviceProfile.LOCAL,
        max_ram_mb=32_000,
        max_vram_mb=16_000,
        cpu_flags=["avx2"],
        os_name="linux",
        arch="x86_64",
        require_downloadable=False,
    )
    assert any(not model.downloadable for model in historical)


def test_catalog_ranks_qualified_quality_and_excludes_rejected_candidates() -> None:
    from ailen.domain.enums import DeviceProfile
    from ailen.models.catalog import ModelPurpose

    def descriptor(
        model_id: str,
        quality_rank: int,
        status: ModelQualificationStatus,
    ) -> ModelDescriptor:
        return ModelDescriptor(
            model_id=model_id,
            display_name=model_id,
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_k_m",
            parameter_class="small",
            ram_requirement_mb=1000,
            vram_requirement_mb=1000,
            disk_size_bytes=100_000_000,
            suitability_profiles=[DeviceProfile.HYBRID],
            purposes=[ModelPurpose.BALANCED],
            quality_rank=quality_rank,
            qualification_status=status,
        )

    catalog = ModelCatalog(
        [
            descriptor("candidate-high", 99, ModelQualificationStatus.CANDIDATE),
            descriptor("qualified-low", 20, ModelQualificationStatus.QUALIFIED),
            descriptor("qualified-high", 70, ModelQualificationStatus.QUALIFIED),
            descriptor("rejected", 100, ModelQualificationStatus.REJECTED),
        ]
    )

    models = catalog.find_suitable_models(
        profile=DeviceProfile.HYBRID,
        max_ram_mb=2000,
        purpose=ModelPurpose.BALANCED,
        require_downloadable=False,
    )

    assert [model.model_id for model in models] == [
        "qualified-high",
        "qualified-low",
        "candidate-high",
    ]

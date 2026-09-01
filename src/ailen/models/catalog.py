"""Declarative catalog for local GGUF models.

Maintains verified metadata, SHA-256 checksums, and resource requirements.
LLMs or dynamic prompts are strictly prohibited from generating arbitrary download URLs.
"""

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ailen.domain.enums import DeviceProfile


class ModelPurpose(str, Enum):
    """Execution purpose intent for local model selection."""
    SANITY = "SANITY"
    FAST = "FAST"
    BALANCED = "BALANCED"
    QUALITY = "QUALITY"


class ModelQualificationStatus(str, Enum):
    """Evidence state for product use; independent from artifact downloadability."""

    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    REJECTED = "rejected"


@dataclass
class ModelDescriptor:
    """Immutable metadata and requirements for a local model artifact."""

    model_id: str
    display_name: str
    family: str  # "qwen", "llama", "smollm", etc.
    runtime: str  # "llama.cpp"
    artifact_format: str  # "gguf"
    quantization: str  # "q4_0", "q4_k_m", "q8_0"
    parameter_class: str  # "tiny", "small", "medium"
    supported_runtimes: list[str] = field(default_factory=list)
    context_default: int = 2048
    ram_requirement_mb: int = 1000
    vram_requirement_mb: int = 1000
    disk_size_bytes: int = 500_000_000
    cpu_requirements: list[str] = field(default_factory=list)  # ["avx2"]
    supported_os: list[str] = field(default_factory=lambda: ["linux", "windows", "darwin"])
    supported_arch: list[str] = field(default_factory=lambda: ["x86_64", "amd64", "arm64", "aarch64"])
    source_url: str = ""
    sha256: str = ""
    downloadable: bool = False
    license_name: str = "Apache-2.0"
    verified_at: str | None = None
    source_reference: str | None = None
    suitability_profiles: list[DeviceProfile] = field(default_factory=list)
    purposes: list[ModelPurpose] = field(
        default_factory=lambda: [ModelPurpose.SANITY, ModelPurpose.BALANCED, ModelPurpose.QUALITY]
    )
    runtime_aliases: list[str] = field(default_factory=list)
    quality_rank: int = 0
    qualification_status: ModelQualificationStatus = ModelQualificationStatus.CANDIDATE
    benchmark_status: str = "unmeasured"
    chat_template: str = ""
    benchmark_reference: str = ""

    def validate(self) -> None:
        """Validate descriptor integrity, path safety and security requirements."""
        if not self.model_id or not re.match(r"^[a-zA-Z0-9_.-]+$", self.model_id):
            raise ValueError(f"Invalid model_id: {self.model_id!r}")
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty")
        if not self.runtime.strip():
            raise ValueError("runtime cannot be empty")
        if self.supported_runtimes and any(
            runtime not in {"llama.cpp", "ollama"}
            for runtime in self.supported_runtimes
        ):
            raise ValueError("supported_runtimes contains an unsupported runtime")
        if not self.artifact_format.strip():
            raise ValueError("artifact_format cannot be empty")
        if self.context_default <= 0:
            raise ValueError(f"context_default must be positive: {self.context_default}")
        if self.ram_requirement_mb < 0 or self.vram_requirement_mb < 0:
            raise ValueError("Memory requirements cannot be negative")
        if self.disk_size_bytes <= 0:
            raise ValueError(f"disk_size_bytes must be positive: {self.disk_size_bytes}")
        if self.quality_rank < 0:
            raise ValueError("quality_rank cannot be negative")
        if self.benchmark_status not in {
            "unmeasured",
            "artifact_only",
            "measured_lab",
            "measured_target",
        }:
            raise ValueError(f"Invalid benchmark_status: {self.benchmark_status!r}")
        if self.downloadable:
            if not self.source_url.startswith("https://"):
                raise ValueError(f"Downloadable models must use HTTPS URL: {self.source_url!r}")
            if len(self.sha256) != 64 or not all(c in "0123456789abcdefABCDEF" for c in self.sha256):
                raise ValueError(f"Downloadable models must specify exact 64-char hex SHA256: {self.sha256!r}")
            if not self.source_reference:
                raise ValueError("Downloadable models must specify source_reference")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["suitability_profiles"] = [p.value for p in self.suitability_profiles]
        d["purposes"] = [p.value for p in self.purposes]
        d["qualification_status"] = self.qualification_status.value
        return d


# Curated catalog of evaluated local models for 2026
DEFAULT_MODELS: list[ModelDescriptor] = [
    # -------------------------------------------------------------------------
    # 2026-08-21 Verified & Downloadable Sanity Models
    # -------------------------------------------------------------------------
    ModelDescriptor(
        model_id="qwen3.5-0.8b-q4_0",
        display_name="Qwen 3.5 0.8B (Q4_0)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_0",
        parameter_class="tiny",
        context_default=2048,
        ram_requirement_mb=900,
        vram_requirement_mb=1100,
        disk_size_bytes=563_036_064,
        cpu_requirements=[],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="https://huggingface.co/ggml-org/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_0.gguf",
        sha256="57d1997790d1744fba5b40a7317df71ea5e2acee28c47e78f0cce39c0703f8cf",
        downloadable=True,
        license_name="Apache-2.0",
        verified_at="2026-08-21",
        source_reference="ggml-org/Qwen3.5-0.8B-GGUF",
        suitability_profiles=[
            DeviceProfile.SATELLITE,
            DeviceProfile.CLOUD,
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.SANITY, ModelPurpose.FAST, ModelPurpose.BALANCED],
        runtime_aliases=[],
        quality_rank=20,
        benchmark_status="artifact_only",
    ),
    ModelDescriptor(
        model_id="qwen3.5-0.8b-q8_0",
        display_name="Qwen 3.5 0.8B (Q8_0)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q8_0",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=1200,
        vram_requirement_mb=1400,
        disk_size_bytes=833_592_096,
        cpu_requirements=[],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="https://huggingface.co/ggml-org/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q8_0.gguf",
        sha256="37ae482d336108d23516fa35e8e0c4126688d81018b87178a18d752a1357814f",
        downloadable=True,
        license_name="Apache-2.0",
        verified_at="2026-08-21",
        source_reference="ggml-org/Qwen3.5-0.8B-GGUF",
        suitability_profiles=[
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.BALANCED, ModelPurpose.QUALITY],
        runtime_aliases=["qwen3.5:0.8b-q8_0", "qwen3.5:0.8b"],
        quality_rank=25,
        benchmark_status="artifact_only",
    ),
    # -------------------------------------------------------------------------
    # Candidates / Historical Metadata (downloadable=False pending hash verify)
    # -------------------------------------------------------------------------
    ModelDescriptor(
        model_id="qwen2.5-0.5b-instruct-q4_k_m",
        display_name="Qwen 2.5 0.5B Instruct (Q4_K_M)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="tiny",
        context_default=2048,
        ram_requirement_mb=600,
        vram_requirement_mb=800,
        disk_size_bytes=397_759_536,
        cpu_requirements=[],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Apache-2.0",
        suitability_profiles=[
            DeviceProfile.SATELLITE,
            DeviceProfile.CLOUD,
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.SANITY],
        runtime_aliases=["qwen2.5:0.5b"],
        quality_rank=10,
    ),
    ModelDescriptor(
        model_id="qwen2.5-1.5b-instruct-q4_k_m",
        display_name="Qwen 2.5 1.5B Instruct (Q4_K_M)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=1400,
        vram_requirement_mb=1600,
        disk_size_bytes=1_120_000_000,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Apache-2.0",
        suitability_profiles=[
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.BALANCED],
        runtime_aliases=["qwen2.5:1.5b"],
        quality_rank=40,
    ),
    ModelDescriptor(
        model_id="smollm2-1.7b-instruct-q4_k_m",
        display_name="SmolLM2 1.7B Instruct (Q4_K_M)",
        family="smollm",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=1500,
        vram_requirement_mb=1800,
        disk_size_bytes=1_079_539_552,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Apache-2.0",
        suitability_profiles=[
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.BALANCED],
        runtime_aliases=["smollm2:1.7b"],
        quality_rank=38,
    ),
    ModelDescriptor(
        model_id="llama-3.2-1b-instruct-q4_k_m",
        display_name="Llama 3.2 1B Instruct (Q4_K_M)",
        family="llama",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=1100,
        vram_requirement_mb=1300,
        disk_size_bytes=810_000_000,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Llama-3.2-Community",
        suitability_profiles=[
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.BALANCED],
        runtime_aliases=["llama3.2:1b"],
        quality_rank=32,
    ),
    ModelDescriptor(
        model_id="qwen2.5-7b-instruct-q4_k_m",
        display_name="Qwen 2.5 7B Instruct (Q4_K_M)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="medium",
        context_default=2048,
        ram_requirement_mb=6500,
        vram_requirement_mb=5500,
        disk_size_bytes=4_680_000_000,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Apache-2.0",
        suitability_profiles=[
            DeviceProfile.LOCAL,
            DeviceProfile.LAN_BRAIN,
        ],
        purposes=[ModelPurpose.QUALITY],
        runtime_aliases=["qwen2.5:7b"],
        quality_rank=85,
    ),
    ModelDescriptor(
        model_id="llama-3.2-3b-instruct-q4_k_m",
        display_name="Llama 3.2 3B Instruct (Q4_K_M)",
        family="llama",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=2800,
        vram_requirement_mb=2600,
        disk_size_bytes=2_020_000_000,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Llama-3.2-Community",
        suitability_profiles=[
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.FAST, ModelPurpose.BALANCED],
        runtime_aliases=["llama3.2:3b", "llama3.2"],
        quality_rank=55,
    ),
    ModelDescriptor(
        model_id="qwen3.5-4b-instruct-q4_k_m",
        display_name="Qwen 3.5 4B Instruct (Q4_K_M)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=3200,
        vram_requirement_mb=3000,
        disk_size_bytes=2_600_000_000,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Apache-2.0",
        suitability_profiles=[
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.FAST, ModelPurpose.BALANCED],
        runtime_aliases=["qwen3.5:4b"],
        quality_rank=70,
    ),
    ModelDescriptor(
        model_id="gemma-3-4b-instruct-q4_k_m",
        display_name="Gemma 3 4B Instruct (Q4_K_M)",
        family="gemma",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=3600,
        vram_requirement_mb=3400,
        disk_size_bytes=2_800_000_000,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Gemma-Terms",
        suitability_profiles=[
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.BALANCED],
        runtime_aliases=["gemma3:4b", "gemma3"],
        quality_rank=65,
    ),
    ModelDescriptor(
        model_id="qwen2.5-3b-instruct-q4_k_m",
        display_name="Qwen 2.5 3B Instruct (Q4_K_M)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="small",
        context_default=2048,
        ram_requirement_mb=2600,
        vram_requirement_mb=2400,
        disk_size_bytes=1_930_000_000,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Apache-2.0",
        suitability_profiles=[
            DeviceProfile.HYBRID,
            DeviceProfile.LOCAL,
        ],
        purposes=[ModelPurpose.FAST, ModelPurpose.BALANCED],
        runtime_aliases=["qwen2.5:3b"],
        quality_rank=60,
    ),
    ModelDescriptor(
        model_id="qwen3.5-9b-instruct-q4_k_m",
        display_name="Qwen 3.5 9B Instruct (Q4_K_M)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="medium",
        context_default=4096,
        ram_requirement_mb=7500,
        vram_requirement_mb=6800,
        disk_size_bytes=6_600_000_000,
        cpu_requirements=["avx2"],
        supported_os=["linux", "windows", "darwin"],
        supported_arch=["x86_64", "amd64", "arm64", "aarch64"],
        source_url="",
        sha256="",
        downloadable=False,
        license_name="Apache-2.0",
        suitability_profiles=[
            DeviceProfile.LOCAL,
            DeviceProfile.LAN_BRAIN,
        ],
        purposes=[ModelPurpose.QUALITY],
        runtime_aliases=["qwen3.5:9b"],
        quality_rank=90,
    ),
]


class ModelCatalog:
    """Catalog repository providing searchable model descriptors."""

    def __init__(self, models: list[ModelDescriptor] | None = None) -> None:
        self._models: dict[str, ModelDescriptor] = {}
        items = models if models is not None else DEFAULT_MODELS
        for m in items:
            m.validate()
            if m.model_id in self._models:
                raise ValueError(f"Duplicate model_id in catalog: {m.model_id}")
            self._models[m.model_id] = m

    def list_models(self) -> list[ModelDescriptor]:
        """Return all catalog model descriptors."""
        return list(self._models.values())

    def get_model(self, model_id: str) -> ModelDescriptor | None:
        """Find model descriptor by unique model ID."""
        return self._models.get(model_id)

    def find_suitable_models(
        self,
        profile: DeviceProfile,
        max_ram_mb: int,
        max_vram_mb: int = 0,
        cpu_flags: list[str] | None = None,
        os_name: str = "linux",
        arch: str = "x86_64",
        purpose: ModelPurpose | None = None,
        require_downloadable: bool = True,
    ) -> list[ModelDescriptor]:
        """Find and rank models matching hardware constraints, profile, and purpose."""
        flags_set = set(cpu_flags or [])
        suitable: list[ModelDescriptor] = []

        for m in self._models.values():
            if require_downloadable and not m.downloadable:
                continue
            if m.qualification_status is ModelQualificationStatus.REJECTED:
                continue

            # Match purpose if requested
            if purpose and purpose not in m.purposes:
                continue

            # Match profile
            if m.suitability_profiles and profile not in m.suitability_profiles:
                continue

            # Match OS and Architecture
            if m.supported_os and os_name.lower() not in [o.lower() for o in m.supported_os]:
                continue
            if m.supported_arch and arch.lower() not in [a.lower() for a in m.supported_arch]:
                continue

            # Match CPU instruction set requirements
            if m.cpu_requirements and not all(req.lower() in flags_set for req in m.cpu_requirements):
                continue

            # Match resource footprint (either fits in RAM or fits in VRAM)
            fits_in_ram = m.ram_requirement_mb <= max_ram_mb
            fits_in_vram = max_vram_mb > 0 and m.vram_requirement_mb <= max_vram_mb

            if fits_in_ram or fits_in_vram:
                suitable.append(m)

        # Capability filtering happens first. Within that safe envelope,
        # measured/qualified descriptors outrank candidates and explicit
        # quality_rank outranks raw parameter count. Footprint is only a tie
        # breaker; it no longer forces every machine onto the smallest model.
        qualification_rank = {
            ModelQualificationStatus.QUALIFIED: 2,
            ModelQualificationStatus.CANDIDATE: 1,
            ModelQualificationStatus.REJECTED: 0,
        }
        benchmark_rank = {
            "measured_target": 3,
            "measured_lab": 2,
            "artifact_only": 1,
            "unmeasured": 0,
        }
        suitable.sort(
            key=lambda m: (
                -qualification_rank[m.qualification_status],
                -benchmark_rank[m.benchmark_status],
                -m.quality_rank,
                m.ram_requirement_mb,
                m.disk_size_bytes,
                m.model_id,
            )
        )

        return suitable

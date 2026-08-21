"""Contracts and domain models for hardware detection and capability reporting.

Provides strongly-typed representations of system resources, instruction sets,
RAM, GPU, disk, audio, cameras, and runtime metadata without fabricating synthetic devices.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ailen.domain.enums import DeviceProfile


class OsFamily(str, Enum):
    """Supported and recognized operating system families."""
    LINUX = "LINUX"
    WINDOWS = "WINDOWS"
    DARWIN = "DARWIN"
    UNKNOWN = "UNKNOWN"


@dataclass
class CpuInfo:
    """Processor specification and capabilities."""
    model: str = "UNKNOWN"
    architecture: str = "UNKNOWN"
    physical_cores: int | None = None
    logical_cores: int | None = None
    flags: list[str] = field(default_factory=list)
    has_avx: bool | None = None
    has_avx2: bool | None = None
    has_fma: bool | None = None
    has_sse4_1: bool | None = None
    has_sse4_2: bool | None = None
    has_neon: bool | None = None


@dataclass
class RamInfo:
    """System memory measurements."""
    total_bytes: int = 0
    available_bytes: int = 0

    @property
    def total_mb(self) -> int:
        return self.total_bytes // (1024 * 1024)

    @property
    def available_mb(self) -> int:
        return self.available_bytes // (1024 * 1024)

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / (1024 * 1024 * 1024), 2)

    @property
    def available_gb(self) -> float:
        return round(self.available_bytes / (1024 * 1024 * 1024), 2)


@dataclass
class GpuInfo:
    """Graphics processor specification."""
    vendor: str = "UNKNOWN"  # "nvidia", "amd", "intel", "apple", "unknown"
    model: str = "UNKNOWN"
    is_dedicated: bool = False
    vram_total_mb: int | None = None
    vram_available_mb: int | None = None
    driver_version: str | None = None
    backend: str | None = None  # "cuda", "rocm", "vulkan", "directml", "metal"


@dataclass
class DiskInfo:
    """Disk partition measurements for model storage location."""
    path: str
    total_bytes: int = 0
    free_bytes: int = 0

    @property
    def total_mb(self) -> int:
        return self.total_bytes // (1024 * 1024)

    @property
    def free_mb(self) -> int:
        return self.free_bytes // (1024 * 1024)

    @property
    def free_gb(self) -> float:
        return round(self.free_bytes / (1024 * 1024 * 1024), 2)


@dataclass
class AudioDeviceReport:
    """Real detected audio endpoint."""
    id: str
    name: str
    is_input: bool
    is_output: bool
    is_default: bool = False


@dataclass
class CameraDeviceReport:
    """Real detected camera device."""
    device_path: str
    index: int
    name: str = "Camera"
    is_available: bool = True


@dataclass
class DisplayDeviceReport:
    """Real detected display output."""
    name: str
    width: int | None = None
    height: int | None = None
    is_primary: bool = False


@dataclass
class RuntimeInfo:
    """Python environment and process metadata."""
    python_version: str
    executable: str
    os_family: OsFamily
    is_wsl: bool = False
    is_container: bool = False


@dataclass
class ProfileRecommendation:
    """Recommended architectural profile and inference budget based on capability report."""
    profile: DeviceProfile
    local_inference_capable: bool
    recommended_local_budget_mb: int
    gpu_inference_capable: bool
    preferred_runtime: str  # "llama.cpp", "ollama", "none"
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.value,
            "local_inference_capable": self.local_inference_capable,
            "recommended_local_budget_mb": self.recommended_local_budget_mb,
            "gpu_inference_capable": self.gpu_inference_capable,
            "preferred_runtime": self.preferred_runtime,
            "reason_codes": list(self.reason_codes),
        }


@dataclass
class HardwareCapabilityReport:
    """Complete, normalized hardware and capability report."""
    timestamp_utc: str
    os_name: str
    os_version: str
    os_distribution: str
    os_family: OsFamily
    cpu: CpuInfo
    ram: RamInfo
    gpus: list[GpuInfo] = field(default_factory=list)
    disk: DiskInfo | None = None
    audio_inputs: list[AudioDeviceReport] = field(default_factory=list)
    audio_outputs: list[AudioDeviceReport] = field(default_factory=list)
    cameras: list[CameraDeviceReport] = field(default_factory=list)
    displays: list[DisplayDeviceReport] = field(default_factory=list)
    runtime: RuntimeInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        d = asdict(self)
        d["os_family"] = self.os_family.value
        if self.runtime:
            d["runtime"]["os_family"] = self.runtime.os_family.value
        d["ram"]["total_mb"] = self.ram.total_mb
        d["ram"]["available_mb"] = self.ram.available_mb
        d["ram"]["total_gb"] = self.ram.total_gb
        d["ram"]["available_gb"] = self.ram.available_gb
        if self.disk:
            d["disk"]["total_mb"] = self.disk.total_mb
            d["disk"]["free_mb"] = self.disk.free_mb
            d["disk"]["free_gb"] = self.disk.free_gb
        return d

"""Adaptive model planner computing optimal local model and runtime parameters."""

from dataclasses import asdict, dataclass, field
from typing import Any

from ailen.domain.enums import DeviceProfile
from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.models.catalog import ModelCatalog, ModelDescriptor, ModelPurpose


@dataclass
class ModelPlan:
    """Execution plan for local model inference."""

    selected_model_id: str | None
    runtime: str = "none"  # "llama.cpp", "ollama", "none"
    device: str = "none"  # "cuda", "cpu", "none"
    gpu_layers: int | str = 0  # "all" or 0
    estimated_ram_mb: int = 0
    estimated_vram_mb: int = 0
    context_size: int = 2048
    reason_codes: list[str] = field(default_factory=list)
    is_viable: bool = False
    model_descriptor: ModelDescriptor | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.model_descriptor:
            d["model_descriptor"] = self.model_descriptor.to_dict()
        return d


class ModelPlanner:
    """Evaluates hardware capabilities and selects viable models respecting strict safety margins."""

    def __init__(self, catalog: ModelCatalog | None = None) -> None:
        self.catalog = catalog or ModelCatalog()

    def plan(
        self,
        report: HardwareCapabilityReport,
        profile: DeviceProfile | None = None,
        prefer_gpu: bool = True,
        max_ram_fraction: float = 0.60,
        max_vram_fraction: float = 0.80,
        desired_context: int = 2048,
        purpose: ModelPurpose = ModelPurpose.BALANCED,
        require_downloadable: bool = True,
    ) -> ModelPlan:
        """Compute viable model plan based on hardware report, safety margins, and execution purpose."""
        # 1. Parameter Validation
        if not (0.0 < max_ram_fraction <= 1.0):
            raise ValueError(f"max_ram_fraction must be in (0, 1], got {max_ram_fraction}")
        if not (0.0 < max_vram_fraction <= 1.0):
            raise ValueError(f"max_vram_fraction must be in (0, 1], got {max_vram_fraction}")
        if desired_context <= 0:
            raise ValueError(f"desired_context must be positive, got {desired_context}")

        # 2. Check for missing/unknown RAM probe
        total_ram_mb = report.ram.total_mb
        avail_ram_mb = report.ram.available_mb
        if total_ram_mb == 0 or avail_ram_mb == 0:
            return ModelPlan(
                selected_model_id=None,
                runtime="none",
                device="none",
                gpu_layers=0,
                estimated_ram_mb=0,
                estimated_vram_mb=0,
                context_size=desired_context,
                reason_codes=["HARDWARE_RAM_UNKNOWN", "LOCAL_PLAN_BLOCKED_INSUFFICIENT_EVIDENCE"],
                is_viable=False,
            )

        # 3. Determine effective profile
        effective_profile = profile or DeviceProfile.HYBRID
        if total_ram_mb < 3000:
            effective_profile = DeviceProfile.SATELLITE

        if effective_profile == DeviceProfile.SATELLITE:
            return ModelPlan(
                selected_model_id=None,
                runtime="none",
                device="none",
                gpu_layers=0,
                estimated_ram_mb=0,
                estimated_vram_mb=0,
                context_size=desired_context,
                reason_codes=["SATELLITE_NO_LOCAL_LLM", "DELEGATE_REMOTE_ONLY"],
                is_viable=False,
            )

        # 4. Compute safety margin memory budgets
        usable_ram_mb = max(0, int(avail_ram_mb * max_ram_fraction))

        best_gpu_vram_mb = 0
        best_gpu_backend: str | None = None
        for gpu in report.gpus:
            if gpu.is_dedicated and gpu.vram_available_mb is not None and gpu.vram_available_mb > best_gpu_vram_mb:
                best_gpu_vram_mb = gpu.vram_available_mb
                best_gpu_backend = gpu.backend

        usable_vram_mb = max(0, int(best_gpu_vram_mb * max_vram_fraction)) if best_gpu_vram_mb > 0 else 0

        # 5. Query candidate models from catalog
        cpu_flags_list = report.cpu.flags if report.cpu.flags else []
        if report.cpu.has_avx2 is True and "avx2" not in cpu_flags_list:
            cpu_flags_list = [*cpu_flags_list, "avx2"]

        candidates = self.catalog.find_suitable_models(
            profile=effective_profile,
            max_ram_mb=usable_ram_mb,
            max_vram_mb=usable_vram_mb,
            cpu_flags=cpu_flags_list,
            os_name=report.os_name,
            arch=report.cpu.architecture,
            purpose=purpose,
            require_downloadable=require_downloadable,
        )

        reasons: list[str] = []

        # 6. Evaluate candidates against GPU first, then CPU
        for candidate in candidates:
            # Check CPU instruction set requirements even for GPU (since host runs runtime CPU loop)
            if "avx2" in candidate.cpu_requirements and report.cpu.has_avx2 is False:
                reasons.append(f"SKIPPED_{candidate.model_id}_NO_AVX2")
                continue

            # Check disk space if disk info is available
            if report.disk and report.disk.free_bytes > 0:
                required_disk_bytes = candidate.disk_size_bytes + 100_000_000  # 100 MB buffer
                if report.disk.free_bytes < required_disk_bytes:
                    reasons.append(f"SKIPPED_{candidate.model_id}_INSUFFICIENT_DISK")
                    continue

            effective_context = min(desired_context, candidate.context_default)

            # Check GPU offload fit
            if (
                prefer_gpu
                and usable_vram_mb > 0
                and candidate.vram_requirement_mb <= usable_vram_mb
                and best_gpu_backend == "cuda"
            ):
                reasons.append(f"GPU_VRAM_FIT_{candidate.vram_requirement_mb}MB")
                reasons.append("OFFLOAD_ALL_LAYERS")
                reasons.append(f"SELECTED_{candidate.parameter_class.upper()}_MODEL")
                # Host RAM buffer for context / runtime working set
                host_ram_estimate = max(100, candidate.ram_requirement_mb // 5)
                return ModelPlan(
                    selected_model_id=candidate.model_id,
                    runtime="llama.cpp",
                    device="cuda",
                    gpu_layers="all",
                    estimated_ram_mb=host_ram_estimate,
                    estimated_vram_mb=candidate.vram_requirement_mb,
                    context_size=effective_context,
                    reason_codes=reasons,
                    is_viable=True,
                    model_descriptor=candidate,
                )

            # Check CPU RAM fit
            if candidate.ram_requirement_mb <= usable_ram_mb:
                reasons.append(f"CPU_RAM_FIT_{candidate.ram_requirement_mb}MB")
                reasons.append("CPU_INFERENCE_ZERO_GPU_LAYERS")
                reasons.append(f"SELECTED_{candidate.parameter_class.upper()}_MODEL")
                return ModelPlan(
                    selected_model_id=candidate.model_id,
                    runtime="llama.cpp",
                    device="cpu",
                    gpu_layers=0,
                    estimated_ram_mb=candidate.ram_requirement_mb,
                    estimated_vram_mb=0,
                    context_size=effective_context,
                    reason_codes=reasons,
                    is_viable=True,
                    model_descriptor=candidate,
                )

        # 7. No viable model fits within safety margins
        reasons.append("INSUFFICIENT_MEMORY_MARGIN")
        reasons.append("NO_VIABLE_LOCAL_MODEL")
        return ModelPlan(
            selected_model_id=None,
            runtime="none",
            device="none",
            gpu_layers=0,
            estimated_ram_mb=0,
            estimated_vram_mb=0,
            context_size=desired_context,
            reason_codes=reasons,
            is_viable=False,
        )

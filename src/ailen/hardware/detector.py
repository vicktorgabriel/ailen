"""Hardware detector orchestrating OS adapters and capability evaluation."""

import datetime
import sys

from ailen.domain.enums import DeviceProfile
from ailen.hardware.base import HardwareAdapter
from ailen.hardware.contracts import (
    HardwareCapabilityReport,
    ProfileRecommendation,
)
from ailen.hardware.linux import LinuxHardwareAdapter
from ailen.hardware.tiers import classify_hardware_tier
from ailen.hardware.windows import WindowsHardwareAdapter


class HardwareDetector:
    """Detects system hardware capabilities and derives architectural profile recommendations."""

    def __init__(self, adapter: HardwareAdapter | None = None) -> None:
        if adapter is not None:
            self._adapter = adapter
        elif sys.platform == "win32":
            self._adapter = WindowsHardwareAdapter()
        else:
            self._adapter = LinuxHardwareAdapter()

    @property
    def adapter(self) -> HardwareAdapter:
        return self._adapter

    def detect(self, disk_path: str = "/var/lib/ailen/models") -> HardwareCapabilityReport:
        """Run complete hardware detection and produce structured report."""
        os_name, os_ver, os_distro, os_family = self._adapter.detect_os()
        cpu = self._adapter.detect_cpu()
        ram = self._adapter.detect_ram()
        gpus = self._adapter.detect_gpus()
        disk = self._adapter.detect_disk(disk_path)
        audio_in, audio_out = self._adapter.detect_audio_devices()
        cameras = self._adapter.detect_cameras()
        displays = self._adapter.detect_displays()
        runtime = self._adapter.detect_runtime()

        return HardwareCapabilityReport(
            timestamp_utc=datetime.datetime.now(datetime.UTC).isoformat(),
            os_name=os_name,
            os_version=os_ver,
            os_distribution=os_distro,
            os_family=os_family,
            cpu=cpu,
            ram=ram,
            gpus=gpus,
            disk=disk,
            audio_inputs=audio_in,
            audio_outputs=audio_out,
            cameras=cameras,
            displays=displays,
            runtime=runtime,
        )

    def recommend_profile(self, report: HardwareCapabilityReport) -> ProfileRecommendation:
        """Derive recommended DeviceProfile and local inference capability from report."""
        total_ram_mb = report.ram.total_mb
        avail_ram_mb = report.ram.available_mb
        memory_tier = classify_hardware_tier(total_ram_mb, avail_ram_mb)
        reasons: list[str] = []

        # 0. Check for unmeasured / missing RAM probe
        if total_ram_mb == 0 or avail_ram_mb == 0:
            reasons.append("HARDWARE_RAM_UNKNOWN")
            reasons.append("LOCAL_PLAN_BLOCKED_INSUFFICIENT_EVIDENCE")
            return ProfileRecommendation(
                profile=DeviceProfile.CLOUD,
                local_inference_capable=False,
                recommended_local_budget_mb=0,
                gpu_inference_capable=False,
                preferred_runtime="none",
                reason_codes=reasons,
            )

        # 1. Inspect GPU acceleration
        best_gpu_vram = 0
        has_cuda_gpu = False
        for gpu in report.gpus:
            if gpu.is_dedicated and gpu.vram_available_mb:
                best_gpu_vram = max(best_gpu_vram, gpu.vram_available_mb)
                if gpu.backend == "cuda":
                    has_cuda_gpu = True

        # 2. Derive Profile
        # Tier A: below the minimum 4 GB recycled-device envelope.
        if total_ram_mb < 3500:
            reasons.append("RAM_LIMITED_SATELLITE")
            reasons.append("NO_LOCAL_INFERENCE")
            return ProfileRecommendation(
                profile=DeviceProfile.SATELLITE,
                local_inference_capable=False,
                recommended_local_budget_mb=0,
                gpu_inference_capable=False,
                preferred_runtime="none",
                reason_codes=reasons,
            )

        # Tier B: Constrained nominal 4 GB Tier.
        if total_ram_mb < 6500:
            reasons.append("RAM_4GB_TIER")
            if not report.cpu.has_avx2 and not has_cuda_gpu:
                reasons.append("CPU_NO_AVX2")
                reasons.append("TARGET_HARDWARE_BENCHMARK_REQUIRED")
            reasons.append("LOCAL_TINY_MODEL_CAPABLE")
            budget_mb = memory_tier.model_ram_budget_mb
            local_capable = budget_mb >= 900
            return ProfileRecommendation(
                profile=DeviceProfile.HYBRID,
                local_inference_capable=local_capable,
                recommended_local_budget_mb=budget_mb,
                gpu_inference_capable=has_cuda_gpu,
                preferred_runtime="llama.cpp" if local_capable else "none",
                reason_codes=reasons,
            )

        # Tier C: Standard nominal 8 GB Tier.
        if total_ram_mb < 12500:
            reasons.append("RAM_8GB_TIER")
            gpu_cap = has_cuda_gpu and best_gpu_vram >= 3000
            if gpu_cap:
                reasons.append("GPU_AVAILABLE")
                reasons.append("LOCAL_SMALL_MODEL_CAPABLE")
                budget_mb = min(int(best_gpu_vram * 0.80), 4000)
            else:
                reasons.append("CPU_AVX2_AVAILABLE" if report.cpu.has_avx2 else "CPU_FALLBACK")
                reasons.append("LOCAL_SMALL_MODEL_CAPABLE")
                budget_mb = memory_tier.model_ram_budget_mb

            return ProfileRecommendation(
                profile=DeviceProfile.HYBRID,
                local_inference_capable=True,
                recommended_local_budget_mb=budget_mb,
                gpu_inference_capable=gpu_cap,
                preferred_runtime="llama.cpp",
                reason_codes=reasons,
            )

        # Tier D: Workstation / High-End Tier (>= 16 GB RAM)
        reasons.append("HIGH_RAM_TIER")
        if has_cuda_gpu and best_gpu_vram >= 8000:
            reasons.append(f"VRAM_{best_gpu_vram // 1024}GB")
            reasons.append("LOCAL_MEDIUM_MODEL_CAPABLE")
            reasons.append("LAN_BRAIN_CAPABLE")
            budget_mb = int(best_gpu_vram * 0.80)
            return ProfileRecommendation(
                profile=DeviceProfile.LOCAL,
                local_inference_capable=True,
                recommended_local_budget_mb=budget_mb,
                gpu_inference_capable=True,
                preferred_runtime="llama.cpp",
                reason_codes=reasons,
            )

        reasons.append("CPU_INFERENCE_CAPABLE")
        reasons.append("LOCAL_MEDIUM_MODEL_CAPABLE")
        budget_mb = min(
            memory_tier.model_ram_budget_mb,
            int(avail_ram_mb * 0.60),
        )
        return ProfileRecommendation(
            profile=DeviceProfile.LOCAL,
            local_inference_capable=True,
            recommended_local_budget_mb=budget_mb,
            gpu_inference_capable=False,
            preferred_runtime="llama.cpp",
            reason_codes=reasons,
        )

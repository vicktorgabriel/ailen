"""Canonical hardware -> local-model provisioning decision.

This module plans only. It never downloads weights, installs packages or
activates a model without the caller presenting and accepting the consent
actions contained in the returned plan.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from ailen.domain.enums import DeviceProfile
from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.hardware.tiers import classify_hardware_tier
from ailen.models.catalog import (
    ModelCatalog,
    ModelDescriptor,
    ModelQualificationStatus,
)
from ailen.models.inference_profile import (
    InferenceRecommendation,
    recommend_inference_profile,
)
from ailen.models.planner import ModelPlan, ModelPlanner


def hardware_class_id(report: HardwareCapabilityReport) -> str:
    """Return a stable, non-identifying capability class for benchmark matching."""

    ram_mb = report.ram.total_mb
    if ram_mb < 3500:
        ram_band = "under4gb"
    elif ram_mb < 6500:
        ram_band = "4gb"
    elif ram_mb < 12500:
        ram_band = "8gb"
    elif ram_mb < 24500:
        ram_band = "16gb"
    elif ram_mb < 49100:
        ram_band = "32gb"
    elif ram_mb < 98300:
        ram_band = "64gb"
    else:
        ram_band = "96gb_plus"

    dedicated_vram = max(
        (
            int(gpu.vram_total_mb or 0)
            for gpu in report.gpus
            if gpu.is_dedicated
        ),
        default=0,
    )
    if dedicated_vram <= 0:
        accelerator = "cpu"
    elif dedicated_vram < 5500:
        accelerator = "gpu4gb"
    elif dedicated_vram < 7500:
        accelerator = "gpu6gb"
    elif dedicated_vram < 10000:
        accelerator = "gpu8gb"
    elif dedicated_vram < 14000:
        accelerator = "gpu12gb"
    elif dedicated_vram < 20000:
        accelerator = "gpu16gb"
    elif dedicated_vram < 28000:
        accelerator = "gpu24gb"
    else:
        accelerator = "gpu32gb_plus"
    instruction = "avx2" if report.cpu.has_avx2 is True else "no_avx2"
    architecture = report.cpu.architecture.lower().replace("-", "_") or "unknown"
    return f"{ram_band}-{accelerator}-{architecture}-{instruction}"


@dataclass(frozen=True)
class HardwareModelQualification:
    """Measured model evidence for one relevant hardware capability class."""

    model_id: str
    hardware_class: str
    status: str
    quality_score: float
    ttfa_ms: float
    tokens_per_second: float
    runtime: str
    context_tokens: int
    evidence_reference: str
    execution_device: str = "cpu"
    gpu_layers: int | str = 0
    peak_rss_mb: int | None = None
    peak_vram_mb: int | None = None

    def validate(self) -> None:
        if self.status not in {"candidate", "qualified", "rejected"}:
            raise ValueError("invalid hardware qualification status")
        if not self.model_id or not self.hardware_class or not self.evidence_reference:
            raise ValueError("qualification identity and evidence reference are required")
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be between zero and one")
        if self.ttfa_ms <= 0 or self.tokens_per_second <= 0:
            raise ValueError("qualification requires positive latency and throughput")
        if self.runtime not in {"llama.cpp", "ollama"}:
            raise ValueError("unsupported qualified runtime")
        if self.status == "qualified" and self.context_tokens <= 0:
            raise ValueError("qualified runtime evidence requires measured context_tokens")
        if self.execution_device not in {"cpu", "cuda"}:
            raise ValueError("unsupported qualification execution device")
        if isinstance(self.gpu_layers, bool) or self.gpu_layers not in {0, "all"}:
            raise ValueError("qualification gpu_layers must be 0 or all")
        if self.execution_device == "cpu" and self.gpu_layers != 0:
            raise ValueError("CPU qualification cannot declare GPU layers")
        if self.execution_device == "cuda" and self.gpu_layers != "all":
            raise ValueError(
                "partial GPU offload is not supported by the qualification contract"
            )
        if self.peak_rss_mb is not None and self.peak_rss_mb <= 0:
            raise ValueError("peak_rss_mb must be positive when measured")
        if self.peak_vram_mb is not None and self.peak_vram_mb <= 0:
            raise ValueError("peak_vram_mb must be positive when measured")
        if self.execution_device == "cpu" and self.peak_vram_mb is not None:
            raise ValueError("CPU qualification cannot declare peak VRAM")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HardwareModelQualification:
        gpu_layers_raw = raw.get("gpu_layers", 0)
        gpu_layers: int | str = (
            gpu_layers_raw if isinstance(gpu_layers_raw, (int, str)) else -1
        )
        peak_rss_raw = raw.get("peak_rss_mb")
        peak_vram_raw = raw.get("peak_vram_mb")
        record = cls(
            model_id=str(raw.get("model_id", "")),
            hardware_class=str(raw.get("hardware_class", "")),
            status=str(raw.get("status", "candidate")),
            quality_score=float(raw.get("quality_score", 0.0)),
            ttfa_ms=float(raw.get("ttfa_ms", 0.0)),
            tokens_per_second=float(raw.get("tokens_per_second", 0.0)),
            runtime=str(raw.get("runtime", "")),
            context_tokens=int(raw.get("context_tokens", 0)),
            evidence_reference=str(raw.get("evidence_reference", "")),
            execution_device=str(raw.get("execution_device", "cpu")),
            gpu_layers=gpu_layers,
            peak_rss_mb=(int(peak_rss_raw) if peak_rss_raw is not None else None),
            peak_vram_mb=(int(peak_vram_raw) if peak_vram_raw is not None else None),
        )
        record.validate()
        return record


class HardwareQualificationStore:
    """Read-only evidence indexed by hardware, model and measured runtime."""

    def __init__(
        self,
        records: list[HardwareModelQualification] | None = None,
    ) -> None:
        self._records: dict[tuple[str, str, str], HardwareModelQualification] = {}
        for record in records or []:
            record.validate()
            key = (record.hardware_class, record.model_id, record.runtime)
            if key in self._records:
                raise ValueError(
                    "duplicate hardware/model/runtime qualification: "
                    f"{record.hardware_class}/{record.model_id}/{record.runtime}"
                )
            self._records[key] = record

    def get(
        self,
        hardware_class: str,
        model_id: str,
        runtime: str,
    ) -> HardwareModelQualification | None:
        return self._records.get((hardware_class, model_id, runtime))

    def qualified_for(self, hardware_class: str) -> list[HardwareModelQualification]:
        return [
            record
            for (record_class, _, _), record in self._records.items()
            if record_class == hardware_class and record.status == "qualified"
        ]

    def qualified_for_model(
        self,
        hardware_class: str,
        model_id: str,
    ) -> list[HardwareModelQualification]:
        """Return every independently qualified runtime for one target model."""

        return sorted(
            (
                record
                for (record_class, record_model, _), record in self._records.items()
                if record_class == hardware_class
                and record_model == model_id
                and record.status == "qualified"
            ),
            key=lambda record: record.runtime,
        )

    @classmethod
    def from_directory(cls, directory: Path) -> HardwareQualificationStore:
        """Load bounded JSON evidence records; malformed files fail closed."""

        records: list[HardwareModelQualification] = []
        if not directory.is_dir():
            return cls()
        for path in sorted(directory.glob("*.json")):
            if path.stat().st_size > 256_000:
                raise ValueError(f"qualification file too large: {path.name}")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
                raise ValueError(f"unsupported qualification record: {path.name}")
            record_raw = raw.get("qualification")
            if not isinstance(record_raw, dict):
                raise TypeError(f"missing qualification object: {path.name}")
            records.append(HardwareModelQualification.from_dict(record_raw))
        return cls(records)


@dataclass(frozen=True)
class ProvisioningPlan:
    """Declarative, auditable install proposal for one detected machine."""

    hardware_class: str
    hardware_tier: str
    topology: str
    os_name: str
    cpu_architecture: str
    cpu_physical_cores: int | None
    cpu_logical_cores: int | None
    disk_free_bytes: int
    total_ram_mb: int
    available_ram_mb: int
    dedicated_vram_mb: int
    dedicated_vram_available_mb: int
    cpu_has_avx2: bool | None
    inference_profile: str
    local_enabled: bool
    runtime: str
    runtime_reason: str
    execution_device: str
    primary_model_id: str | None
    fallback_model_id: str | None
    candidate_model_ids: tuple[str, ...]
    context_tokens: int
    gpu_layers: int | str
    reserved_system_ram_mb: int
    estimated_model_ram_mb: int
    estimated_model_vram_mb: int
    download_size_bytes: int
    artifact_url: str
    artifact_sha256: str
    license_name: str
    qualification_status: str
    auto_download_allowed: bool
    required_assets: tuple[str, ...]
    consent_actions: tuple[str, ...]
    alternatives: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProvisioningPlanner:
    """Choose the best measured model inside the complete-system envelope."""

    def __init__(
        self,
        *,
        catalog: ModelCatalog | None = None,
        qualifications: HardwareQualificationStore | None = None,
    ) -> None:
        self.catalog = catalog or ModelCatalog()
        self.qualifications = qualifications or HardwareQualificationStore()

    @staticmethod
    def _evidence_rank(
        variant: tuple[HardwareModelQualification, ModelPlan],
        preferred_runtime: str,
    ) -> tuple[float, float, float, int, bool, int, bool, int, bool, str]:
        """Rank measured runtime evidence without treating support as qualification."""

        evidence, _plan = variant
        return (
            -evidence.quality_score,
            evidence.ttfa_ms,
            -evidence.tokens_per_second,
            -evidence.context_tokens,
            evidence.peak_rss_mb is None,
            evidence.peak_rss_mb or 0,
            evidence.peak_vram_mb is None,
            evidence.peak_vram_mb or 0,
            evidence.runtime != preferred_runtime,
            evidence.runtime,
        )

    def _best_execution_variant(
        self,
        descriptor: ModelDescriptor,
        evidence_records: list[HardwareModelQualification],
        *,
        report: HardwareCapabilityReport,
        device_profile: DeviceProfile,
        recommendation: InferenceRecommendation,
        reasons: list[str],
    ) -> tuple[HardwareModelQualification, ModelPlan] | None:
        """Return the best target-measured runtime/device plan that still fits."""

        supported = descriptor.supported_runtimes or [descriptor.runtime]
        variants: list[tuple[HardwareModelQualification, ModelPlan]] = []
        for evidence in evidence_records:
            if evidence.runtime not in supported:
                reasons.append(
                    f"QUALIFICATION_RUNTIME_MISMATCH_{descriptor.model_id}_{evidence.runtime}"
                )
                continue
            if (
                evidence.peak_rss_mb is not None
                and evidence.peak_rss_mb > recommendation.max_model_ram_mb
            ):
                reasons.append(
                    f"QUALIFICATION_RSS_OUTSIDE_ENVELOPE_{descriptor.model_id}_{evidence.runtime}"
                )
                continue
            if (
                evidence.peak_vram_mb is not None
                and evidence.peak_vram_mb > recommendation.max_model_vram_mb
            ):
                reasons.append(
                    f"QUALIFICATION_VRAM_OUTSIDE_ENVELOPE_{descriptor.model_id}_{evidence.runtime}"
                )
                continue

            qualified_descriptor = replace(
                descriptor,
                context_default=min(
                    descriptor.context_default,
                    evidence.context_tokens,
                ),
                qualification_status=ModelQualificationStatus.QUALIFIED,
                benchmark_status="measured_target",
                quality_rank=max(
                    descriptor.quality_rank,
                    round(evidence.quality_score * 100),
                ),
            )
            execution_plan = ModelPlanner(
                ModelCatalog([qualified_descriptor])
            ).plan(
                report,
                profile=device_profile,
                prefer_gpu=evidence.execution_device == "cuda",
                desired_context=recommendation.recommended_context,
                inference_profile=recommendation.profile,
                require_downloadable=True,
            )
            if (
                not execution_plan.is_viable
                or execution_plan.device != evidence.execution_device
                or execution_plan.gpu_layers != evidence.gpu_layers
            ):
                reasons.append(
                    f"QUALIFICATION_EXECUTION_MISMATCH_{descriptor.model_id}_{evidence.runtime}"
                )
                continue
            execution_plan = replace(execution_plan, runtime=evidence.runtime)
            variants.append((evidence, execution_plan))

        if not variants:
            return None
        return min(
            variants,
            key=lambda variant: self._evidence_rank(
                variant,
                recommendation.preferred_runtime,
            ),
        )

    def plan(
        self,
        report: HardwareCapabilityReport,
        *,
        topology: str = "hybrid",
        manual_model_override: str | None = None,
    ) -> ProvisioningPlan:
        if topology not in {
            "hybrid",
            "local",
            "lan-satellite",
            "gpu-lan-brain",
            "external-only",
        }:
            raise ValueError(f"unsupported provisioning topology: {topology}")

        hardware_class = hardware_class_id(report)
        total_ram = report.ram.total_mb
        available_ram = report.ram.available_mb
        tier = classify_hardware_tier(total_ram, available_ram)
        dedicated_vram = max(
            (
                int(gpu.vram_total_mb or 0)
                for gpu in report.gpus
                if gpu.is_dedicated
            ),
            default=0,
        )
        dedicated_vram_available = max(
            (
                int(gpu.vram_available_mb or 0)
                for gpu in report.gpus
                if gpu.is_dedicated
            ),
            default=0,
        )
        device_profile = (
            DeviceProfile.SATELLITE
            if topology in {"lan-satellite", "external-only"}
            else DeviceProfile.LAN_BRAIN
            if topology == "gpu-lan-brain"
            else DeviceProfile.HYBRID
        )
        recommendation = recommend_inference_profile(
            report,
            device_profile=device_profile,
        )
        reasons = list(recommendation.reason_codes)

        runtime_variants: dict[
            str, tuple[HardwareModelQualification, ModelPlan]
        ] = {}
        qualified_descriptors: list[ModelDescriptor] = []
        for descriptor in self.catalog.list_models():
            variant = self._best_execution_variant(
                descriptor,
                self.qualifications.qualified_for_model(
                    hardware_class,
                    descriptor.model_id,
                ),
                report=report,
                device_profile=device_profile,
                recommendation=recommendation,
                reasons=reasons,
            )
            if variant is None:
                continue
            runtime_variants[descriptor.model_id] = variant
            qualified_descriptor = variant[1].model_descriptor
            assert qualified_descriptor is not None
            qualified_descriptors.append(qualified_descriptor)

        selected_plan = None
        if recommendation.local_allowed and qualified_descriptors:
            selected_plan = ModelPlanner(ModelCatalog(qualified_descriptors)).plan(
                report,
                profile=device_profile,
                desired_context=recommendation.recommended_context,
                inference_profile=recommendation.profile,
                require_downloadable=True,
            )

        candidate_ids: list[str] = []
        if recommendation.local_allowed:
            candidate_plan = ModelPlanner(self.catalog).plan(
                report,
                profile=device_profile,
                desired_context=recommendation.recommended_context,
                inference_profile=recommendation.profile,
                require_downloadable=True,
            )
            if candidate_plan.selected_model_id:
                candidate_ids.append(candidate_plan.selected_model_id)
                candidate_ids.extend(candidate_plan.fallback_model_ids)

        if manual_model_override:
            override_descriptor = self.catalog.get_model(manual_model_override)
            if override_descriptor is None:
                reasons.append("MANUAL_MODEL_OVERRIDE_NOT_IN_CATALOG")
                selected_plan = None
            elif manual_model_override not in runtime_variants:
                reasons.append("MANUAL_MODEL_OVERRIDE_NOT_TARGET_QUALIFIED")
                selected_plan = None
                if manual_model_override not in candidate_ids:
                    candidate_ids.insert(0, manual_model_override)
            else:
                selected_plan = runtime_variants[manual_model_override][1]
                reasons.append("MANUAL_MODEL_OVERRIDE_SELECTED")

        if selected_plan is None or not selected_plan.is_viable:
            reasons.extend(["NO_TARGET_QUALIFIED_MODEL", "CATALOG_LIMITED_TO_CANDIDATES"])
            return ProvisioningPlan(
                hardware_class=hardware_class,
                hardware_tier=tier.tier_id,
                topology=topology,
                os_name=report.os_name,
                cpu_architecture=report.cpu.architecture,
                cpu_physical_cores=report.cpu.physical_cores,
                cpu_logical_cores=report.cpu.logical_cores,
                disk_free_bytes=report.disk.free_bytes if report.disk else 0,
                total_ram_mb=total_ram,
                available_ram_mb=available_ram,
                dedicated_vram_mb=dedicated_vram,
                dedicated_vram_available_mb=dedicated_vram_available,
                cpu_has_avx2=report.cpu.has_avx2,
                inference_profile=recommendation.profile.value,
                local_enabled=False,
                runtime="none",
                runtime_reason="No model is qualified for this hardware class.",
                execution_device="none",
                primary_model_id=None,
                fallback_model_id=None,
                candidate_model_ids=tuple(dict.fromkeys(candidate_ids)),
                context_tokens=recommendation.recommended_context,
                gpu_layers=0,
                reserved_system_ram_mb=tier.minimum_free_ram_mb,
                estimated_model_ram_mb=0,
                estimated_model_vram_mb=0,
                download_size_bytes=0,
                artifact_url="",
                artifact_sha256="",
                license_name="",
                qualification_status="candidate",
                auto_download_allowed=False,
                required_assets=("stt", "tts", "facepack"),
                consent_actions=(),
                alternatives=("lan_brain", "remote_provider", "core_degraded"),
                reason_codes=tuple(dict.fromkeys(reasons)),
            )

        selected_descriptor = selected_plan.model_descriptor
        assert selected_descriptor is not None
        evidence, execution_plan = runtime_variants[selected_descriptor.model_id]
        runtime = evidence.runtime
        verified_artifact = bool(
            selected_descriptor.downloadable
            and selected_descriptor.source_url.startswith("https://")
            and len(selected_descriptor.sha256) == 64
            and selected_descriptor.license_name.strip()
        )
        fallback_id = (
            selected_plan.fallback_model_ids[0]
            if selected_plan.fallback_model_ids
            else None
        )
        reasons.extend(selected_plan.reason_codes)
        reasons.extend(execution_plan.reason_codes)
        reasons.append("TARGET_HARDWARE_QUALIFICATION_MATCHED")
        runtime_token = runtime.upper().replace(".", "_").replace("-", "_")
        reasons.append(f"RUNTIME_QUALIFICATION_{runtime_token}_SELECTED")
        if runtime != recommendation.preferred_runtime:
            preferred_token = (
                recommendation.preferred_runtime.upper()
                .replace(".", "_")
                .replace("-", "_")
            )
            reasons.append(
                f"PREFERRED_RUNTIME_{preferred_token}_OVERRIDDEN_BY_QUALIFIED_EVIDENCE"
            )
        execution_reason = (
            "measured CPU execution with zero GPU layers"
            if evidence.execution_device == "cpu"
            else "measured CUDA execution with all layers offloaded"
        )
        return ProvisioningPlan(
            hardware_class=hardware_class,
            hardware_tier=tier.tier_id,
            topology=topology,
            os_name=report.os_name,
            cpu_architecture=report.cpu.architecture,
            cpu_physical_cores=report.cpu.physical_cores,
            cpu_logical_cores=report.cpu.logical_cores,
            disk_free_bytes=report.disk.free_bytes if report.disk else 0,
            total_ram_mb=total_ram,
            available_ram_mb=available_ram,
            dedicated_vram_mb=dedicated_vram,
            dedicated_vram_available_mb=dedicated_vram_available,
            cpu_has_avx2=report.cpu.has_avx2,
            inference_profile=recommendation.profile.value,
            local_enabled=True,
            runtime=runtime,
            runtime_reason=(
                f"{runtime} was selected from target-hardware/runtime evidence; "
                f"{execution_reason}."
            ),
            execution_device=evidence.execution_device,
            primary_model_id=selected_descriptor.model_id,
            fallback_model_id=fallback_id,
            candidate_model_ids=tuple(dict.fromkeys(candidate_ids)),
            context_tokens=execution_plan.context_size,
            gpu_layers=evidence.gpu_layers,
            reserved_system_ram_mb=tier.minimum_free_ram_mb,
            estimated_model_ram_mb=max(
                execution_plan.estimated_ram_mb,
                evidence.peak_rss_mb or 0,
            ),
            estimated_model_vram_mb=max(
                execution_plan.estimated_vram_mb,
                evidence.peak_vram_mb or 0,
            ),
            download_size_bytes=selected_descriptor.disk_size_bytes,
            artifact_url=selected_descriptor.source_url,
            artifact_sha256=selected_descriptor.sha256,
            license_name=selected_descriptor.license_name,
            qualification_status="qualified",
            auto_download_allowed=verified_artifact,
            required_assets=("stt", "tts", "facepack"),
            consent_actions=(
                f"install_runtime:{runtime}",
                f"download_model:{selected_descriptor.model_id}",
                f"activate_model:{selected_descriptor.model_id}",
            ),
            alternatives=("lan_brain", "remote_provider", "core_degraded"),
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

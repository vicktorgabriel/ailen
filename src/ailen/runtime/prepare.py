"""Consent-gated local AI preparation driven by the canonical provisioning plan."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ailen.core.config import AILENConfig
from ailen.domain.enums import DeviceProfile
from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.hardware.detector import HardwareDetector
from ailen.models.downloader import ModelDownloader
from ailen.models.store import ModelStore
from ailen.provisioning.activation import (
    LocalAiSelectionError,
    LocalAiSelectionStore,
)
from ailen.provisioning.planner import ProvisioningPlan, ProvisioningPlanner
from ailen.runtime.contracts import ExternalRuntimeDescriptor
from ailen.runtime.managed import ManagedLlamaRuntime
from ailen.runtime.manager import LocalRuntimeManager

logger = logging.getLogger(__name__)


@dataclass
class PrepareAiReport:
    """Diagnostic and preparation status for local AI execution."""

    hardware: HardwareCapabilityReport
    plan: ProvisioningPlan
    model_installed: bool
    model_verified: bool
    model_path: str | None
    runtimes: list[ExternalRuntimeDescriptor]
    managed_runtime_verified: bool = False
    selection_activated: bool = False
    selection_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hardware": self.hardware.to_dict(),
            "plan": self.plan.to_dict(),
            "model_installed": self.model_installed,
            "model_verified": self.model_verified,
            "model_path": self.model_path,
            "runtimes": [
                {
                    "type": runtime.runtime_type.value,
                    "endpoint": runtime.endpoint,
                    "status": runtime.status.value,
                    "detected": runtime.is_detected,
                }
                for runtime in self.runtimes
            ],
            "managed_runtime_verified": self.managed_runtime_verified,
            "selection_activated": self.selection_activated,
            "selection_path": self.selection_path,
        }


class LabAiPreparer:
    """Inspect and optionally execute an already-qualified, consented plan."""

    def __init__(
        self,
        config: AILENConfig,
        store: ModelStore | None = None,
        runtime_manager: LocalRuntimeManager | None = None,
        provisioning_planner: ProvisioningPlanner | None = None,
        selection_store: LocalAiSelectionStore | None = None,
    ) -> None:
        self.config = config
        self.store = store or ModelStore()
        self.runtime_mgr = runtime_manager or LocalRuntimeManager()
        self.provisioning_planner = provisioning_planner or ProvisioningPlanner()
        self.selection_store = selection_store or LocalAiSelectionStore(
            Path(config.node.data_dir) / "provisioning" / "local-ai-selection.json"
        )

    @staticmethod
    def _topology(profile: DeviceProfile) -> str:
        return {
            DeviceProfile.SATELLITE: "lan-satellite",
            DeviceProfile.CLOUD: "external-only",
            DeviceProfile.LAN_BRAIN: "gpu-lan-brain",
            DeviceProfile.LOCAL: "local",
        }.get(profile, "hybrid")

    def run(
        self,
        auto_download: bool = False,
        start_runtime: bool = False,
        activate_selection: bool = False,
    ) -> tuple[PrepareAiReport, int]:
        """Plan first; candidates can never cross the download gate."""

        hardware = HardwareDetector().detect(str(self.store.base_dir))
        plan = self.provisioning_planner.plan(
            hardware,
            topology=self._topology(self.config.node.profile),
            manual_model_override=(
                self.config.ai.local.model
                if self.config.ai.local.enabled and self.config.ai.local.model
                else None
            ),
        )
        runtimes = self.runtime_mgr.detect_available_runtimes()
        model_id = plan.primary_model_id
        descriptor = (
            self.provisioning_planner.catalog.get_model(model_id)
            if model_id is not None
            else None
        )
        model_installed = model_id is not None and self.store.exists(model_id)
        model_verified = False
        if model_installed and model_id is not None and descriptor is not None:
            model_verified = self.store.verify(model_id, descriptor.sha256)
        model_path = (
            str(self.store.get_model_path(model_id))
            if model_verified and model_id is not None
            else None
        )

        print("==================================================================")
        print(" AILEN LAB AI PREPARATION — hardware-driven, consent gated")
        print("==================================================================")
        print(f"Hardware class : {plan.hardware_class}")
        print(f"Tier/topology  : {plan.hardware_tier} / {plan.topology}")
        print(f"Runtime        : {plan.runtime}")
        print(
            f"Execution      : {plan.execution_device} "
            f"(GPU layers: {plan.gpu_layers})"
        )
        print(f"Primary model  : {plan.primary_model_id or 'none target-qualified'}")
        print(f"Candidates     : {list(plan.candidate_model_ids)}")
        print(f"Auto-download  : {'eligible after consent' if plan.auto_download_allowed else 'BLOCKED'}")
        print(f"Reasons        : {', '.join(plan.reason_codes)}")
        print("------------------------------------------------------------------")
        for runtime in runtimes:
            print(
                f"  - {runtime.runtime_type.value:<18} : "
                f"{runtime.endpoint:<28} [{runtime.status.value}]"
            )
        print("==================================================================")

        if auto_download and not plan.auto_download_allowed:
            print(
                "No se descargó ningún modelo: falta calificación para esta clase "
                "de hardware o identidad verificable del artefacto."
            )
        elif (
            auto_download
            and descriptor is not None
            and model_id is not None
            and not model_installed
        ):
            try:
                downloaded_path = ModelDownloader(store=self.store).download(descriptor)
            except Exception as exc:  # noqa: BLE001
                print(f"Download failed: {exc}")
                return (
                    PrepareAiReport(
                        hardware,
                        plan,
                        False,
                        False,
                        None,
                        runtimes,
                    ),
                    1,
                )
            model_installed = True
            model_verified = True
            model_path = str(downloaded_path)

        managed_started = False
        if start_runtime and model_verified and model_path and model_id:
            if plan.runtime != "llama.cpp":
                print(
                    f"El verificador administrado actual sólo inicia llama.cpp; "
                    f"el plan eligió {plan.runtime}."
                )
            else:
                managed_runtime = ManagedLlamaRuntime(runtime_manager=self.runtime_mgr)
                managed_started = managed_runtime.start(
                    model_path=Path(model_path),
                    port=8080,
                    context_size=plan.context_tokens,
                    gpu_layers=plan.gpu_layers,
                    model_alias=model_id,
                )
                if managed_started:
                    managed_runtime.stop()

        selection_activated = False
        if activate_selection:
            if not model_verified:
                print(
                    "No se activó la selección: el artefacto exacto todavía no "
                    "está instalado y verificado."
                )
                return (
                    PrepareAiReport(
                        hardware=hardware,
                        plan=plan,
                        model_installed=model_installed,
                        model_verified=model_verified,
                        model_path=model_path,
                        runtimes=runtimes,
                        managed_runtime_verified=managed_started,
                    ),
                    1,
                )
            try:
                self.selection_store.activate(
                    plan,
                    catalog=self.provisioning_planner.catalog,
                    model_store=self.store,
                )
            except (LocalAiSelectionError, OSError) as exc:
                print(f"No se activó la selección local: {exc}")
                return (
                    PrepareAiReport(
                        hardware=hardware,
                        plan=plan,
                        model_installed=model_installed,
                        model_verified=model_verified,
                        model_path=model_path,
                        runtimes=runtimes,
                        managed_runtime_verified=managed_started,
                    ),
                    1,
                )
            selection_activated = True
            print(
                "Selección local activada para este hardware. "
                "AILEN mantendrá ese modelo/runtime estable hasta un nuevo provisioning."
            )

        return (
            PrepareAiReport(
                hardware=hardware,
                plan=plan,
                model_installed=model_installed,
                model_verified=model_verified,
                model_path=model_path,
                runtimes=runtimes,
                managed_runtime_verified=managed_started,
                selection_activated=selection_activated,
                selection_path=(
                    str(self.selection_store.path) if selection_activated else None
                ),
            ),
            0,
        )

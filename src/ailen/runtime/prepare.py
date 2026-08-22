"""Step-by-step AI preparation and verification workflow for Lab Mode."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ailen.core.config import AILENConfig
from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.hardware.detector import HardwareDetector
from ailen.models.catalog import ModelCatalog, ModelPurpose
from ailen.models.downloader import ModelDownloader
from ailen.models.planner import ModelPlan, ModelPlanner
from ailen.models.store import ModelStore
from ailen.runtime.contracts import ExternalRuntimeDescriptor
from ailen.runtime.managed import ManagedLlamaRuntime
from ailen.runtime.manager import LocalRuntimeManager

logger = logging.getLogger(__name__)


@dataclass
class PrepareAiReport:
    """Diagnostic and preparation status for local AI execution."""

    hardware: HardwareCapabilityReport
    plan: ModelPlan
    model_installed: bool
    model_verified: bool
    model_path: str | None
    runtimes: list[ExternalRuntimeDescriptor]
    managed_runtime_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "hardware": self.hardware.to_dict(),
            "plan": self.plan.to_dict(),
            "model_installed": self.model_installed,
            "model_verified": self.model_verified,
            "model_path": self.model_path,
            "runtimes": [
                {
                    "type": r.runtime_type.value,
                    "endpoint": r.endpoint,
                    "status": r.status.value,
                    "detected": r.is_detected,
                }
                for r in self.runtimes
            ],
            "managed_runtime_verified": self.managed_runtime_verified,
        }


class LabAiPreparer:
    """Executes non-invasive AI capability inspection, optional download, and runtime startup."""

    def __init__(
        self,
        config: AILENConfig,
        store: ModelStore | None = None,
        runtime_manager: LocalRuntimeManager | None = None,
    ) -> None:
        self.config = config
        self.store = store or ModelStore()
        self.runtime_mgr = runtime_manager or LocalRuntimeManager()

    def run(
        self,
        auto_download: bool = False,
        start_runtime: bool = False,
        purpose: ModelPurpose = ModelPurpose.BALANCED,
    ) -> tuple[PrepareAiReport, int]:
        """Run inspection and optional preparation steps. Returns (report, exit_code)."""
        detector = HardwareDetector()
        report = detector.detect(str(self.store.base_dir))
        rec = detector.recommend_profile(report)

        catalog = ModelCatalog()
        planner = ModelPlanner(catalog=catalog)
        plan = planner.plan(report, profile=rec.profile, purpose=purpose)

        runtimes = self.runtime_mgr.detect_available_runtimes()

        model_id = plan.selected_model_id
        model_installed = False
        model_verified = False
        model_path_str: str | None = None

        if model_id:
            model_installed = self.store.exists(model_id)
            if model_installed and plan.model_descriptor:
                model_verified = self.store.verify(model_id, plan.model_descriptor.sha256)
                model_path_str = str(self.store.get_model_path(model_id))

        print("==================================================================")
        print("                     AILEN LAB AI PREPARATION                     ")
        print("==================================================================")
        print(f"Hardware Profile : {rec.profile.value}")
        print(f"Memory Usable    : {report.ram.available_mb} MB available")
        if report.gpus:
            print(f"GPU Detected     : {report.gpus[0].model} ({report.gpus[0].vram_available_mb or report.gpus[0].vram_total_mb} MB VRAM)")
        print("------------------------------------------------------------------")
        if plan.is_viable and plan.model_descriptor:
            desc = plan.model_descriptor
            print(f"Recommended Model: {desc.model_id} ({desc.display_name})")
            print(f"Parameter Class  : {desc.parameter_class.upper()} | Quantization: {desc.quantization}")
            print(f"Disk Required    : {desc.disk_size_bytes // (1024 * 1024)} MB")
            print(f"Destination Path : {self.store.get_model_path(desc.model_id)}")
            print(f"Artifact Exists  : {'YES' if model_installed else 'NO'}")
            print(f"SHA-256 Verified : {'PASS' if model_verified else ('FAIL' if model_installed else 'N/A')}")
        else:
            print("Recommended Model: NO VIABLE LOCAL MODEL (Remote / Rule routing only)")
            print(f"Reasons          : {', '.join(plan.reason_codes)}")
        print("------------------------------------------------------------------")
        print("DETECTED RUNTIMES:")
        for r in runtimes:
            print(f"  - {r.runtime_type.value:<18} : {r.endpoint:<28} [{r.status.value}]")
        print("==================================================================")

        # 1. Download if requested and missing
        if auto_download and plan.is_viable and plan.model_descriptor and not model_installed:
            if not plan.model_descriptor.downloadable:
                print(f"Error: Model '{plan.model_descriptor.model_id}' is not marked as downloadable.")
                return PrepareAiReport(report, plan, False, False, None, runtimes), 1

            print(f"Downloading model '{plan.model_descriptor.model_id}'...")
            downloader = ModelDownloader(store=self.store)
            try:
                def progress(done: int, total: int) -> None:
                    pct = int(done / total * 100) if total > 0 else 0
                    print(f"\rProgress: {done // (1024*1024)} MB / {total // (1024*1024)} MB ({pct}%)", end="", flush=True)

                downloaded_path = downloader.download(plan.model_descriptor, progress_callback=progress)
                print(f"\nSuccessfully downloaded to {downloaded_path}")
                model_installed = True
                model_verified = True
                model_path_str = str(downloaded_path)
            except Exception as exc:  # noqa: BLE001
                print(f"\nDownload failed: {exc}")
                return PrepareAiReport(report, plan, False, False, None, runtimes), 1

        # 2. Start managed runtime if requested
        managed_started = False
        if start_runtime and model_installed and model_verified and model_path_str:
            print("Starting AILEN-owned llama.cpp runtime...")
            managed_rt = ManagedLlamaRuntime(runtime_manager=self.runtime_mgr)
            success = managed_rt.start(
                model_path=Path(model_path_str),
                port=8080,
                context_size=plan.context_size,
                gpu_layers=plan.gpu_layers,
                model_alias=plan.selected_model_id,
            )
            if success:
                print(f"Managed runtime health check passed at {managed_rt.endpoint} (PID {managed_rt.pid}).")
                print("Stopping temporary preparation runtime; `ailen lab start` owns the live-session process.")
                managed_started = True
                managed_rt.stop()
            else:
                print("Failed to start a healthy managed runtime.")

        report_obj = PrepareAiReport(
            hardware=report,
            plan=plan,
            model_installed=model_installed,
            model_verified=model_verified,
            model_path=model_path_str,
            runtimes=runtimes,
            managed_runtime_verified=managed_started,
        )

        return report_obj, 0

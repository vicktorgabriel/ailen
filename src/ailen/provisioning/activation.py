"""Stable, evidence-bound local model selection produced by provisioning.

The installation planner may evaluate many candidates, but the conversational
runtime consumes one immutable selection.  This module persists that selection
only after the exact artifact has been verified.  It never downloads weights,
starts a runtime, or changes the active product configuration by itself.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.models.catalog import (
    ModelCatalog,
    ModelQualificationStatus,
)
from ailen.models.planner import ModelPlan
from ailen.models.store import ModelStore
from ailen.provisioning.planner import ProvisioningPlan, hardware_class_id

_SCHEMA_VERSION = 1
_MAX_SELECTION_BYTES = 16_384
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUNTIMES = frozenset({"llama.cpp", "ollama"})
_DEVICES = frozenset({"cpu", "cuda"})


class LocalAiSelectionError(ValueError):
    """The activated selection is corrupt, stale, or unsupported."""


@dataclass(frozen=True)
class LocalAiSelection:
    """One exact hardware/model/runtime decision stable across a session."""

    schema_version: int
    hardware_class: str
    runtime: str
    model_id: str
    fallback_model_id: str | None
    context_tokens: int
    execution_device: str
    gpu_layers: int | str
    estimated_model_ram_mb: int
    estimated_model_vram_mb: int
    artifact_sha256: str
    qualification_status: str

    def validate(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise LocalAiSelectionError("unsupported local AI selection schema")
        if not self.hardware_class or len(self.hardware_class) > 256:
            raise LocalAiSelectionError("invalid local AI hardware class")
        if _MODEL_ID_RE.fullmatch(self.model_id) is None:
            raise LocalAiSelectionError("invalid local AI model ID")
        if self.fallback_model_id is not None and _MODEL_ID_RE.fullmatch(
            self.fallback_model_id
        ) is None:
            raise LocalAiSelectionError("invalid local AI fallback model ID")
        if self.runtime not in _RUNTIMES:
            raise LocalAiSelectionError("invalid local AI runtime")
        if self.execution_device not in _DEVICES:
            raise LocalAiSelectionError("invalid local AI execution device")
        if isinstance(self.gpu_layers, bool) or self.gpu_layers not in {0, "all"}:
            raise LocalAiSelectionError("invalid local AI GPU layer plan")
        if self.execution_device == "cpu" and self.gpu_layers != 0:
            raise LocalAiSelectionError("CPU selection cannot declare GPU offload")
        if self.execution_device == "cuda" and self.gpu_layers != "all":
            raise LocalAiSelectionError("partial GPU offload is not activated")
        if not 512 <= self.context_tokens <= 32768:
            raise LocalAiSelectionError("invalid local AI context")
        if self.estimated_model_ram_mb <= 0 or self.estimated_model_vram_mb < 0:
            raise LocalAiSelectionError("invalid local AI memory estimate")
        if _SHA256_RE.fullmatch(self.artifact_sha256) is None:
            raise LocalAiSelectionError("invalid local AI artifact digest")
        if self.qualification_status != "qualified":
            raise LocalAiSelectionError("local AI selection is not qualified")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LocalAiSelection:
        expected = {
            "schema_version",
            "hardware_class",
            "runtime",
            "model_id",
            "fallback_model_id",
            "context_tokens",
            "execution_device",
            "gpu_layers",
            "estimated_model_ram_mb",
            "estimated_model_vram_mb",
            "artifact_sha256",
            "qualification_status",
        }
        if set(raw) != expected:
            raise LocalAiSelectionError("local AI selection fields are invalid")
        integer_fields = (
            "schema_version",
            "context_tokens",
            "estimated_model_ram_mb",
            "estimated_model_vram_mb",
        )
        if any(
            isinstance(raw[field], bool) or not isinstance(raw[field], int)
            for field in integer_fields
        ):
            raise LocalAiSelectionError("local AI selection integer fields are invalid")
        string_fields = (
            "hardware_class",
            "runtime",
            "model_id",
            "execution_device",
            "artifact_sha256",
            "qualification_status",
        )
        if any(not isinstance(raw[field], str) for field in string_fields):
            raise LocalAiSelectionError("local AI selection string fields are invalid")
        fallback_raw = raw["fallback_model_id"]
        if fallback_raw is not None and not isinstance(fallback_raw, str):
            raise LocalAiSelectionError("local AI fallback model ID is invalid")
        selection = cls(
            schema_version=int(raw["schema_version"]),
            hardware_class=str(raw["hardware_class"]),
            runtime=str(raw["runtime"]),
            model_id=str(raw["model_id"]),
            fallback_model_id=(
                str(fallback_raw) if fallback_raw is not None else None
            ),
            context_tokens=int(raw["context_tokens"]),
            execution_device=str(raw["execution_device"]),
            gpu_layers=raw["gpu_layers"],
            estimated_model_ram_mb=int(raw["estimated_model_ram_mb"]),
            estimated_model_vram_mb=int(raw["estimated_model_vram_mb"]),
            artifact_sha256=str(raw["artifact_sha256"]).lower(),
            qualification_status=str(raw["qualification_status"]),
        )
        selection.validate()
        return selection

    def to_model_plan(self, catalog: ModelCatalog) -> ModelPlan:
        """Project the persisted decision into the existing runtime contract."""

        self.validate()
        descriptor = catalog.get_model(self.model_id)
        if descriptor is None:
            raise LocalAiSelectionError("activated model is absent from the catalog")
        if descriptor.sha256.lower() != self.artifact_sha256:
            raise LocalAiSelectionError("activated model artifact identity changed")
        if self.runtime not in (descriptor.supported_runtimes or [descriptor.runtime]):
            raise LocalAiSelectionError("activated runtime is unsupported by the model")
        if self.context_tokens > descriptor.context_default:
            raise LocalAiSelectionError("activated context exceeds the current descriptor")

        qualified_descriptor = replace(
            descriptor,
            qualification_status=ModelQualificationStatus.QUALIFIED,
            benchmark_status="activated_target_selection",
        )
        return ModelPlan(
            selected_model_id=self.model_id,
            runtime=self.runtime,
            fallback_model_ids=(
                [self.fallback_model_id] if self.fallback_model_id else []
            ),
            device=self.execution_device,
            gpu_layers=self.gpu_layers,
            estimated_ram_mb=self.estimated_model_ram_mb,
            estimated_vram_mb=self.estimated_model_vram_mb,
            context_size=self.context_tokens,
            reason_codes=[
                "ACTIVATED_TARGET_HARDWARE_SELECTION",
                f"ACTIVATED_RUNTIME_{self.runtime.upper().replace('.', '_')}",
            ],
            is_viable=True,
            model_descriptor=qualified_descriptor,
        )


class LocalAiSelectionStore:
    """Atomic storage for the one local model selected by provisioning."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def selection_from_plan(plan: ProvisioningPlan) -> LocalAiSelection:
        if (
            not plan.local_enabled
            or plan.qualification_status != "qualified"
            or not plan.auto_download_allowed
            or not plan.primary_model_id
        ):
            raise LocalAiSelectionError(
                "only a verified target-qualified provisioning plan can be activated"
            )
        selection = LocalAiSelection(
            schema_version=_SCHEMA_VERSION,
            hardware_class=plan.hardware_class,
            runtime=plan.runtime,
            model_id=plan.primary_model_id,
            fallback_model_id=plan.fallback_model_id,
            context_tokens=plan.context_tokens,
            execution_device=plan.execution_device,
            gpu_layers=plan.gpu_layers,
            estimated_model_ram_mb=plan.estimated_model_ram_mb,
            estimated_model_vram_mb=plan.estimated_model_vram_mb,
            artifact_sha256=plan.artifact_sha256.lower(),
            qualification_status=plan.qualification_status,
        )
        selection.validate()
        return selection

    @staticmethod
    def _validate_catalog_and_artifact(
        selection: LocalAiSelection,
        *,
        catalog: ModelCatalog,
        model_store: ModelStore,
    ) -> None:
        selection.to_model_plan(catalog)
        descriptor = catalog.get_model(selection.model_id)
        assert descriptor is not None
        artifact_path = model_store.base_dir / f"{selection.model_id}.gguf"
        try:
            artifact_stat = artifact_path.lstat()
        except (OSError, ValueError) as exc:
            raise LocalAiSelectionError("local AI artifact is unavailable") from exc
        if not stat.S_ISREG(artifact_stat.st_mode):
            raise LocalAiSelectionError("local AI artifact path is unsafe")
        if artifact_stat.st_size != descriptor.disk_size_bytes:
            raise LocalAiSelectionError("local AI artifact size changed")
        if not model_store.verify(selection.model_id, selection.artifact_sha256):
            raise LocalAiSelectionError("local AI artifact verification failed")

    def activate(
        self,
        plan: ProvisioningPlan,
        *,
        catalog: ModelCatalog,
        model_store: ModelStore,
    ) -> LocalAiSelection:
        """Persist a consented selection after re-verifying the exact artifact."""

        selection = self.selection_from_plan(plan)
        self._validate_catalog_and_artifact(
            selection,
            catalog=catalog,
            model_store=model_store,
        )
        payload = json.dumps(
            asdict(selection),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > _MAX_SELECTION_BYTES:
            raise LocalAiSelectionError("local AI selection is too large")

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            stream = os.fdopen(descriptor, "wb", closefd=True)
            descriptor = -1
            with stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            if os.name != "nt":
                directory_fd = os.open(
                    self.path.parent,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
        return selection

    def load(
        self,
        report: HardwareCapabilityReport,
        *,
        catalog: ModelCatalog,
        model_store: ModelStore,
    ) -> LocalAiSelection | None:
        """Load and verify a selection for the currently detected hardware."""

        try:
            file_stat = self.path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LocalAiSelectionError("local AI selection is unavailable") from exc
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size <= 0
            or file_stat.st_size > _MAX_SELECTION_BYTES
            or (os.name != "nt" and stat.S_IMODE(file_stat.st_mode) != 0o600)
        ):
            raise LocalAiSelectionError("local AI selection file is unsafe")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalAiSelectionError("local AI selection is corrupt") from exc
        if not isinstance(raw, dict):
            raise LocalAiSelectionError("local AI selection root is invalid")
        selection = LocalAiSelection.from_dict(raw)
        if selection.hardware_class != hardware_class_id(report):
            raise LocalAiSelectionError(
                "local AI selection hardware class no longer matches"
            )
        self._validate_catalog_and_artifact(
            selection,
            catalog=catalog,
            model_store=model_store,
        )
        return selection

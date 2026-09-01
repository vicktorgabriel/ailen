"""Hardware-driven, consent-gated provisioning contracts."""

from ailen.provisioning.activation import (
    LocalAiSelection,
    LocalAiSelectionError,
    LocalAiSelectionStore,
)
from ailen.provisioning.planner import (
    HardwareModelQualification,
    HardwareQualificationStore,
    ProvisioningPlan,
    ProvisioningPlanner,
    hardware_class_id,
)

__all__ = [
    "HardwareModelQualification",
    "HardwareQualificationStore",
    "LocalAiSelection",
    "LocalAiSelectionError",
    "LocalAiSelectionStore",
    "ProvisioningPlan",
    "ProvisioningPlanner",
    "hardware_class_id",
]

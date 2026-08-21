"""Hardware subsystem providing multi-platform capability detection."""

from ailen.hardware.base import HardwareAdapter
from ailen.hardware.contracts import (
    AudioDeviceReport,
    CameraDeviceReport,
    CpuInfo,
    DiskInfo,
    DisplayDeviceReport,
    GpuInfo,
    HardwareCapabilityReport,
    OsFamily,
    ProfileRecommendation,
    RamInfo,
    RuntimeInfo,
)
from ailen.hardware.detector import HardwareDetector
from ailen.hardware.fake import FakeHardwareAdapter
from ailen.hardware.linux import LinuxHardwareAdapter
from ailen.hardware.windows import WindowsHardwareAdapter

__all__ = [
    "AudioDeviceReport",
    "CameraDeviceReport",
    "CpuInfo",
    "DiskInfo",
    "DisplayDeviceReport",
    "FakeHardwareAdapter",
    "GpuInfo",
    "HardwareAdapter",
    "HardwareCapabilityReport",
    "HardwareDetector",
    "LinuxHardwareAdapter",
    "OsFamily",
    "ProfileRecommendation",
    "RamInfo",
    "RuntimeInfo",
    "WindowsHardwareAdapter",
]

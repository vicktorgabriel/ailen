"""Abstract base hardware adapter interface."""

from abc import ABC, abstractmethod

from ailen.hardware.contracts import (
    AudioDeviceReport,
    CameraDeviceReport,
    CpuInfo,
    DiskInfo,
    DisplayDeviceReport,
    GpuInfo,
    OsFamily,
    RamInfo,
    RuntimeInfo,
)


class HardwareAdapter(ABC):
    """Abstract interface for operating-system specific hardware inspectors."""

    @abstractmethod
    def detect_os(self) -> tuple[str, str, str, OsFamily]:
        """Detect operating system name, version, distribution, and OsFamily."""
        raise NotImplementedError

    @abstractmethod
    def detect_cpu(self) -> CpuInfo:
        """Detect CPU model, architecture, core counts, and instruction flags."""
        raise NotImplementedError

    @abstractmethod
    def detect_ram(self) -> RamInfo:
        """Detect system memory total and available bytes."""
        raise NotImplementedError

    @abstractmethod
    def detect_gpus(self) -> list[GpuInfo]:
        """Detect graphics processing units, dedicated status, and VRAM."""
        raise NotImplementedError

    @abstractmethod
    def detect_disk(self, path: str) -> DiskInfo | None:
        """Measure disk total and available bytes at the target filesystem path."""
        raise NotImplementedError

    @abstractmethod
    def detect_audio_devices(self) -> tuple[list[AudioDeviceReport], list[AudioDeviceReport]]:
        """Detect real input (capture) and output (playback) audio devices."""
        raise NotImplementedError

    @abstractmethod
    def detect_cameras(self) -> list[CameraDeviceReport]:
        """Detect real video capture camera devices."""
        raise NotImplementedError

    @abstractmethod
    def detect_displays(self) -> list[DisplayDeviceReport]:
        """Detect real connected display outputs and resolutions."""
        raise NotImplementedError

    @abstractmethod
    def detect_runtime(self) -> RuntimeInfo:
        """Inspect current Python executable runtime and environment."""
        raise NotImplementedError

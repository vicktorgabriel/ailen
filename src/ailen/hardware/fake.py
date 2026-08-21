"""Fake hardware adapter for deterministic and offline unit testing."""

from ailen.hardware.base import HardwareAdapter
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


class FakeHardwareAdapter(HardwareAdapter):
    """Configurable test adapter providing fully deterministic hardware configurations."""

    def __init__(
        self,
        os_info: tuple[str, str, str, OsFamily] | None = None,
        cpu: CpuInfo | None = None,
        ram: RamInfo | None = None,
        gpus: list[GpuInfo] | None = None,
        disk: DiskInfo | None = None,
        audio: tuple[list[AudioDeviceReport], list[AudioDeviceReport]] | None = None,
        cameras: list[CameraDeviceReport] | None = None,
        displays: list[DisplayDeviceReport] | None = None,
        runtime: RuntimeInfo | None = None,
    ) -> None:
        self._os_info = os_info or ("Linux", "6.6.0", "Debian GNU/Linux 13 (trixie)", OsFamily.LINUX)
        self._cpu = cpu or CpuInfo(
            model="Fake x86_64 CPU",
            architecture="x86_64",
            physical_cores=4,
            logical_cores=8,
            flags=["avx", "avx2", "fma", "sse4_1", "sse4_2"],
            has_avx=True,
            has_avx2=True,
            has_fma=True,
            has_sse4_1=True,
            has_sse4_2=True,
            has_neon=False,
        )
        self._ram = ram or RamInfo(total_bytes=8 * 1024 * 1024 * 1024, available_bytes=6 * 1024 * 1024 * 1024)
        self._gpus = gpus if gpus is not None else []
        self._disk = disk or DiskInfo(path="/var/lib/ailen/models", total_bytes=100 * 1024 * 1024 * 1024, free_bytes=60 * 1024 * 1024 * 1024)
        self._audio = audio or (
            [AudioDeviceReport(id="hw:0,0", name="Fake Mic", is_input=True, is_output=False, is_default=True)],
            [AudioDeviceReport(id="hw:0,0", name="Fake Speakers", is_input=False, is_output=True, is_default=True)],
        )
        self._cameras = cameras if cameras is not None else [CameraDeviceReport(device_path="/dev/video0", index=0, name="Fake Webcam", is_available=True)]
        self._displays = displays if displays is not None else [DisplayDeviceReport(name="HDMI-1", width=1920, height=1080, is_primary=True)]
        self._runtime = runtime or RuntimeInfo(
            python_version="3.11.2",
            executable="/usr/bin/python3",
            os_family=OsFamily.LINUX,
            is_wsl=False,
            is_container=False,
        )

    def detect_os(self) -> tuple[str, str, str, OsFamily]:
        return self._os_info

    def detect_cpu(self) -> CpuInfo:
        return self._cpu

    def detect_ram(self) -> RamInfo:
        return self._ram

    def detect_gpus(self) -> list[GpuInfo]:
        return list(self._gpus)

    def detect_disk(self, path: str) -> DiskInfo | None:
        return self._disk

    def detect_audio_devices(self) -> tuple[list[AudioDeviceReport], list[AudioDeviceReport]]:
        return list(self._audio[0]), list(self._audio[1])

    def detect_cameras(self) -> list[CameraDeviceReport]:
        return list(self._cameras)

    def detect_displays(self) -> list[DisplayDeviceReport]:
        return list(self._displays)

    def detect_runtime(self) -> RuntimeInfo:
        return self._runtime

    # -------------------------------------------------------------------------
    # Factory Presets
    # -------------------------------------------------------------------------

    @classmethod
    def create_lab_pc_preset(cls) -> "FakeHardwareAdapter":
        """Ryzen 5 5500 + 48 GB RAM + RTX 3060 12GB."""
        return cls(
            os_info=("Linux", "6.8.0", "Linux Mint 22", OsFamily.LINUX),
            cpu=CpuInfo(
                model="AMD Ryzen 5 5500",
                architecture="x86_64",
                physical_cores=6,
                logical_cores=12,
                flags=["avx", "avx2", "fma", "sse4_1", "sse4_2"],
                has_avx=True,
                has_avx2=True,
                has_fma=True,
                has_sse4_1=True,
                has_sse4_2=True,
            ),
            ram=RamInfo(total_bytes=48 * 1024 * 1024 * 1024, available_bytes=42 * 1024 * 1024 * 1024),
            gpus=[
                GpuInfo(
                    vendor="nvidia",
                    model="NVIDIA GeForce RTX 3060",
                    is_dedicated=True,
                    vram_total_mb=12288,
                    vram_available_mb=11500,
                    driver_version="550.54.14",
                    backend="cuda",
                )
            ],
            disk=DiskInfo(path="/models", total_bytes=500 * 1024 * 1024 * 1024, free_bytes=350 * 1024 * 1024 * 1024),
        )

    @classmethod
    def create_bangho_preset(cls) -> "FakeHardwareAdapter":
        """Banghó Zero G05 + 8 GB RAM + Integrated GPU."""
        return cls(
            os_info=("Linux", "6.6.0", "Debian GNU/Linux 13", OsFamily.LINUX),
            cpu=CpuInfo(
                model="Intel Celeron / Core N-series",
                architecture="x86_64",
                physical_cores=4,
                logical_cores=4,
                flags=["avx", "avx2", "sse4_1", "sse4_2"],
                has_avx=True,
                has_avx2=True,
                has_fma=True,
                has_sse4_1=True,
                has_sse4_2=True,
            ),
            ram=RamInfo(total_bytes=8 * 1024 * 1024 * 1024, available_bytes=6 * 1024 * 1024 * 1024),
            gpus=[
                GpuInfo(
                    vendor="intel",
                    model="Intel UHD Graphics",
                    is_dedicated=False,
                    vram_total_mb=None,
                    vram_available_mb=None,
                    backend="vulkan",
                )
            ],
            disk=DiskInfo(path="/models", total_bytes=250 * 1024 * 1024 * 1024, free_bytes=180 * 1024 * 1024 * 1024),
        )

    @classmethod
    def create_sf20ba_preset(cls) -> "FakeHardwareAdapter":
        """SF20BA Celeron N2840 + 4 GB RAM + NO AVX2."""
        return cls(
            os_info=("Linux", "6.6.0", "Debian GNU/Linux 13", OsFamily.LINUX),
            cpu=CpuInfo(
                model="Intel Celeron N2840",
                architecture="x86_64",
                physical_cores=2,
                logical_cores=2,
                flags=["sse4_1", "sse4_2"],
                has_avx=False,
                has_avx2=False,
                has_fma=False,
                has_sse4_1=True,
                has_sse4_2=True,
            ),
            ram=RamInfo(total_bytes=4 * 1024 * 1024 * 1024, available_bytes=2800 * 1024 * 1024),
            gpus=[],
            disk=DiskInfo(path="/models", total_bytes=32 * 1024 * 1024 * 1024, free_bytes=15 * 1024 * 1024 * 1024),
        )

    @classmethod
    def create_satellite_preset(cls) -> "FakeHardwareAdapter":
        """2 GB RAM + 1 core satellite node."""
        return cls(
            os_info=("Linux", "6.6.0", "Debian GNU/Linux 13", OsFamily.LINUX),
            cpu=CpuInfo(
                model="Low-power SoC",
                architecture="x86_64",
                physical_cores=1,
                logical_cores=1,
                flags=["sse4_1"],
                has_avx=False,
                has_avx2=False,
            ),
            ram=RamInfo(total_bytes=2 * 1024 * 1024 * 1024, available_bytes=1100 * 1024 * 1024),
            gpus=[],
            disk=DiskInfo(path="/models", total_bytes=16 * 1024 * 1024 * 1024, free_bytes=8 * 1024 * 1024 * 1024),
            cameras=[],
            displays=[],
        )

"""Windows hardware adapter using stdlib, ctypes and fixed-argv CIM queries."""

import csv
import io
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

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


class WindowsHardwareAdapter(HardwareAdapter):
    """Hardware capability inspection adapter for Windows systems."""

    def detect_os(self) -> tuple[str, str, str, OsFamily]:
        """Query Windows OS version and release metadata."""
        sys_name = "Windows"
        sys_version = platform.version()
        release = platform.release()
        return sys_name, sys_version, f"Windows {release}", OsFamily.WINDOWS

    def detect_cpu(self) -> CpuInfo:
        """Inspect processor model, cores and instruction sets on Windows."""
        model = platform.processor() or "UNKNOWN"
        arch = platform.machine() or "AMD64"
        physical_cores: int | None = None
        logical_cores: int | None = os.cpu_count()

        # Fixed allowlisted PowerShell CIM query
        out = self._run_fixed_cmd([
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_Processor | Select-Object -Property Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Csv -NoTypeInformation",
        ])

        parsed_model, parsed_physical, parsed_logical = self.parse_cim_cpu(out)
        if parsed_model:
            model = parsed_model
        if parsed_physical is not None:
            physical_cores = parsed_physical
        if parsed_logical is not None:
            logical_cores = parsed_logical

        return CpuInfo(
            model=model,
            architecture=arch,
            physical_cores=physical_cores,
            logical_cores=logical_cores,
            flags=[],
            has_avx=None,
            has_avx2=None,
            has_fma=None,
            has_sse4_1=None,
            has_sse4_2=None,
            has_neon=None,
        )

    def detect_ram(self) -> RamInfo:
        """Detect total and available RAM via GlobalMemoryStatusEx or fixed CIM query."""
        # 1. Try ctypes if on native Windows
        if sys.platform == "win32":
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    return RamInfo(
                        total_bytes=int(stat.ullTotalPhys),
                        available_bytes=int(stat.ullAvailPhys),
                    )
            except Exception:  # noqa: BLE001, S110
                pass

        # 2. Fallback via fixed CIM query
        out = self._run_fixed_cmd([
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Csv -NoTypeInformation",
        ])
        total_b, avail_b = self.parse_cim_ram(out)
        return RamInfo(total_bytes=total_b, available_bytes=avail_b)

    def detect_gpus(self) -> list[GpuInfo]:
        """Detect GPUs via nvidia-smi executable or fixed CIM query."""
        gpus: list[GpuInfo] = []

        # 1. Try nvidia-smi in fixed path locations or PATH
        nvidia_paths = [
            "nvidia-smi",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            r"C:\Windows\System32\nvidia-smi.exe",
        ]

        for n_path in nvidia_paths:
            try:
                cmd = [
                    n_path,
                    "--query-gpu=name,memory.total,memory.free,driver_version",
                    "--format=csv,noheader,nounits",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0, check=False)
                if res.returncode == 0 and res.stdout.strip():
                    for line in res.stdout.strip().splitlines():
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 4:
                            name, total_str, free_str, driver = parts[0], parts[1], parts[2], parts[3]
                            gpus.append(
                                GpuInfo(
                                    vendor="nvidia",
                                    model=name,
                                    is_dedicated=True,
                                    vram_total_mb=int(float(total_str)),
                                    vram_available_mb=int(float(free_str)),
                                    driver_version=driver,
                                    backend="cuda",
                                )
                            )
                    if gpus:
                        return gpus
            except Exception:  # noqa: BLE001, S110
                pass

        # 2. Fallback via fixed CIM query for video controllers
        out = self._run_fixed_cmd([
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Csv -NoTypeInformation",
        ])
        return self.parse_cim_gpus(out)

    def detect_disk(self, path: str) -> DiskInfo | None:
        """Measure disk total and available space using shutil.disk_usage."""
        try:
            target_path = Path(path)
            check_path = target_path
            while not check_path.exists() and check_path.parent != check_path:
                check_path = check_path.parent

            usage = shutil.disk_usage(check_path)
            return DiskInfo(
                path=str(target_path),
                total_bytes=usage.total,
                free_bytes=usage.free,
            )
        except Exception:  # noqa: BLE001
            return None

    def detect_audio_devices(self) -> tuple[list[AudioDeviceReport], list[AudioDeviceReport]]:
        """Detect sound devices via fixed CIM query."""
        out = self._run_fixed_cmd([
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_SoundDevice | Select-Object DeviceID,Name,Status | ConvertTo-Csv -NoTypeInformation",
        ])
        return self.parse_cim_audio(out)

    def detect_cameras(self) -> list[CameraDeviceReport]:
        """Detect video capture devices via fixed CIM query."""
        out = self._run_fixed_cmd([
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPClass -eq 'Camera' -or $_.PNPClass -eq 'Image' } | Select-Object DeviceID,Name,Status | ConvertTo-Csv -NoTypeInformation",
        ])
        return self.parse_cim_cameras(out)

    def detect_displays(self) -> list[DisplayDeviceReport]:
        """Detect monitors via fixed CIM query."""
        out = self._run_fixed_cmd([
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_DesktopMonitor | Select-Object DeviceID,Name,ScreenWidth,ScreenHeight | ConvertTo-Csv -NoTypeInformation",
        ])
        return self.parse_cim_displays(out)

    def detect_runtime(self) -> RuntimeInfo:
        """Inspect current Python executable runtime on Windows."""
        return RuntimeInfo(
            python_version=platform.python_version(),
            executable=sys.executable,
            os_family=OsFamily.WINDOWS,
            is_wsl=False,
            is_container=False,
        )

    # -------------------------------------------------------------------------
    # Defensive Parsers (also used directly in unit testing with fixture strings)
    # -------------------------------------------------------------------------

    @staticmethod
    def parse_cim_cpu(csv_output: str) -> tuple[str | None, int | None, int | None]:
        """Parse CIM CPU CSV output using stdlib csv."""
        if not csv_output.strip():
            return None, None, None
        reader = csv.reader(io.StringIO(csv_output.strip()))
        rows = [r for r in reader if any(field.strip() for field in r)]
        if len(rows) > 1:
            row = rows[1]
            name = row[0].strip() if len(row) > 0 and row[0].strip() else None
            phys = int(row[1].strip()) if len(row) > 1 and row[1].strip().isdigit() else None
            log = int(row[2].strip()) if len(row) > 2 and row[2].strip().isdigit() else None
            return name, phys, log
        return None, None, None

    @staticmethod
    def parse_cim_ram(csv_output: str) -> tuple[int, int]:
        """Parse CIM OperatingSystem RAM CSV output in kB to bytes using stdlib csv."""
        if not csv_output.strip():
            return 0, 0
        reader = csv.reader(io.StringIO(csv_output.strip()))
        rows = [r for r in reader if any(field.strip() for field in r)]
        if len(rows) > 1:
            row = rows[1]
            try:
                total_kb = int(row[0].strip()) if len(row) > 0 and row[0].strip().isdigit() else 0
                free_kb = int(row[1].strip()) if len(row) > 1 and row[1].strip().isdigit() else 0
                return total_kb * 1024, free_kb * 1024
            except (ValueError, IndexError):
                pass
        return 0, 0

    @staticmethod
    def parse_cim_gpus(csv_output: str) -> list[GpuInfo]:
        """Parse CIM VideoController CSV output using stdlib csv."""
        gpus: list[GpuInfo] = []
        if not csv_output.strip():
            return gpus
        reader = csv.reader(io.StringIO(csv_output.strip()))
        rows = [r for r in reader if any(field.strip() for field in r)]
        if len(rows) > 1:
            for row in rows[1:]:
                if row and row[0].strip():
                    name = row[0].strip()
                    vram_mb: int | None = None
                    if len(row) > 1 and row[1].strip().isdigit():
                        vram_bytes = int(row[1].strip())
                        vram_mb = vram_bytes // (1024 * 1024) if vram_bytes > 0 else None
                    driver = row[2].strip() if len(row) > 2 and row[2].strip() else None
                    name_lower = name.lower()
                    vendor = (
                        "nvidia"
                        if "nvidia" in name_lower
                        else (
                            "amd"
                            if "amd" in name_lower or "radeon" in name_lower
                            else ("intel" if "intel" in name_lower else "unknown")
                        )
                    )
                    gpus.append(
                        GpuInfo(
                            vendor=vendor,
                            model=name,
                            is_dedicated=vendor == "nvidia" or (vram_mb is not None and vram_mb > 1024),
                            vram_total_mb=vram_mb,
                            vram_available_mb=None,  # Win32_VideoController reports total, not free
                            driver_version=driver,
                            backend="cuda" if vendor == "nvidia" else ("directml" if vendor in ("amd", "intel") else None),
                        )
                    )
        return gpus

    @staticmethod
    def parse_cim_audio(csv_output: str) -> tuple[list[AudioDeviceReport], list[AudioDeviceReport]]:
        """Parse CIM SoundDevice CSV output using stdlib csv."""
        inputs: list[AudioDeviceReport] = []
        outputs: list[AudioDeviceReport] = []
        if not csv_output.strip():
            return inputs, outputs
        reader = csv.reader(io.StringIO(csv_output.strip()))
        rows = [r for r in reader if any(field.strip() for field in r)]
        if len(rows) > 1:
            for idx, row in enumerate(rows[1:]):
                if row and row[0].strip():
                    dev_id = row[0].strip()
                    name = row[1].strip() if len(row) > 1 and row[1].strip() else dev_id
                    status = row[2].strip().upper() if len(row) > 2 else "OK"
                    if status == "OK":
                        outputs.append(
                            AudioDeviceReport(
                                id=dev_id,
                                name=name,
                                is_input=False,
                                is_output=True,
                                is_default=idx == 0,
                            )
                        )
        return inputs, outputs

    @staticmethod
    def parse_cim_cameras(csv_output: str) -> list[CameraDeviceReport]:
        """Parse CIM Camera PnP CSV output using stdlib csv."""
        cameras: list[CameraDeviceReport] = []
        if not csv_output.strip():
            return cameras
        reader = csv.reader(io.StringIO(csv_output.strip()))
        rows = [r for r in reader if any(field.strip() for field in r)]
        if len(rows) > 1:
            for idx, row in enumerate(rows[1:]):
                if row and row[0].strip():
                    dev_id = row[0].strip()
                    name = row[1].strip() if len(row) > 1 and row[1].strip() else dev_id
                    cameras.append(
                        CameraDeviceReport(
                            device_path=dev_id,
                            index=idx,
                            name=name,
                            is_available=True,
                        )
                    )
        return cameras

    @staticmethod
    def parse_cim_displays(csv_output: str) -> list[DisplayDeviceReport]:
        """Parse CIM DesktopMonitor CSV output using stdlib csv."""
        displays: list[DisplayDeviceReport] = []
        if not csv_output.strip():
            return displays
        reader = csv.reader(io.StringIO(csv_output.strip()))
        rows = [r for r in reader if any(field.strip() for field in r)]
        if len(rows) > 1:
            for idx, row in enumerate(rows[1:]):
                if row and row[0].strip():
                    name = row[1].strip() if len(row) > 1 and row[1].strip() else row[0].strip()
                    w = int(row[2].strip()) if len(row) > 2 and row[2].strip().isdigit() else None
                    h = int(row[3].strip()) if len(row) > 3 and row[3].strip().isdigit() else None
                    displays.append(
                        DisplayDeviceReport(
                            name=name,
                            width=w,
                            height=h,
                            is_primary=idx == 0,
                        )
                    )
        return displays

    def _run_fixed_cmd(self, cmd: list[str]) -> str:
        """Run a fixed command safely with timeout without shell=True."""
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=2.5,
                check=False,
            )
            if res.returncode == 0:
                return res.stdout
        except Exception:  # noqa: BLE001, S110
            pass
        return ""

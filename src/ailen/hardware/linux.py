"""Linux hardware adapter inspecting /proc, /sys, ALSA, V4L2 and DRM."""

import glob
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


class LinuxHardwareAdapter(HardwareAdapter):
    """Inspects Linux system capabilities via standard kernel interfaces and allowlisted tools."""

    def detect_os(self) -> tuple[str, str, str, OsFamily]:
        """Detect Linux OS name, release and distribution from /etc/os-release."""
        sys_name = platform.system()
        sys_version = platform.release()
        distro = "Linux"

        os_release_path = Path("/etc/os-release")
        if os_release_path.is_file():
            try:
                content = os_release_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith("PRETTY_NAME="):
                        distro = line.split("=", 1)[1].strip('"\'')
                        break
                    if line.startswith("NAME=") and distro == "Linux":
                        distro = line.split("=", 1)[1].strip('"\'')
            except Exception:  # noqa: BLE001, S110
                pass

        return sys_name, sys_version, distro, OsFamily.LINUX

    def detect_cpu(self) -> CpuInfo:
        """Parse /proc/cpuinfo for model, cores, and instruction set flags."""
        model = "UNKNOWN"
        arch = platform.machine() or "x86_64"
        flags: list[str] = []
        physical_cores: int | None = None
        logical_cores: int | None = os.cpu_count()
        flags_found = False

        cpuinfo_path = Path("/proc/cpuinfo")
        if cpuinfo_path.is_file():
            try:
                content = cpuinfo_path.read_text(encoding="utf-8")
                core_pairs: set[tuple[str, str]] = set()
                current_physical_id = "0"
                for line in content.splitlines():
                    if ":" in line:
                        k, v = (part.strip() for part in line.split(":", 1))
                        if k in ("model name", "Hardware", "Processor") and model == "UNKNOWN":
                            model = v
                        elif k in ("flags", "Features"):
                            flags = v.split()
                            flags_found = True
                        elif k == "physical id":
                            current_physical_id = v
                        elif k == "core id":
                            core_pairs.add((current_physical_id, v))
                if core_pairs:
                    physical_cores = len(core_pairs)
            except Exception:  # noqa: BLE001, S110
                pass

        flags_set = set(flags)
        return CpuInfo(
            model=model,
            architecture=arch,
            physical_cores=physical_cores,
            logical_cores=logical_cores,
            flags=flags,
            has_avx=("avx" in flags_set) if flags_found else None,
            has_avx2=("avx2" in flags_set) if flags_found else None,
            has_fma=("fma" in flags_set) if flags_found else None,
            has_sse4_1=("sse4_1" in flags_set) if flags_found else None,
            has_sse4_2=("sse4_2" in flags_set) if flags_found else None,
            has_neon=("neon" in flags_set or "asimd" in flags_set) if flags_found else None,
        )

    def detect_ram(self) -> RamInfo:
        """Parse /proc/meminfo for total and available system memory."""
        total_bytes = 0
        available_bytes = 0
        mem_free = 0
        buffers = 0
        cached = 0

        meminfo_path = Path("/proc/meminfo")
        if meminfo_path.is_file():
            try:
                content = meminfo_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if ":" in line:
                        k, v = (part.strip() for part in line.split(":", 1))
                        parts = v.split()
                        if parts:
                            kb = int(parts[0])
                            if k == "MemTotal":
                                total_bytes = kb * 1024
                            elif k == "MemAvailable":
                                available_bytes = kb * 1024
                            elif k == "MemFree":
                                mem_free = kb * 1024
                            elif k == "Buffers":
                                buffers = kb * 1024
                            elif k == "Cached":
                                cached = kb * 1024
            except Exception:  # noqa: BLE001, S110
                pass

        if available_bytes == 0 and (mem_free > 0 or cached > 0):
            available_bytes = mem_free + buffers + cached

        return RamInfo(total_bytes=total_bytes, available_bytes=available_bytes)

    def detect_gpus(self) -> list[GpuInfo]:
        """Detect GPUs via nvidia-smi and DRM interfaces."""
        gpus: list[GpuInfo] = []

        # 1. Probe NVIDIA GPU via nvidia-smi
        try:
            cmd = [
                "nvidia-smi",
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
        except Exception:  # noqa: BLE001, S110
            pass

        # 2. Probe DRM cards if no NVIDIA GPU found
        if not gpus:
            drm_cards = glob.glob("/sys/class/drm/card[0-9]")
            for card in drm_cards:
                device_name_path = Path(card) / "device" / "uevent"
                vendor = "unknown"
                model = Path(card).name
                if device_name_path.is_file():
                    try:
                        content = device_name_path.read_text(encoding="utf-8")
                        for line in content.splitlines():
                            if "PCI_ID=" in line:
                                vendor = "intel" if "8086:" in line else ("amd" if "1002:" in line else "unknown")
                    except Exception:  # noqa: BLE001, S110
                        pass
                gpus.append(
                    GpuInfo(
                        vendor=vendor,
                        model=model,
                        is_dedicated=False,
                        vram_total_mb=None,
                        vram_available_mb=None,
                        driver_version=None,
                        backend=None,
                    )
                )

        return gpus

    def detect_disk(self, path: str) -> DiskInfo | None:
        """Measure disk total and available space using shutil.disk_usage."""
        try:
            target_path = Path(path)
            # Find closest existing parent path if directory does not exist yet
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
        """Parse ALSA sound card devices from /proc/asound/pcm or arecord/aplay."""
        inputs: list[AudioDeviceReport] = []
        outputs: list[AudioDeviceReport] = []

        pcm_path = Path("/proc/asound/pcm")
        if pcm_path.is_file():
            try:
                content = pcm_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    # Format e.g. "00-00: ALC887-VD Analog : ALC887-VD Analog : playback 1 : capture 1"
                    if ":" in line:
                        parts = [p.strip() for p in line.split(":")]
                        dev_id = f"hw:{parts[0]}"
                        name = parts[1] if len(parts) > 1 else dev_id
                        line_lower = line.lower()
                        is_cap = "capture" in line_lower
                        is_play = "playback" in line_lower

                        if is_cap:
                            inputs.append(AudioDeviceReport(id=dev_id, name=name, is_input=True, is_output=False))
                        if is_play:
                            outputs.append(AudioDeviceReport(id=dev_id, name=name, is_input=False, is_output=True))
            except Exception:  # noqa: BLE001, S110
                pass

        return inputs, outputs

    def detect_cameras(self) -> list[CameraDeviceReport]:
        """Detect video capture devices in /sys/class/video4linux."""
        cameras: list[CameraDeviceReport] = []
        v4l_dirs = sorted(glob.glob("/sys/class/video4linux/video[0-9]*"))
        for v4l_dir in v4l_dirs:
            name_file = Path(v4l_dir) / "name"
            dev_name = Path(v4l_dir).name  # e.g. "video0"
            dev_path = f"/dev/{dev_name}"
            friendly_name = "Camera"
            if name_file.is_file():
                try:
                    friendly_name = name_file.read_text(encoding="utf-8").strip()
                except Exception:  # noqa: BLE001, S110
                    pass

            idx = 0
            try:
                idx = int(dev_name.replace("video", ""))
            except ValueError:
                pass

            cameras.append(
                CameraDeviceReport(
                    device_path=dev_path,
                    index=idx,
                    name=friendly_name,
                    is_available=Path(dev_path).exists(),
                )
            )

        return cameras

    def detect_displays(self) -> list[DisplayDeviceReport]:
        """Detect connected monitors via /sys/class/drm status."""
        displays: list[DisplayDeviceReport] = []
        status_files = glob.glob("/sys/class/drm/card*-*/status")
        for sf in status_files:
            try:
                status_path = Path(sf)
                if status_path.read_text(encoding="utf-8").strip() == "connected":
                    conn_name = status_path.parent.name.split("-", 1)[1] if "-" in status_path.parent.name else status_path.parent.name
                    modes_file = status_path.parent / "modes"
                    width: int | None = None
                    height: int | None = None
                    if modes_file.is_file():
                        mode_line = modes_file.read_text(encoding="utf-8").splitlines()
                        if mode_line and "x" in mode_line[0]:
                            dims = mode_line[0].split("x")
                            width, height = int(dims[0]), int(dims[1])
                    displays.append(
                        DisplayDeviceReport(
                            name=conn_name,
                            width=width,
                            height=height,
                            is_primary=len(displays) == 0,
                        )
                    )
            except Exception:  # noqa: BLE001, S110
                pass

        return displays

    def detect_runtime(self) -> RuntimeInfo:
        """Inspect current Python executable runtime and environment."""
        is_wsl = False
        is_container = Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()

        proc_version = Path("/proc/version")
        if proc_version.is_file():
            try:
                v_text = proc_version.read_text(encoding="utf-8").lower()
                is_wsl = "microsoft" in v_text or "wsl" in v_text
            except Exception:  # noqa: BLE001, S110
                pass

        return RuntimeInfo(
            python_version=platform.python_version(),
            executable=sys.executable,
            os_family=OsFamily.LINUX,
            is_wsl=is_wsl,
            is_container=is_container,
        )

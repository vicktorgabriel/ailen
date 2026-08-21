"""Hardware diagnostics for AILEN."""

import glob
import os
import platform
import shutil
import socket
from pathlib import Path

from ailen.domain.enums import DeviceProfile
from ailen.domain.models import (
    AudioDeviceInfo,
    CameraInfo,
    CpuInfo,
    DiskInfo,
    DisplayInfo,
    GpuInfo,
    HardwareReport,
    MemoryInfo,
    NetworkInfo,
    OsInfo,
)


class HardwareDiagnostics:
    """Best-effort hardware discovery engine for Linux / POSIX systems."""

    def probe_cpu(self) -> CpuInfo:
        """Discover CPU specifications."""
        arch = platform.machine()
        cores_logical = os.cpu_count() or 1
        cores_physical = cores_logical
        model = "Unknown CPU"
        freq_mhz = None

        cpuinfo_path = Path("/proc/cpuinfo")
        if cpuinfo_path.is_file():
            try:
                content = cpuinfo_path.read_text(encoding="utf-8", errors="ignore")
                physical_ids = set()
                core_ids = set()
                for line in content.splitlines():
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if key in ("model name", "Hardware", "Processor") and model == "Unknown CPU":
                        model = val
                    elif key == "cpu MHz" and freq_mhz is None:
                        try:
                            freq_mhz = float(val)
                        except ValueError:
                            pass
                    elif key == "physical id":
                        physical_ids.add(val)
                    elif key == "core id":
                        core_ids.add(val)

                if physical_ids and core_ids:
                    cores_physical = len(physical_ids) * len(core_ids)
                elif core_ids:
                    cores_physical = len(core_ids)
            except OSError:
                pass

        return CpuInfo(
            model=model,
            arch=arch,
            cores_physical=cores_physical,
            cores_logical=cores_logical,
            frequency_mhz=freq_mhz,
        )

    def probe_memory(self) -> MemoryInfo:
        """Discover RAM capacity and availability."""
        total_kb = 0
        avail_kb = 0

        meminfo_path = Path("/proc/meminfo")
        if meminfo_path.is_file():
            try:
                content = meminfo_path.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            total_kb = int(parts[1])
                    elif line.startswith("MemAvailable:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            avail_kb = int(parts[1])
            except (OSError, ValueError):
                pass

        total_bytes = total_kb * 1024
        available_bytes = avail_kb * 1024
        used_bytes = max(0, total_bytes - available_bytes)

        return MemoryInfo(
            total_bytes=total_bytes,
            available_bytes=available_bytes,
            used_bytes=used_bytes,
            total_mb=round(total_bytes / (1024 * 1024), 1),
            available_mb=round(available_bytes / (1024 * 1024), 1),
        )

    def probe_disk(self, mount_point: str = "/") -> DiskInfo:
        """Discover disk storage capacity."""
        try:
            usage = shutil.disk_usage(mount_point)
            return DiskInfo(
                mount_point=mount_point,
                total_bytes=usage.total,
                free_bytes=usage.free,
                used_bytes=usage.used,
                total_gb=round(usage.total / (1024**3), 2),
                free_gb=round(usage.free / (1024**3), 2),
            )
        except OSError:
            return DiskInfo(mount_point=mount_point)

    def probe_gpu(self) -> GpuInfo:
        """Discover GPU / Graphics devices."""
        # Check /dev/dri
        dri_devices = glob.glob("/dev/dri/card*")
        render_nodes = glob.glob("/dev/dri/renderD*")
        if dri_devices or render_nodes:
            # Check sysfs for PCI vendor/model
            gpu_names = []
            for card in dri_devices:
                card_name = os.path.basename(card)
                device_link = Path(f"/sys/class/drm/{card_name}/device")
                if device_link.exists():
                    gpu_names.append(f"DRM Device ({card_name})")
            name = ", ".join(gpu_names) if gpu_names else "Generic DRM Card"
            return GpuInfo(detected=True, name=name, driver="drm/kms")

        return GpuInfo(detected=False, name="None")

    def probe_audio(self) -> tuple[list[AudioDeviceInfo], list[AudioDeviceInfo]]:
        """Discover ALSA audio capture and playback devices."""
        inputs: list[AudioDeviceInfo] = []
        outputs: list[AudioDeviceInfo] = []

        cards_path = Path("/proc/asound/cards")
        if cards_path.is_file():
            try:
                content = cards_path.read_text(encoding="utf-8", errors="ignore")
                card_idx = 0
                for line in content.splitlines():
                    line = line.strip()
                    if line and line[0].isdigit() and "[" in line:
                        parts = line.split("[", 1)
                        if len(parts) == 2:
                            num_str = parts[0].strip()
                            try:
                                card_idx = int(num_str)
                            except ValueError:
                                pass
                            name_part = parts[1].split("]")[0].strip()
                            # Register device as both potential input and output
                            inputs.append(AudioDeviceInfo(
                                index=card_idx,
                                name=f"hw:{card_idx} ({name_part})",
                                is_input=True,
                                is_output=False,
                                is_default=(card_idx == 0),
                            ))
                            outputs.append(AudioDeviceInfo(
                                index=card_idx,
                                name=f"hw:{card_idx} ({name_part})",
                                is_input=False,
                                is_output=True,
                                is_default=(card_idx == 0),
                            ))
            except OSError:
                pass

        if not inputs and not outputs:
            # Fallback default
            inputs.append(AudioDeviceInfo(index=0, name="default", is_input=True, is_output=False, is_default=True))
            outputs.append(AudioDeviceInfo(index=0, name="default", is_input=False, is_output=True, is_default=True))

        return inputs, outputs

    def probe_cameras(self) -> list[CameraInfo]:
        """Discover connected video capture devices."""
        cameras: list[CameraInfo] = []
        video_devs = sorted(glob.glob("/dev/video*"))
        for dev in video_devs:
            name = Path(dev).name
            sys_name_path = Path(f"/sys/class/video4linux/{name}/name")
            display_name = name
            if sys_name_path.is_file():
                try:
                    display_name = sys_name_path.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
            accessible = os.access(dev, os.R_OK)
            cameras.append(CameraInfo(
                device_path=dev,
                name=display_name,
                accessible=accessible,
            ))
        return cameras

    def probe_displays(self) -> list[DisplayInfo]:
        """Discover connected displays via DRM / sysfs."""
        displays: list[DisplayInfo] = []
        drm_connectors = sorted(glob.glob("/sys/class/drm/card*-*"))
        for conn in drm_connectors:
            conn_name = Path(conn).name.split("-", 1)[-1]
            status_file = Path(conn) / "status"
            connected = False
            if status_file.is_file():
                try:
                    status_text = status_file.read_text(encoding="utf-8").strip()
                    connected = (status_text == "connected")
                except OSError:
                    pass

            modes_file = Path(conn) / "modes"
            res = None
            if connected and modes_file.is_file():
                try:
                    modes_text = modes_file.read_text(encoding="utf-8").strip().splitlines()
                    if modes_text:
                        res = modes_text[0]
                except OSError:
                    pass

            if connected or not displays:
                displays.append(DisplayInfo(
                    connector=conn_name,
                    connected=connected,
                    resolution=res,
                ))

        if not displays:
            displays.append(DisplayInfo(connector="default", connected=True, resolution="1280x720"))

        return displays

    def probe_network(self) -> list[NetworkInfo]:
        """Discover network interfaces and IP addresses."""
        interfaces: list[NetworkInfo] = []
        net_devs = sorted(glob.glob("/sys/class/net/*"))
        for dev in net_devs:
            iface_name = Path(dev).name
            if iface_name == "lo":
                continue
            operstate_file = Path(dev) / "operstate"
            is_up = False
            if operstate_file.is_file():
                try:
                    state = operstate_file.read_text(encoding="utf-8").strip()
                    is_up = (state == "up")
                except OSError:
                    pass

            # Best-effort IP lookup for this interface
            ip_addr: str | None = None
            if is_up:
                try:
                    # Generic socket lookup
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        s.settimeout(0.1)
                        s.connect(("8.8.8.8", 80))
                        ip_addr = s.getsockname()[0]
                except OSError:
                    ip_addr = None

            interfaces.append(NetworkInfo(
                interface=iface_name,
                is_up=is_up,
                ip_address=ip_addr if is_up else None,
            ))
        return interfaces

    def probe_os(self) -> OsInfo:
        """Discover OS, distribution, and kernel information."""
        system = platform.system()
        release = platform.release()
        distro = "Linux Generic"

        os_release = Path("/etc/os-release")
        if os_release.is_file():
            try:
                content = os_release.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    if line.startswith("PRETTY_NAME="):
                        distro = line.split("=", 1)[1].strip('"\'')
                        break
            except OSError:
                pass

        return OsInfo(
            system=system,
            release=release,
            distribution=distro,
            kernel_version=platform.version(),
        )

    def recommend_profile(self, memory: MemoryInfo, cpu: CpuInfo) -> DeviceProfile:
        """Recommend hardware profile based on measured RAM and CPU."""
        ram_mb = memory.total_mb

        if ram_mb > 0 and ram_mb < 3000:
            # 2 GB class
            return DeviceProfile.SATELLITE
        elif ram_mb >= 3000 and ram_mb < 6000:
            # 4 GB class
            return DeviceProfile.CLOUD
        elif ram_mb >= 6000 and ram_mb < 12000:
            # 8 GB class (e.g. Banghó Zero G05)
            return DeviceProfile.HYBRID
        elif ram_mb >= 12000 and cpu.cores_logical >= 6:
            # 16 GB+ workstation / host
            return DeviceProfile.LAN_BRAIN
        else:
            return DeviceProfile.HYBRID

    def run(self) -> HardwareReport:
        """Execute full hardware diagnostics."""
        cpu = self.probe_cpu()
        mem = self.probe_memory()
        disk = self.probe_disk()
        gpu = self.probe_gpu()
        aud_in, aud_out = self.probe_audio()
        cams = self.probe_cameras()
        displays = self.probe_displays()
        net = self.probe_network()
        os_info = self.probe_os()
        rec_profile = self.recommend_profile(mem, cpu)

        return HardwareReport(
            cpu=cpu,
            memory=mem,
            disk=disk,
            gpu=gpu,
            audio_inputs=aud_in,
            audio_outputs=aud_out,
            cameras=cams,
            displays=displays,
            network=net,
            os=os_info,
            recommended_profile=rec_profile,
        )


def format_hardware_report(report: HardwareReport) -> str:
    """Format hardware report into a readable console string."""
    display_strs = [f"{d.connector}:{d.resolution or 'auto'}" for d in report.displays]
    displays_formatted = ", ".join(display_strs)
    cameras_formatted = ", ".join(c.device_path for c in report.cameras) if report.cameras else "None"
    audio_in_names = ", ".join(d.name for d in report.audio_inputs[:2])
    audio_out_names = ", ".join(d.name for d in report.audio_outputs[:2])
    net_formatted = ", ".join(f"{n.interface} (up={n.is_up})" for n in report.network)

    lines = [
        "==================================================================",
        "                      AILEN HARDWARE REPORT                      ",
        "==================================================================",
        f"OS / Distro : {report.os.distribution} (Kernel: {report.os.release})",
        f"Architecture: {report.cpu.arch} | System: {report.os.system}",
        "------------------------------------------------------------------",
        f"CPU Model   : {report.cpu.model}",
        f"CPU Cores   : {report.cpu.cores_physical} physical / {report.cpu.cores_logical} logical",
        f"RAM Total   : {report.memory.total_mb} MB (Available: {report.memory.available_mb} MB)",
        f"Disk (/)    : {report.disk.total_gb} GB total / {report.disk.free_gb} GB free",
        f"GPU         : {report.gpu.name} (Driver: {report.gpu.driver or 'N/A'})",
        "------------------------------------------------------------------",
        f"Audio In    : {len(report.audio_inputs)} devices detected ({audio_in_names})",
        f"Audio Out   : {len(report.audio_outputs)} devices detected ({audio_out_names})",
        f"Cameras     : {len(report.cameras)} detected ({cameras_formatted})",
        f"Displays    : {len(report.displays)} ({displays_formatted})",
        f"Network     : {net_formatted}",
        "==================================================================",
        f"RECOMMENDED PROFILE: {report.recommended_profile.value}",
        "==================================================================",
    ]
    return "\n".join(lines)

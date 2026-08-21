"""Unit tests for hardware adapters across Linux, Windows and Fake implementations."""

from ailen.hardware.contracts import OsFamily
from ailen.hardware.fake import FakeHardwareAdapter
from ailen.hardware.linux import LinuxHardwareAdapter
from ailen.hardware.windows import WindowsHardwareAdapter


def test_fake_hardware_adapter_presets() -> None:
    # 1. Lab PC Preset
    lab_adapter = FakeHardwareAdapter.create_lab_pc_preset()
    _os_name, _, _, os_family = lab_adapter.detect_os()
    assert os_family == OsFamily.LINUX
    assert "Linux Mint" in lab_adapter.detect_os()[2]

    cpu = lab_adapter.detect_cpu()
    assert cpu.has_avx2 is True
    assert cpu.has_fma is True
    assert cpu.physical_cores == 6

    ram = lab_adapter.detect_ram()
    assert ram.total_gb >= 48.0
    assert ram.available_gb >= 40.0

    gpus = lab_adapter.detect_gpus()
    assert len(gpus) == 1
    assert gpus[0].vendor == "nvidia"
    assert gpus[0].vram_total_mb == 12288
    assert gpus[0].is_dedicated is True

    # 2. Banghó Preset
    bangho_adapter = FakeHardwareAdapter.create_bangho_preset()
    assert bangho_adapter.detect_ram().total_gb == 8.0
    assert bangho_adapter.detect_cpu().has_avx2 is True

    # 3. SF20BA Preset (No AVX2)
    sf20_adapter = FakeHardwareAdapter.create_sf20ba_preset()
    assert sf20_adapter.detect_ram().total_gb == 4.0
    assert sf20_adapter.detect_cpu().has_avx2 is False

    # 4. Satellite Preset (2GB)
    sat_adapter = FakeHardwareAdapter.create_satellite_preset()
    assert sat_adapter.detect_ram().total_gb == 2.0
    assert len(sat_adapter.detect_cameras()) == 0
    assert len(sat_adapter.detect_displays()) == 0


def test_windows_adapter_cim_parsers_with_quotes_and_commas() -> None:
    # Test CIM CPU CSV parsing with quotes
    sample_cpu_csv = (
        '"Name","NumberOfCores","NumberOfLogicalProcessors"\n'
        '"13th Gen Intel(R) Core(TM) i7-13700H, with vPro",14,20\n'
    )
    name, phys, log = WindowsHardwareAdapter.parse_cim_cpu(sample_cpu_csv)
    assert name == "13th Gen Intel(R) Core(TM) i7-13700H, with vPro"
    assert phys == 14
    assert log == 20

    # Test CIM RAM CSV parsing (TotalVisibleMemorySize, FreePhysicalMemory in kB)
    sample_ram_csv = (
        '"TotalVisibleMemorySize","FreePhysicalMemory"\n'
        '"33285120","18543200"\n'
    )
    total_b, free_b = WindowsHardwareAdapter.parse_cim_ram(sample_ram_csv)
    assert total_b == 33285120 * 1024
    assert free_b == 18543200 * 1024

    # Test CIM GPU CSV parsing with commas in names and verify vram_available_mb is None
    sample_gpu_csv = (
        '"Name","AdapterRAM","DriverVersion"\n'
        '"NVIDIA Corporation, GeForce RTX 4070 Laptop GPU","8589934592","31.0.15.4633"\n'
        '"Intel(R) Corporation, Iris(R) Xe Graphics","1073741824","31.0.101.4575"\n'
    )
    gpus = WindowsHardwareAdapter.parse_cim_gpus(sample_gpu_csv)
    assert len(gpus) == 2
    assert gpus[0].vendor == "nvidia"
    assert gpus[0].model == "NVIDIA Corporation, GeForce RTX 4070 Laptop GPU"
    assert gpus[0].vram_total_mb == 8192
    assert gpus[0].vram_available_mb is None  # AdapterRAM is total, not free!
    assert gpus[0].backend == "cuda"
    assert gpus[1].vendor == "intel"
    assert gpus[1].model == "Intel(R) Corporation, Iris(R) Xe Graphics"

    # Test CIM Audio CSV parsing with commas
    sample_audio_csv = (
        '"DeviceID","Name","Status"\n'
        '"HDAUDIO\\FUNC_01...","Realtek High Definition Audio, Audio Device","OK"\n'
    )
    _inputs, outputs = WindowsHardwareAdapter.parse_cim_audio(sample_audio_csv)
    assert len(outputs) == 1
    assert outputs[0].name == "Realtek High Definition Audio, Audio Device"

    # Test CIM Camera CSV parsing
    sample_cam_csv = (
        '"DeviceID","Name","Status"\n'
        '"USB\\VID_04F2...","Integrated Camera, HD 720p","OK"\n'
    )
    cams = WindowsHardwareAdapter.parse_cim_cameras(sample_cam_csv)
    assert len(cams) == 1
    assert cams[0].name == "Integrated Camera, HD 720p"


def test_windows_adapter_does_not_invent_cpu_flags() -> None:
    adapter = WindowsHardwareAdapter()
    cpu = adapter.detect_cpu()
    # Windows CPU flags must be None (unmeasured/unknown) unless measured
    assert cpu.has_avx is None
    assert cpu.has_avx2 is None
    assert cpu.has_fma is None
    assert cpu.has_sse4_1 is None


def test_linux_adapter_inspection_on_current_host() -> None:
    adapter = LinuxHardwareAdapter()
    _os_name, _os_version, distro, os_family = adapter.detect_os()
    assert os_family == OsFamily.LINUX
    assert len(distro) > 0

    cpu = adapter.detect_cpu()
    assert cpu.logical_cores is not None and cpu.logical_cores > 0

    ram = adapter.detect_ram()
    assert ram.total_bytes > 0

    runtime = adapter.detect_runtime()
    assert runtime.os_family == OsFamily.LINUX
    assert len(runtime.python_version) > 0

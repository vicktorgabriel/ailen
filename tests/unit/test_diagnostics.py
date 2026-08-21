"""Unit tests for hardware diagnostics and profile recommendation."""

import unittest

from ailen.core.diagnostics import HardwareDiagnostics, format_hardware_report
from ailen.domain.enums import DeviceProfile
from ailen.domain.models import CpuInfo, MemoryInfo


class TestDiagnostics(unittest.TestCase):
    """Test suite for hardware diagnostics."""

    def setUp(self):
        self.diagnostics = HardwareDiagnostics()

    def test_run_diagnostics(self):
        report = self.diagnostics.run()
        self.assertIsNotNone(report.cpu)
        self.assertIsNotNone(report.memory)
        self.assertIsNotNone(report.disk)
        self.assertIsNotNone(report.os)
        self.assertIsInstance(report.recommended_profile, DeviceProfile)

        formatted = format_hardware_report(report)
        self.assertIn("AILEN HARDWARE REPORT", formatted)
        self.assertIn("RECOMMENDED PROFILE", formatted)

    def test_profile_recommendations(self):
        # 2 GB class -> SATELLITE
        mem_2gb = MemoryInfo(total_mb=2048.0, available_mb=1024.0)
        cpu_2c = CpuInfo(cores_logical=2, cores_physical=2)
        self.assertEqual(self.diagnostics.recommend_profile(mem_2gb, cpu_2c), DeviceProfile.SATELLITE)

        # 4 GB class -> CLOUD
        mem_4gb = MemoryInfo(total_mb=4096.0, available_mb=2500.0)
        self.assertEqual(self.diagnostics.recommend_profile(mem_4gb, cpu_2c), DeviceProfile.CLOUD)

        # 8 GB class (Banghó) -> HYBRID
        mem_8gb = MemoryInfo(total_mb=8192.0, available_mb=6000.0)
        cpu_4c = CpuInfo(cores_logical=4, cores_physical=4)
        self.assertEqual(self.diagnostics.recommend_profile(mem_8gb, cpu_4c), DeviceProfile.HYBRID)

        # 32 GB workstation -> LAN_BRAIN
        mem_32gb = MemoryInfo(total_mb=32768.0, available_mb=28000.0)
        cpu_12c = CpuInfo(cores_logical=12, cores_physical=6)
        self.assertEqual(self.diagnostics.recommend_profile(mem_32gb, cpu_12c), DeviceProfile.LAN_BRAIN)


if __name__ == "__main__":
    unittest.main()

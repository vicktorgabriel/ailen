"""Unit tests for version resolution."""

import unittest

from ailen.version import __version__, get_version


class TestVersion(unittest.TestCase):
    """Test suite for AILEN version resolution."""

    def test_version_format(self):
        ver = get_version()
        self.assertIsInstance(ver, str)
        self.assertTrue(len(ver) > 0)
        self.assertEqual(ver, __version__)


if __name__ == "__main__":
    unittest.main()

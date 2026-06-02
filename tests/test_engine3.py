import unittest
from unittest.mock import patch

from midi.engine3 import ENGINE3_INSTALL_HINT, ENGINE3_LABEL, detect_engine3_runtime


class Engine3RuntimeTest(unittest.TestCase):
    def test_detect_engine3_runtime_available_when_mido_is_installed(self):
        with patch("midi.engine3.importlib.util.find_spec", return_value=object()):
            status = detect_engine3_runtime()

        self.assertTrue(status.available)
        self.assertIsNone(status.executable)
        self.assertEqual(status.label, ENGINE3_LABEL)
        self.assertIn("Send backend active", status.status_text)

    def test_detect_engine3_runtime_missing_has_install_hint(self):
        with patch("midi.engine3.importlib.util.find_spec", return_value=None):
            status = detect_engine3_runtime()

        self.assertFalse(status.available)
        self.assertIsNone(status.executable)
        self.assertEqual(status.install_hint, ENGINE3_INSTALL_HINT)
        self.assertIn("mido", status.status_text)


if __name__ == "__main__":
    unittest.main()

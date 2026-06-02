import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from midi.engine3_native import Engine3Native, Engine3NativeError


class Engine3NativeTest(unittest.TestCase):
    def make_native(self) -> Engine3Native:
        helper_dir = tempfile.TemporaryDirectory()
        self.addCleanup(helper_dir.cleanup)
        helper_path = Path(helper_dir.name) / "taureon_midi_capture.exe"
        helper_path.write_text("stub", encoding="utf-8")
        return Engine3Native(helper_path)

    def test_list_inputs_parses_json_payload(self):
        native = self.make_native()

        with patch(
            "midi.engine3_native.subprocess.run",
            return_value=Mock(
                returncode=0,
                stdout='{"inputs":[{"index":2,"name":"minilogue xd","manufacturer_id":66}]}',
                stderr="",
            ),
        ):
            devices = native.list_inputs()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].index, 2)
        self.assertEqual(devices[0].name, "minilogue xd")
        self.assertEqual(devices[0].manufacturer_id, 66)

    def test_list_inputs_reports_timeout_cleanly(self):
        native = self.make_native()

        with patch(
            "midi.engine3_native.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["helper", "--list-json"], timeout=8),
        ):
            with self.assertRaisesRegex(Engine3NativeError, "timed out after 8s"):
                native.list_inputs()

    def test_list_inputs_reports_invalid_json_cleanly(self):
        native = self.make_native()

        with patch(
            "midi.engine3_native.subprocess.run",
            return_value=Mock(returncode=0, stdout="not-json", stderr=""),
        ):
            with self.assertRaisesRegex(Engine3NativeError, "returned invalid JSON"):
                native.list_inputs()


if __name__ == "__main__":
    unittest.main()

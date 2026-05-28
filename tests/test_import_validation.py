import tempfile
import unittest
from pathlib import Path

from librarian.import_validation import INCOMPATIBLE, INVALID, UNKNOWN, validate_import_path


class ImportValidationTest(unittest.TestCase):
    def test_unknown_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sound.txt"
            path.write_text("not a synth file", encoding="utf-8")
            result = validate_import_path(path)
            self.assertEqual(result.status, INCOMPATIBLE)
            self.assertFalse(result.sendable)

    def test_corrupt_program_zip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.mnlgxdprog"
            path.write_bytes(b"not a zip")
            result = validate_import_path(path)
            self.assertEqual(result.status, INVALID)
            self.assertFalse(result.sendable)

    def test_non_program_syx(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "unknown.syx"
            path.write_bytes(b"\xf0\x42\x30\x00\xf7")
            result = validate_import_path(path)
            self.assertEqual(result.status, UNKNOWN)
            self.assertFalse(result.sendable)

    def test_invalid_syx_without_f0_f7(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "invalid.syx"
            path.write_bytes(b"not sysex")
            result = validate_import_path(path)
            self.assertEqual(result.status, INVALID)
            self.assertFalse(result.sendable)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from xd_formats.filename_utils import safe_filename, unique_path


class FilenameSanitizeTest(unittest.TestCase):
    def test_safe_filename(self):
        self.assertEqual(safe_filename("Dark Pad"), "Dark Pad")
        self.assertEqual(safe_filename("Pad/Lead:*?"), "Pad_Lead___")
        self.assertEqual(safe_filename("", fallback="Slot_001"), "Slot_001")

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            first = directory / "Dark Pad.mnlgxdprog"
            first.write_text("", encoding="utf-8")
            self.assertEqual(unique_path(directory, "Dark Pad", ".mnlgxdprog").name, "Dark Pad (2).mnlgxdprog")


if __name__ == "__main__":
    unittest.main()

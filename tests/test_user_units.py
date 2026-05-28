import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from librarian.user_units import import_user_unit, scan_user_units


class UserUnitsTest(unittest.TestCase):
    def test_import_nested_mnlgxdunit_metadata(self):
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "revfx",
                "api": "1.0-0",
                "dev_id": 0,
                "prg_id": 0,
                "version": "1.0",
                "name": "freeverb",
                "num_param": 0,
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "freeverb.mnlgxdunit"
            library = Path(temp_dir) / "library"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("freeverb/manifest.json", json.dumps(manifest))
                archive.writestr("freeverb/payload.bin", b"UREVpayload")

            imported = import_user_unit(source, library)
            scanned = scan_user_units(library)

            self.assertEqual(imported.name, "freeverb")
            self.assertEqual(imported.kind, "user-fx")
            self.assertEqual(imported.module, "revfx")
            self.assertEqual(imported.compatibility, "compatible")
            self.assertEqual(scanned[0].status, "imported successfully")


if __name__ == "__main__":
    unittest.main()

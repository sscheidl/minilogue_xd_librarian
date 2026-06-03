import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from devices.korg_minilogue_xd.logue_unit_header import (
    COMPATIBILITY_UNKNOWN,
    COMPATIBLE_WITH_XD,
    parse_logue_unit_header,
)
from librarian.user_units import import_user_unit, scan_user_units


def write_unit(path: Path, manifest: dict, payload: bytes = b"UOSCpayload") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{path.stem}/manifest.json", json.dumps(manifest))
        archive.writestr(f"{path.stem}/payload.bin", payload)


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
            write_unit(source, manifest, b"UREVpayload")

            imported = import_user_unit(source, library)
            scanned = scan_user_units(library)

            self.assertEqual(imported.name, "freeverb")
            self.assertEqual(imported.kind, "user-fx")
            self.assertEqual(imported.module, "revfx")
            self.assertEqual(imported.compatibility, COMPATIBLE_WITH_XD)
            self.assertEqual(scanned[0].status, "local file")

    def test_user_unit_header_short_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "short.mnlgxdunit"
            path.write_bytes(b"xd")

            imported = import_user_unit(path, Path(temp_dir) / "library")

            self.assertEqual(imported.status, "invalid container/header")
            self.assertEqual(imported.compatibility, COMPATIBILITY_UNKNOWN)

    def test_user_unit_header_valid_osc(self):
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "osc",
                "api": "1.1-0",
                "dev_id": 11,
                "prg_id": 22,
                "version": "2.0",
                "name": "Bright OSC",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bright.mnlgxdunit"
            write_unit(path, manifest, b"UOSCpayload")

            header = parse_logue_unit_header(path)

            self.assertEqual(header.unit_type, "osc")
            self.assertEqual(header.unit_name, "Bright OSC")
            self.assertEqual(header.developer_id, 11)
            self.assertEqual(header.unit_id, 22)
            self.assertEqual(header.compatibility, COMPATIBLE_WITH_XD)
            self.assertFalse(header.hardware_sendable)

    def test_user_unit_header_valid_fx(self):
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "delayfx",
                "api": "1.0-0",
                "dev_id": 1,
                "unit_id": 2,
                "version": "1.0",
                "name": "Tape Delay",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "delay.mnlgxdunit"
            write_unit(path, manifest, b"UDELpayload")

            imported = import_user_unit(path, Path(temp_dir) / "library")

            self.assertEqual(imported.kind, "user-fx")
            self.assertEqual(imported.module, "delfx")
            self.assertEqual(imported.compatibility, COMPATIBLE_WITH_XD)

    def test_user_unit_unknown_type(self):
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "samplepack",
                "api": "1.0-0",
                "version": "1.0",
                "name": "Unknown Unit",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "unknown.mnlgxdunit"
            write_unit(path, manifest, b"U???payload")

            imported = import_user_unit(path, Path(temp_dir) / "library")

            self.assertEqual(imported.kind, "user-unit")
            self.assertEqual(imported.module, "samplepack")
            self.assertEqual(imported.compatibility, COMPATIBILITY_UNKNOWN)

    def test_user_unit_unknown_compatibility_not_sendable(self):
        manifest = {
            "header": {
                "platform": "logue-sdk",
                "module": "osc",
                "api": "1.0-0",
                "version": "1.0",
                "name": "Generic Unit",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "generic.mnlgxdunit"
            write_unit(path, manifest, b"UOSCpayload")

            header = parse_logue_unit_header(path)

            self.assertEqual(header.compatibility, COMPATIBILITY_UNKNOWN)
            self.assertFalse(header.hardware_sendable)


if __name__ == "__main__":
    unittest.main()

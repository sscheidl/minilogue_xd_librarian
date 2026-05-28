import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from xd_formats import (
    export_programs_as_mnlgxdprog,
    import_sysex_programs,
    load_mnlgxdlib,
    load_mnlgxdprog,
    load_mnlgxdunit,
    read_program_name,
    rename_program,
    save_mnlgxdlib,
    save_mnlgxdunit,
    write_program_name,
    write_sysex_programs,
)


FIXTURES = Path(__file__).resolve().parents[1] / "libraries"


class XDFormatTest(unittest.TestCase):
    def setUp(self):
        if not FIXTURES.exists():
            self.skipTest("local Korg fixtures are not available")

    def test_load_library_and_read_names(self):
        library = load_mnlgxdlib(FIXTURES / "All Presets.mnlgxdlib")

        self.assertEqual(len(library.programs), 500)
        self.assertEqual(library.programs[0].name, "Replicant xd")
        self.assertEqual(len(library.programs[0].prog_bin), 1024)
        self.assertEqual(library.programs[0].prog_bin[:4], b"PROG")

    def test_clean_dump_decodes_to_library_programs(self):
        library = load_mnlgxdlib(FIXTURES / "All Presets.mnlgxdlib")
        programs = import_sysex_programs(FIXTURES / "All Presets_CleanDump.syx")

        self.assertEqual(len(programs), 500)
        self.assertEqual(programs[0].prog_bin, library.programs[0].prog_bin)
        self.assertEqual(programs[499].prog_bin, library.programs[499].prog_bin)

    def test_addinfo_is_not_imported_as_program_dump(self):
        programs = import_sysex_programs(FIXTURES / "All Presets_AddInfo.syx")

        self.assertEqual(programs, [])

    def test_program_and_library_roundtrip(self):
        library = load_mnlgxdlib(FIXTURES / "All Presets.mnlgxdlib")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exported = export_programs_as_mnlgxdprog(library, [0], temp_path)
            program = load_mnlgxdprog(exported[0])
            self.assertEqual(program.prog_bin, library.programs[0].prog_bin)

            rename_program(library, 0, "Short Name")
            self.assertEqual(read_program_name(library.programs[0].prog_bin), "Short Name")

            syx_path = temp_path / "library.syx"
            write_sysex_programs(library.programs[:2], syx_path)
            imported = import_sysex_programs(syx_path)
            self.assertEqual([program.name for program in imported], ["Short Name", library.programs[1].name])

            lib_path = temp_path / "roundtrip.mnlgxdlib"
            save_mnlgxdlib(library, lib_path)
            reloaded = load_mnlgxdlib(lib_path)
            self.assertEqual(reloaded.programs[0].name, "Short Name")

    def test_write_program_name_only_changes_name_range(self):
        program = load_mnlgxdlib(FIXTURES / "All Presets.mnlgxdlib").programs[0]
        renamed = write_program_name(program.prog_bin, "ABCDEFGHIJKLMNO")

        self.assertEqual(read_program_name(renamed), "ABCDEFGHIJKL")
        self.assertEqual(renamed[:4], program.prog_bin[:4])
        self.assertEqual(renamed[16:], program.prog_bin[16:])


class XDUnitFormatTest(unittest.TestCase):
    def test_unit_roundtrip(self):
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "osc",
                "api": "1.0-0",
                "dev_id": 1,
                "prg_id": 2,
                "version": "1.6-1",
                "name": "testosc",
                "num_param": 1,
                "params": [["Shape", 0, 100, "%"]],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "testosc.mnlgxdunit"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("testosc/manifest.json", json.dumps(manifest))
                archive.writestr("testosc/payload.bin", b"UOSCpayload")

            unit = load_mnlgxdunit(path)
            self.assertEqual(unit.name, "testosc")
            self.assertEqual(unit.payload_signature, "UOSC")
            self.assertEqual(unit.warnings, [])

            out_path = Path(temp_dir) / "saved.mnlgxdunit"
            save_mnlgxdunit(unit, out_path)
            reloaded = load_mnlgxdunit(out_path)
            self.assertEqual(reloaded.params[0].name, "Shape")


if __name__ == "__main__":
    unittest.main()

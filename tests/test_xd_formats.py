import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from xd_formats import (
    XDProgram,
    decode_current_program_dump,
    encode_current_program_dump,
    encode_program_dump,
    export_programs_as_mnlgxdprog,
    import_current_program_from_bytes,
    import_sysex_programs,
    import_sysex_programs_from_bytes,
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
from xd_formats.sysex_codec import encode_7bit_packed


FIXTURES = Path(__file__).resolve().parents[1] / "libraries"


def make_prog_bin(name: str) -> bytes:
    data = bytearray(1024)
    data[:4] = b"PROG"
    data[4:16] = name.encode("latin-1")[:12].ljust(12, b" ")
    return bytes(data)


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

    def test_load_program_zip_without_file_information(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "single.mnlgxdprog"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Prog_000.prog_bin", make_prog_bin("4Voice NK"))

            program = load_mnlgxdprog(path)

            self.assertEqual(program.name, "4Voice NK")
            self.assertEqual(program.prog_bin[:4], b"PROG")

    def test_load_library_zip_falls_back_to_sorted_prog_bins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "library.mnlgxdlib"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Prog_002.prog_bin", make_prog_bin("Third"))
                archive.writestr("Prog_000.prog_bin", make_prog_bin("First"))
                archive.writestr("Prog_001.prog_bin", make_prog_bin("Second"))
                archive.writestr("FileInformation.xml", b"not xml")

            library = load_mnlgxdlib(path)

            self.assertEqual([program.name for program in library.programs], ["First", "Second", "Third"])


class LiveSysexImportTest(unittest.TestCase):
    @staticmethod
    def make_program(name: str = "LiveName") -> XDProgram:
        prog_bin = bytearray(1024)
        prog_bin[:4] = b"PROG"
        prog_bin[4:16] = name.encode("latin-1")[:12].ljust(12, b" ")
        return XDProgram(slot_index=1, name=name, prog_bin=bytes(prog_bin), source_type="test")

    def test_import_sysex_programs_from_bytes_ignores_non_program_commands(self):
        program = self.make_program("SlotTwo")
        slot_dump = encode_program_dump(program, 1)
        raw = bytes.fromhex("F0 42 30 00 01 51 44 F7") + slot_dump + bytes.fromhex("F0 42 30 00 01 51 51 F7")

        programs = import_sysex_programs_from_bytes(raw)

        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0].slot_index, 1)
        self.assertEqual(programs[0].name, "SlotTwo")

    def test_import_current_program_from_bytes(self):
        program = self.make_program("Current")
        current_dump = bytes.fromhex("F0 42 30 00 01 51 40") + encode_7bit_packed(program.prog_bin) + b"\xF7"

        decoded = import_current_program_from_bytes(current_dump)

        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.name, "Current")
        self.assertIsNone(decoded.slot_index)

    def test_encode_current_program_dump_has_no_slot_bytes(self):
        program = self.make_program("Buffer")

        current_dump = encode_current_program_dump(program)
        decoded = decode_current_program_dump(current_dump)

        self.assertEqual(current_dump[6], 0x40)
        self.assertEqual(current_dump[7:12], bytes.fromhex("00 50 52 4F 47"))
        self.assertEqual(len(current_dump), 1179)
        self.assertEqual(decoded.name, "Buffer")
        self.assertIsNone(decoded.slot_index)


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

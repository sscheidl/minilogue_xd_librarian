import tempfile
import unittest
from pathlib import Path

from xd_formats import XDProgram, analyze_sysex_file, encode_program_dump, parse_pocket_midi_text
from xd_formats.pocket_midi import analyze_pocket_midi_text, export_individual_programs


FIXTURES = Path(__file__).resolve().parents[1] / "libraries"


def make_prog_bin(name_bytes: bytes) -> bytes:
    data = bytearray(1024)
    data[:4] = b"PROG"
    data[4:16] = name_bytes[:12].ljust(12, b" ")
    return bytes(data)


class PocketMidiImportTest(unittest.TestCase):
    def test_hex_token_parsing_ignores_text_and_realtime(self):
        parsed = parse_pocket_midi_text("noise F8 F0 42 30 00 01 51 51 F7 0x40 ignored")

        self.assertEqual(parsed.raw_bytes, bytes.fromhex("F8 F0 42 30 00 01 51 51 F7"))
        self.assertIn("noise", parsed.ignored_tokens)
        self.assertIn("0x40", parsed.ignored_tokens)

    def test_extracts_and_counts_commands_from_pocket_text(self):
        text = "F8 F0 42 30 00 01 51 51 F7\nF0 42 30 00 01 51 44 F7"

        analysis = analyze_pocket_midi_text(text)

        self.assertEqual(len(analysis.messages), 2)
        self.assertEqual(analysis.command_counts[0x51], 1)
        self.assertEqual(analysis.command_counts[0x44], 1)

    def test_name_extraction_ignores_embedded_nulls(self):
        program = XDProgram(
            slot_index=0,
            name="Replicant",
            prog_bin=make_prog_bin(b"Rep\x00licant \x00"),
            source_type="test",
        )
        raw = encode_program_dump(program, 0)

        analysis = analyze_pocket_midi_text(" ".join(f"{byte:02X}" for byte in raw))

        self.assertEqual(analysis.bank_programs[0].name, "Replicant")
        self.assertEqual(analysis.bank_programs[0].slot_index, 0)

    def test_existing_clean_dump_is_complete_500_bank(self):
        path = FIXTURES / "All Presets_CleanDump.syx"
        if not path.exists():
            self.skipTest("clean dump fixture unavailable")

        analysis = analyze_sysex_file(path)
        validation = analysis.validate_bank()

        self.assertEqual(analysis.command_counts[0x4C], 500)
        self.assertTrue(validation.complete)
        self.assertEqual(validation.missing_slots, ())
        self.assertEqual(validation.duplicate_slots, ())
        self.assertEqual(analysis.bank_only_bytes(), path.read_bytes())

    def test_export_individual_programs(self):
        program = XDProgram(
            slot_index=1,
            name="TyoCityLoo",
            prog_bin=make_prog_bin(b"TyoCityLoo"),
            source_type="test",
        )
        analysis = analyze_pocket_midi_text(" ".join(f"{byte:02X}" for byte in encode_program_dump(program, 1)))
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = export_individual_programs(analysis, temp_dir)

            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].name, "002_TyoCityLoo.syx")
            self.assertEqual(paths[0].read_bytes(), analysis.bank_programs[0].raw)


if __name__ == "__main__":
    unittest.main()

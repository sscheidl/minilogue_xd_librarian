import unittest

from devices.korg_minilogue_xd.sysex import classify_xd_sysex


class XDSysexClassificationTest(unittest.TestCase):
    def test_program_dump_with_slot(self):
        result = classify_xd_sysex(bytes.fromhex("F0 42 30 00 01 51 4C 73 03 F7"))

        self.assertEqual(result.label, "program-data-dump-with-slot")
        self.assertEqual(result.slot_index, 499)
        self.assertTrue(result.sendable_program)

    def test_current_program_dump(self):
        result = classify_xd_sysex(bytes.fromhex("F0 42 30 00 01 51 40 F7"))

        self.assertEqual(result.label, "current-program-data-dump")
        self.assertTrue(result.sendable_program)

    def test_unknown_commands_are_preserved_as_unknown(self):
        cases = {
            0x44: "unknown-index-data",
            0x45: "unknown-sequencer-index-data",
            0x51: "unknown-global-data",
        }
        for command, label in cases.items():
            with self.subTest(command=command):
                result = classify_xd_sysex(bytes([0xF0, 0x42, 0x30, 0x00, 0x01, 0x51, command, 0xF7]))
                self.assertEqual(result.label, label)
                self.assertFalse(result.sendable_program)


if __name__ == "__main__":
    unittest.main()

import unittest

from devices.korg_minilogue_xd.sysex import classify_xd_sysex, summarize_xd_sysex_stream
from midi.sysex_requests import (
    build_all_programs_request,
    request_current_program,
    request_program_slot,
    slot_to_lsb_msb,
)


class SysexRequestsTest(unittest.TestCase):
    def test_current_program_request(self):
        self.assertEqual(request_current_program(), bytes.fromhex("F0 42 30 00 01 51 10 00 F7"))
        self.assertEqual(
            request_current_program(trailing_zero=False),
            bytes.fromhex("F0 42 30 00 01 51 10 F7"),
        )

    def test_all_programs_request(self):
        self.assertEqual(build_all_programs_request(), bytes.fromhex("F0 42 30 00 01 51 0E F7"))

    def test_program_slot_request(self):
        cases = {
            0: (0x00, 0x00),
            99: (0x63, 0x00),
            100: (0x64, 0x00),
            127: (0x7F, 0x00),
            128: (0x00, 0x01),
            149: (0x15, 0x01),
            499: (0x73, 0x03),
        }
        for slot, pair in cases.items():
            with self.subTest(slot=slot):
                self.assertEqual(slot_to_lsb_msb(slot), pair)
                self.assertEqual(
                    request_program_slot(slot),
                    bytes([0xF0, 0x42, 0x30, 0x00, 0x01, 0x51, 0x1C, pair[0], pair[1], 0x00, 0xF7]),
                )
                self.assertEqual(
                    request_program_slot(slot, trailing_zero=False),
                    bytes([0xF0, 0x42, 0x30, 0x00, 0x01, 0x51, 0x1C, pair[0], pair[1], 0xF7]),
                )

    def test_program_slot_range(self):
        for slot in (-1, 500):
            with self.subTest(slot=slot):
                with self.assertRaises(ValueError):
                    request_program_slot(slot)

    def test_write_ack_classification(self):
        raw = bytes.fromhex("F0 42 30 00 01 51 23 F7")

        info = classify_xd_sysex(raw)

        self.assertEqual(info.command, 0x23)
        self.assertEqual(info.label, "write-ack")
        self.assertFalse(info.sendable_program)
        self.assertEqual(summarize_xd_sysex_stream(raw)["0x23 write ack"], 1)


if __name__ == "__main__":
    unittest.main()

import unittest

from librarian.sysex_tools import build_records, split_sysex_stream


class SysexToolsTest(unittest.TestCase):
    def test_split_multiple_messages(self):
        data = bytes([0xF0, 0x42, 0x01, 0xF7, 0xF0, 0x42, 0x02, 0xF7])
        self.assertEqual(len(split_sysex_stream(data)), 2)

    def test_korg_record(self):
        record = build_records(bytes([0xF0, 0x42, 0x30, 0xF7]))[0]
        self.assertTrue(record.is_korg)
        self.assertEqual(record.length, 4)

    def test_raw_unknown_file_is_preserved(self):
        record = build_records(b"not sysex")[0]
        self.assertEqual(record.dump_type, "raw-unknown-file")
        self.assertEqual(record.raw, b"not sysex")


if __name__ == "__main__":
    unittest.main()

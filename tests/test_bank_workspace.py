import unittest

from librarian.bank_workspace import OfflineBank
from librarian.models import SysexRecord
from xd_formats import XDProgram


def make_program(name: str, slot_index: int = 0) -> XDProgram:
    prog_bin = bytearray(1024)
    prog_bin[:4] = b"PROG"
    prog_bin[4:16] = name.encode("latin-1")[:12].ljust(12, b" ")
    return XDProgram(slot_index=slot_index, name=name, prog_bin=bytes(prog_bin), source_type="test")


class BankWorkspaceTest(unittest.TestCase):
    def test_move_changes_model_order_and_rewrites_target_slot_header(self):
        bank = OfflineBank()
        bank.load_programs([make_program("One"), make_program("Two")], "test", "test")

        bank.move(0, 9)

        self.assertEqual(bank.slots[9].name, "One")
        self.assertEqual(bank.raw_for_slot(9)[6:10], bytes.fromhex("4C 09 00 00"))
        self.assertEqual(bank.slots[9].raw[6:10], bytes.fromhex("4C 09 00 00"))
        self.assertEqual(bank.slots[9].status, "Modified in editor")

    def test_export_selected_after_move_uses_current_slot_header(self):
        bank = OfflineBank()
        bank.load_programs([make_program("One")], "test", "test")
        bank.move(0, 9)

        data = bank.export_selected_bytes([9])

        self.assertEqual(data[6:10], bytes.fromhex("4C 09 00 00"))

    def test_load_programs_by_slot_uses_dump_slot_numbers(self):
        bank = OfflineBank()
        programs = [make_program("SlotTen", 9), make_program("SlotOne", 0)]

        bank.load_programs_by_slot(programs, "capture", "Received")

        self.assertEqual(bank.slots[0].name, "SlotOne")
        self.assertEqual(bank.slots[9].name, "SlotTen")
        self.assertEqual(bank.slots[9].raw[6:10], bytes.fromhex("4C 09 00 00"))

    def test_merge_programs_preserves_existing_captured_slots(self):
        bank = OfflineBank()
        bank.merge_programs([make_program("SlotOne", 0)], "capture", "Received", status="Captured")

        merged = bank.merge_programs([make_program("SlotTen", 9)], "capture", "Received", status="Captured")

        self.assertEqual(merged, 1)
        self.assertEqual(bank.slots[0].name, "SlotOne")
        self.assertEqual(bank.slots[9].name, "SlotTen")
        self.assertEqual(bank.slots[0].status, "Captured")
        self.assertEqual(bank.slots[9].status, "Captured")

    def test_raw_sysex_records_are_reheadered_after_move(self):
        bank = OfflineBank()
        raw = bytes.fromhex("F0 42 30 00 01 51 4C 00 00 00") + (b"\x00" * 12) + b"\xF7"
        bank.load_records(
            [SysexRecord(1, raw, len(raw), 0x42, True, "program", "hash")],
            "raw",
        )

        bank.move(0, 9)
        data = bank.export_selected_bytes([9])

        self.assertEqual(data[6:10], bytes.fromhex("4C 09 00 00"))
        self.assertEqual(bank.slots[9].raw[6:10], bytes.fromhex("4C 09 00 00"))

    def test_status_transitions_for_import_edit_send_and_error(self):
        bank = OfflineBank()
        bank.load_programs([make_program("One")], "test", "test", status="Imported")
        self.assertEqual(bank.slots[0].status, "Imported")

        bank.rename(0, "Renamed")
        self.assertEqual(bank.slots[0].status, "Modified in editor")

        bank.mark_sent([0])
        self.assertEqual(bank.slots[0].status, "Sent to XD")

        bank.mark_error([0], "send failed")
        self.assertEqual(bank.slots[0].status, "Error")
        self.assertEqual(bank.slots[0].notes, "send failed")

    def test_multi_copy_paste_preserves_order_and_rewrites_headers(self):
        bank = OfflineBank()
        bank.load_programs(
            [make_program("One"), make_program("Two"), make_program("Three")],
            "test",
            "test",
        )

        copied = bank.copy_indices([0, 1])
        pasted = bank.paste_many(9)

        self.assertEqual(copied, 2)
        self.assertEqual(pasted, 2)
        self.assertEqual([bank.slots[9].name, bank.slots[10].name], ["One", "Two"])
        self.assertEqual(bank.slots[9].raw[6:10], bytes.fromhex("4C 09 00 00"))
        self.assertEqual(bank.slots[10].raw[6:10], bytes.fromhex("4C 0A 00 00"))

    def test_insert_many_shifts_model_and_rewrites_headers(self):
        bank = OfflineBank()
        bank.load_programs(
            [make_program("One"), make_program("Two"), make_program("Three")],
            "test",
            "test",
        )
        bank.copy_indices([0])

        inserted = bank.insert_many(2)

        self.assertEqual(inserted, 1)
        self.assertEqual([bank.slots[index].name for index in range(4)], ["One", "Two", "One", "Three"])
        self.assertEqual(bank.slots[2].raw[6:10], bytes.fromhex("4C 02 00 00"))
        self.assertEqual(bank.slots[3].raw[6:10], bytes.fromhex("4C 03 00 00"))
        self.assertEqual(bank.slots[2].status, "Modified in editor")
        self.assertEqual(bank.slots[3].status, "Modified in editor")

    def test_clear_uses_verified_init_template(self):
        bank = OfflineBank()
        bank.load_programs([make_program("Init Progr"), make_program("One")], "test", "test")

        cleared = bank.clear_slots([1])

        self.assertTrue(cleared)
        self.assertEqual(bank.slots[1].name, "Init")
        self.assertEqual(bank.slots[1].status, "Modified in editor")
        self.assertEqual(bank.slots[1].raw[6:10], bytes.fromhex("4C 01 00 00"))

    def test_clear_without_init_template_fails_without_emptying_slot(self):
        bank = OfflineBank()
        bank.load_programs([make_program("One")], "test", "test")

        cleared = bank.clear_slots([0])

        self.assertFalse(cleared)
        self.assertEqual(bank.slots[0].name, "One")
        self.assertTrue(bank.slots[0].raw)


if __name__ == "__main__":
    unittest.main()

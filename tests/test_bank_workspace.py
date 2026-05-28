import unittest

from librarian.bank_workspace import OfflineBank
from librarian.models import SysexRecord


def record(index: int, payload: bytes) -> SysexRecord:
    return SysexRecord(
        index=index,
        raw=payload,
        length=len(payload),
        manufacturer_id=0x42,
        is_korg=True,
        dump_type="possible-program-dump",
        sha256=f"hash-{index}",
    )


class BankWorkspaceTest(unittest.TestCase):
    def test_rename_copy_paste_and_undo(self):
        bank = OfflineBank()
        bank.load_records([record(1, b"abc")], "fixture")
        bank.rename(0, "Bass")
        bank.copy(0)
        bank.paste(1)

        self.assertEqual(bank.slots[1].name, "Bass")
        self.assertTrue(bank.undo())
        self.assertEqual(bank.slots[1].status, "empty")

    def test_swap(self):
        bank = OfflineBank()
        bank.load_records([record(1, b"a"), record(2, b"b")], "fixture")
        first_hash = bank.slots[0].sha256
        bank.swap(0, 1)
        self.assertEqual(bank.slots[1].sha256, first_hash)


if __name__ == "__main__":
    unittest.main()

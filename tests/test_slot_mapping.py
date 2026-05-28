import unittest

from devices.korg_minilogue_xd.slot_mapping import map_slot


class SlotMappingTest(unittest.TestCase):
    def test_required_slot_mappings(self):
        cases = [
            (0, "001", "A001"),
            (1, "002", "A002"),
            (99, "100", "A100"),
            (100, "101", "B001"),
            (199, "200", "B100"),
            (200, "201", "C001"),
            (399, "400", "D100"),
            (400, "401", "E001"),
            (499, "500", "E100"),
        ]
        for index, display_number, bank_slot in cases:
            with self.subTest(index=index):
                mapped = map_slot(index)
                self.assertEqual(mapped.display_number_text, display_number)
                self.assertEqual(mapped.bank_slot_text, bank_slot)

    def test_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            map_slot(-1)
        with self.assertRaises(ValueError):
            map_slot(500)


if __name__ == "__main__":
    unittest.main()

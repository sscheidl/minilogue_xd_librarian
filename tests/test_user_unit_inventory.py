import unittest

from devices.korg_minilogue_xd.user_unit_inventory import UserUnitInventoryReader
from devices.korg_minilogue_xd.user_unit_protocol import (
    parse_module_status_output,
    parse_probe_summary,
)
from devices.korg_minilogue_xd.user_unit_transport import (
    InventoryCancelledError,
    InventoryTimeoutError,
)


SUMMARY_OUTPUT = """
> Device: minilogue xd
> System version: 2.10
> Logue API version: 1.01-0
> Available modules:

Modulation FX: [ slot_count: 16, max_payload_size: 8180, max_load_size: 6144 ]
Delay FX: [ slot_count: 8, max_payload_size: 16368, max_load_size: 12288 ]
Reverb FX: [ slot_count: 8, max_payload_size: 16368, max_load_size: 12288 ]
Oscillator: [ slot_count: 16, max_payload_size: 36848, max_load_size: 32768 ]
""".strip()


class FakeInventoryTransport:
    def __init__(self, module_outputs):
        self.module_outputs = module_outputs
        self.cancelled = False
        self.calls = []

    def cancel(self):
        self.cancelled = True

    def resolve_port_indices(self, input_name, output_name):
        self.calls.append(("resolve", input_name, output_name))
        return 2, 2

    def probe_summary(self, input_index, output_index):
        self.calls.append(("summary", input_index, output_index))
        if self.cancelled:
            raise InventoryCancelledError("Inventory read cancelled.")
        return SUMMARY_OUTPUT

    def probe_module(self, module, input_index, output_index):
        self.calls.append(("module", module, input_index, output_index))
        if self.cancelled:
            raise InventoryCancelledError("Inventory read cancelled.")
        result = self.module_outputs[module]
        if isinstance(result, Exception):
            raise result
        return result


class UserUnitInventoryTest(unittest.TestCase):
    def make_reader(self, **module_outputs):
        defaults = {
            "osc": "> Oscillator status:\n[0]: free.\n",
            "modfx": '> Modulation FX status:\n[0]: "Ensemble" v1.00-0 api:1.01-0 did:00000000 uid:00000000\n',
            "delfx": '> Delay FX status:\n[0]: "Tape Echo" v1.01-0 api:1.01-0 did:00000000 uid:00000010\n',
            "revfx": '> Reverb FX status:\n[0]: "Cloud Hall" v1.02-0 api:1.01-0 did:00000001 uid:00000020\n',
        }
        defaults.update(module_outputs)
        transport = FakeInventoryTransport(defaults)
        reader = UserUnitInventoryReader(
            "minilogue xd SOUND",
            "minilogue xd SOUND",
            transport=transport,
        )
        return reader, transport

    def test_empty_osc_slot_response(self):
        parsed = parse_module_status_output("> Oscillator status:\n[0]: free.\n")

        self.assertEqual(parsed[0].slot_index, 1)
        self.assertFalse(parsed[0].occupied)
        self.assertIsNone(parsed[0].display_name)

    def test_installed_osc_slot_metadata(self):
        reader, _transport = self.make_reader(
            osc='> Oscillator status:\n[0]: "Waves" v1.00-0 api:1.00-0 did:00000000 uid:00000000\n'
        )

        slots = reader.read_oscillator_slots()

        self.assertEqual(slots[0].slot_key, "osc-01")
        self.assertEqual(slots[0].status, "Installed")
        self.assertEqual(slots[0].display_name, "Waves")
        self.assertEqual(slots[0].unit_version, "1.00-0")
        self.assertEqual(slots[0].api_version, "1.00-0")

    def test_installed_mod_fx_slot_metadata(self):
        reader, _transport = self.make_reader()

        slots = reader.read_mod_fx_slots()

        self.assertEqual(slots[0].slot_key, "modfx-01")
        self.assertEqual(slots[0].display_name, "Ensemble")
        self.assertEqual(slots[0].developer_id, "00000000")

    def test_installed_delay_fx_slot_metadata(self):
        reader, _transport = self.make_reader()

        slots = reader.read_delay_fx_slots()

        self.assertEqual(slots[0].slot_key, "delfx-01")
        self.assertEqual(slots[0].display_name, "Tape Echo")
        self.assertEqual(slots[0].unit_id, "00000010")

    def test_installed_reverb_fx_slot_metadata(self):
        reader, _transport = self.make_reader()

        slots = reader.read_reverb_fx_slots()

        self.assertEqual(slots[0].slot_key, "revfx-01")
        self.assertEqual(slots[0].display_name, "Cloud Hall")
        self.assertEqual(slots[0].unit_id, "00000020")

    def test_unknown_inventory_response(self):
        parsed = parse_module_status_output("> Oscillator status:\n[0]: ???\n")

        self.assertEqual(parsed[0].slot_index, 1)
        self.assertIsNone(parsed[0].occupied)
        self.assertIn("Unrecognized slot status format.", parsed[0].warnings)

    def test_inventory_timeout(self):
        reader, _transport = self.make_reader(
            osc=InventoryTimeoutError("Timed out while running probe -m osc.")
        )

        with self.assertRaises(InventoryTimeoutError):
            reader.read_oscillator_slots()

    def test_inventory_cancel(self):
        reader, _transport = self.make_reader()
        reader.cancel()

        with self.assertRaises(InventoryCancelledError):
            reader.read_inventory()

    def test_probe_summary_parses_module_counts(self):
        summary = parse_probe_summary(SUMMARY_OUTPUT)

        self.assertEqual(summary.device_name, "minilogue xd")
        self.assertEqual(summary.system_version, "2.10")
        self.assertEqual(summary.logue_api_version, "1.01-0")
        self.assertEqual(summary.modules["osc"].slot_count, 16)
        self.assertEqual(summary.modules["delfx"].slot_count, 8)


if __name__ == "__main__":
    unittest.main()

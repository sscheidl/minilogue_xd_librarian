import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from devices.korg_minilogue_xd.unit_types import UnitModule
from devices.korg_minilogue_xd.unit_validator import UserUnitValidator
from devices.korg_minilogue_xd.unit_workspace import UserUnitWorkspace
from devices.korg_minilogue_xd.user_unit_inventory import UserUnitSlotInfo


def write_unit(path: Path, manifest: dict, payload: bytes = b"UOSCpayload") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{path.stem}/manifest.json", json.dumps(manifest))
        archive.writestr(f"{path.stem}/payload.bin", payload)


class UnitValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = UserUnitValidator()

    def test_valid_osc_assigns_to_osc_slot(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "osc", "api": "1.0-0", "version": "1.0-0", "name": "Bright", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bright.mnlgxdunit"
            write_unit(path, manifest, b"UOSCpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.OSC, destination_slot=0)
        self.assertTrue(result.ok)
        self.assertEqual(result.unit.module, UnitModule.OSC)

    def test_valid_modfx_assigns_to_modfx_slot(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "modfx", "api": "1.0-0", "version": "1.0-0", "name": "Phase", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "phase.mnlgxdunit"
            write_unit(path, manifest, b"UMODpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.MOD_FX, destination_slot=0)
        self.assertTrue(result.ok)
        self.assertEqual(result.unit.module, UnitModule.MOD_FX)

    def test_valid_delfx_assigns_to_delay_slot(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "delfx", "api": "1.0-0", "version": "1.0-0", "name": "Tape", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tape.mnlgxdunit"
            write_unit(path, manifest, b"UDELpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.DELAY_FX, destination_slot=0)
        self.assertTrue(result.ok)
        self.assertEqual(result.unit.module, UnitModule.DELAY_FX)

    def test_valid_revfx_assigns_to_reverb_slot(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "revfx", "api": "1.0-0", "version": "1.0-0", "name": "Cloud", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cloud.mnlgxdunit"
            write_unit(path, manifest, b"UREVpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.REVERB_FX, destination_slot=0)
        self.assertTrue(result.ok)
        self.assertEqual(result.unit.module, UnitModule.REVERB_FX)

    def test_osc_rejected_for_fx_slots(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "osc", "api": "1.0-0", "version": "1.0-0", "name": "Bright", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bright.mnlgxdunit"
            write_unit(path, manifest, b"UOSCpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.DELAY_FX, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("Detected unit type", result.user_message)

    def test_wrong_platform_rejected(self):
        manifest = {"header": {"platform": "nts-1", "module": "osc", "api": "1.0-0", "version": "1.0-0", "name": "Bright", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bright.mnlgxdunit"
            write_unit(path, manifest, b"UOSCpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.OSC, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("not minilogue xd", result.user_message)

    def test_missing_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.mnlgxdunit"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("broken/payload.bin", b"UOSCpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.OSC, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("manifest.json", result.user_message)

    def test_missing_payload_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.mnlgxdunit"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("broken/manifest.json", json.dumps({"header": {}}))
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.OSC, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("payload.bin", result.user_message)

    def test_invalid_zip_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.mnlgxdunit"
            path.write_bytes(b"not a zip")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.OSC, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("ZIP container", result.user_message)

    def test_manifest_payload_mismatch_rejected(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "revfx", "api": "1.0-0", "version": "1.0-0", "name": "Cloud", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cloud.mnlgxdunit"
            write_unit(path, manifest, b"UDELpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.REVERB_FX, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("Manifest module and payload magic", result.user_message)

    def test_unknown_module_rejected(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "samplepack", "api": "1.0-0", "version": "1.0-0", "name": "Unknown", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "unknown.mnlgxdunit"
            write_unit(path, manifest, b"UOSCpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.OSC, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("unknown module type", result.user_message.lower())

    def test_api_major_mismatch_rejected(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "osc", "api": "2.0-0", "version": "1.0-0", "name": "Bright", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bright.mnlgxdunit"
            write_unit(path, manifest, b"UOSCpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.OSC, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("Unsupported API major", result.user_message)

    def test_api_minor_too_new_rejected(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "osc", "api": "1.2-0", "version": "1.0-0", "name": "Bright", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bright.mnlgxdunit"
            write_unit(path, manifest, b"UOSCpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.OSC, destination_slot=0)
        self.assertFalse(result.ok)
        self.assertIn("Unsupported API minor", result.user_message)

    def test_slot_limits(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "revfx", "api": "1.0-0", "version": "1.0-0", "name": "Cloud", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cloud.mnlgxdunit"
            write_unit(path, manifest, b"UREVpayload")
            result = self.validator.validate_for_destination(path=path, destination_module=UnitModule.REVERB_FX, destination_slot=8)
        self.assertFalse(result.ok)
        self.assertIn("outside the valid range", result.user_message)

    def test_pending_does_not_overwrite_hardware_state(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "osc", "api": "1.0-0", "version": "1.0-0", "name": "Bright", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "bright.mnlgxdunit"
            library = temp_path / "library"
            state_path = temp_path / "user_unit_slots.json"
            write_unit(source, manifest, b"UOSCpayload")
            workspace = UserUnitWorkspace(library_dir=library, state_path=state_path, validator=self.validator)
            workspace.set_hardware_inventory({
                "osc-01": UserUnitSlotInfo(
                    module="osc",
                    category="User OSC",
                    slot_key="osc-01",
                    slot_index=1,
                    occupied=True,
                    status="Installed",
                    display_name="Installed OSC",
                    unit_name="Installed OSC",
                    unit_version="1.0-0",
                    api_version="1.0-0",
                    sdk_version=None,
                    developer_id="00000000",
                    unit_id="00000000",
                    target_platform="minilogue xd",
                    compatibility="Unknown",
                    payload_size=None,
                    checksum=None,
                    source="hardware_inventory",
                    raw_metadata=None,
                    raw_protocol_command=None,
                    raw_metadata_length=None,
                    read_timestamp=None,
                    device_name="minilogue xd",
                    system_version="2.10",
                    logue_api_version="1.01-0",
                )
            })
            result = self.validator.validate_for_destination(path=source, destination_module=UnitModule.OSC, destination_slot=0)
            workspace.assign_pending(module=UnitModule.OSC, slot_index=0, unit=result.unit)
        self.assertEqual(workspace.slot_state("osc-01").installed_on_xd.display_name, "Installed OSC")
        self.assertEqual(workspace.slot_state("osc-01").pending_assignment.display_name, "Bright")

    def test_replace_pending_status(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "osc", "api": "1.0-0", "version": "1.0-0", "name": "Bright", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "bright.mnlgxdunit"
            library = temp_path / "library"
            state_path = temp_path / "user_unit_slots.json"
            write_unit(source, manifest, b"UOSCpayload")
            workspace = UserUnitWorkspace(library_dir=library, state_path=state_path, validator=self.validator)
            workspace.slot_state("osc-01").installed_on_xd = UserUnitSlotInfo(
                module="osc", category="User OSC", slot_key="osc-01", slot_index=1, occupied=True, status="Installed",
                display_name="Installed OSC", unit_name="Installed OSC", unit_version="1.0-0", api_version="1.0-0",
                sdk_version=None, developer_id="00000000", unit_id="00000000", target_platform="minilogue xd",
                compatibility="Unknown", payload_size=None, checksum=None, source="hardware_inventory",
                raw_metadata=None, raw_protocol_command=None, raw_metadata_length=None, read_timestamp=None,
                device_name="minilogue xd", system_version="2.10", logue_api_version="1.01-0"
            )
            result = self.validator.validate_for_destination(path=source, destination_module=UnitModule.OSC, destination_slot=0)
            workspace.assign_pending(module=UnitModule.OSC, slot_index=0, unit=result.unit)
        self.assertIsNotNone(workspace.slot_state("osc-01").pending_assignment)
        self.assertTrue(workspace.slot_state("osc-01").installed_on_xd.occupied)

    def test_clear_pending_assignment(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "osc", "api": "1.0-0", "version": "1.0-0", "name": "Bright", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "bright.mnlgxdunit"
            library = temp_path / "library"
            state_path = temp_path / "user_unit_slots.json"
            write_unit(source, manifest, b"UOSCpayload")
            workspace = UserUnitWorkspace(library_dir=library, state_path=state_path, validator=self.validator)
            result = self.validator.validate_for_destination(path=source, destination_module=UnitModule.OSC, destination_slot=0)
            workspace.assign_pending(module=UnitModule.OSC, slot_index=0, unit=result.unit)
            workspace.clear_pending_assignment(module=UnitModule.OSC, slot_index=0)
        self.assertIsNone(workspace.slot_state("osc-01").pending_assignment)

    def test_reconcile_pending_with_matching_hardware_clears_pending(self):
        manifest = {"header": {"platform": "minilogue-xd", "module": "osc", "api": "1.0-0", "version": "1.1-0", "name": "HUMN", "num_param": 0, "params": []}}
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "humn.mnlgxdunit"
            library = temp_path / "library"
            state_path = temp_path / "user_unit_slots.json"
            write_unit(source, manifest, b"UOSCpayload")
            workspace = UserUnitWorkspace(library_dir=library, state_path=state_path, validator=self.validator)
            result = self.validator.validate_for_destination(path=source, destination_module=UnitModule.OSC, destination_slot=15)
            workspace.assign_pending(module=UnitModule.OSC, slot_index=15, unit=result.unit)
            workspace.set_hardware_inventory({
                "osc-16": UserUnitSlotInfo(
                    module="osc", category="User OSC", slot_key="osc-16", slot_index=16, occupied=True, status="Installed",
                    display_name="HUMN", unit_name="HUMN", unit_version="1.1-0", api_version="1.0-0",
                    sdk_version=None, developer_id="00000000", unit_id="00000000", target_platform="minilogue xd",
                    compatibility="Unknown", payload_size=None, checksum=None, source="hardware_inventory",
                    raw_metadata=None, raw_protocol_command=None, raw_metadata_length=None, read_timestamp=None,
                    device_name="minilogue xd", system_version="2.10", logue_api_version="1.01-0"
                )
            })

            changed = workspace.reconcile_pending_with_hardware()

        self.assertTrue(changed)
        self.assertIsNone(workspace.slot_state("osc-16").pending_assignment)


if __name__ == "__main__":
    unittest.main()

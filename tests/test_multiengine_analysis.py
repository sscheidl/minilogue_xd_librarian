import unittest

from devices.korg_minilogue_xd.multiengine_analysis import (
    MultiengineRef,
    MultiengineReport,
    analyze_multiengine_refs,
    report_text,
)
from devices.korg_minilogue_xd.user_unit_inventory import (
    UserUnitInventorySnapshot,
    UserUnitSlotInfo,
)
from xd_formats import XDProgram


class MultiengineAnalysisTest(unittest.TestCase):
    @staticmethod
    def make_program(
        name: str,
        slot_index: int,
        *,
        multi_type: int = 0,
        user_osc_index: int = 0,
    ) -> XDProgram:
        prog_bin = bytearray(1024)
        prog_bin[:4] = b"PROG"
        prog_bin[4:16] = name.encode("latin-1", errors="replace")[:12].ljust(12, b" ")
        prog_bin[38] = multi_type
        prog_bin[41] = user_osc_index
        return XDProgram(
            slot_index=slot_index,
            name=name,
            prog_bin=bytes(prog_bin),
            source_type="test",
        )

    @staticmethod
    def make_inventory_snapshot() -> UserUnitInventorySnapshot:
        return UserUnitInventorySnapshot(
            input_port_name="minilogue xd SOUND",
            output_port_name="minilogue xd SOUND",
            device_name="minilogue xd",
            system_version="2.10",
            logue_api_version="1.01-0",
            read_timestamp="2026-06-09T12:00:00+00:00",
            module_info={},
            slots={
                "osc-04": UserUnitSlotInfo(
                    module="osc",
                    category="User OSC",
                    slot_key="osc-04",
                    slot_index=4,
                    occupied=True,
                    status="Installed",
                    display_name="Bent",
                    unit_name="Bent",
                    unit_version="1.00-3",
                    api_version="1.00-0",
                    sdk_version=None,
                    developer_id="00000000",
                    unit_id="00000010",
                    target_platform="minilogue xd",
                    compatibility="Unknown",
                    payload_size=None,
                    checksum=None,
                    source="hardware_inventory",
                    raw_metadata=None,
                    raw_protocol_command="logue-cli probe -m osc -i 1 -o 2",
                    raw_metadata_length=None,
                    read_timestamp="2026-06-09T12:00:00+00:00",
                    device_name="minilogue xd",
                    system_version="2.10",
                    logue_api_version="1.01-0",
                )
            },
            warnings=(),
        )

    def test_analyze_empty_program_list_returns_empty_report(self):
        report = analyze_multiengine_refs([])

        self.assertEqual(report.total_programs, 0)
        self.assertEqual(report.multiengine_count, 0)
        self.assertEqual(report.builtin_osc_count, 0)
        self.assertEqual(report.refs_by_user_osc, {})
        self.assertEqual(report.unresolved, [])

    def test_report_text_handles_empty_report(self):
        report = MultiengineReport(total_programs=0, multiengine_count=0, builtin_osc_count=0)

        text = report_text(report)

        self.assertIsInstance(text, str)
        self.assertIn("Programs using User OSC: 0", text)
        self.assertIn("User OSC References", text)
        self.assertIn("Unresolved", text)

    def test_report_text_without_inventory_snapshot(self):
        report = MultiengineReport(
            total_programs=1,
            multiengine_count=1,
            builtin_osc_count=0,
            refs_by_user_osc={
                3: [
                    MultiengineRef(
                        slot_index=41,
                        slot_display="042",
                        program_name="BassLead",
                        user_osc_index=3,
                        user_osc_display="User OSC 04",
                    )
                ]
            },
        )

        text = report_text(report, inventory_snapshot=None, source_label="capture.syx")

        self.assertIn("Source: capture.syx", text)
        self.assertIn("inventory unavailable", text)
        self.assertIn("042 | BassLead", text)

    def test_report_counts_are_initialized_correctly(self):
        programs = [
            self.make_program("NoisePad", 0, multi_type=0),
            self.make_program("VpmLead", 1, multi_type=1),
            self.make_program("UserBass", 2, multi_type=2, user_osc_index=3),
        ]

        report = analyze_multiengine_refs(programs)

        self.assertEqual(report.total_programs, 3)
        self.assertEqual(report.multiengine_count, 1)
        self.assertEqual(report.builtin_osc_count, 2)
        self.assertEqual(len(report.refs_by_user_osc[3]), 1)

    def test_analyze_known_user_osc_offset_groups_reference(self):
        report = analyze_multiengine_refs(
            [self.make_program("BassLead", 41, multi_type=2, user_osc_index=3)]
        )

        self.assertIn(3, report.refs_by_user_osc)
        ref = report.refs_by_user_osc[3][0]
        self.assertEqual(ref.slot_index, 41)
        self.assertEqual(ref.slot_display, "042")
        self.assertEqual(ref.program_name, "BassLead")
        self.assertEqual(ref.user_osc_index, 3)
        self.assertEqual(ref.user_osc_display, "User OSC 04")

    def test_report_text_uses_inventory_name_when_available(self):
        report = analyze_multiengine_refs(
            [self.make_program("BassLead", 41, multi_type=2, user_osc_index=3)]
        )

        text = report_text(report, inventory_snapshot=self.make_inventory_snapshot())

        self.assertIn("User OSC 04 | Bent | 1 program(s)", text)


if __name__ == "__main__":
    unittest.main()

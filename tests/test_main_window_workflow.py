import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from app.main_window import MainWindow
from app.version import APP_VERSION
from midi.receiver import QueuedMidiMessage
from librarian.models import SysexRecord
from xd_formats import XDProgram, encode_current_program_dump, encode_program_dump
from xd_formats.sysex_codec import encode_7bit_packed


class FailingSender:
    def send_messages(self, *_args, **_kwargs):
        raise RuntimeError("boom")


class SuccessfulSender:
    def __init__(self):
        self.messages = []

    def send_messages(self, messages, _delay_ms, progress):
        self.messages = list(messages)
        for index, message in enumerate(messages, start=1):
            progress(index, len(messages), len(message))
        return len(messages)


class FakeReceiver:
    def __init__(self, sender=None):
        self.sender = sender or FailingSender()

    is_open = True

    def make_sender(self):
        return self.sender

    def close_ports(self):
        pass


class FakeNativeCaptureWorker:
    instances = []

    def __init__(self, port_name, events, **kwargs):
        self.port_name = port_name
        self.events = events
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.wait_called = False
        FakeNativeCaptureWorker.instances.append(self)

    @property
    def is_running(self):
        return self.started and not self.stopped

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def wait_stopped(self, timeout=2.0):
        self.wait_called = True
        self.stopped = True
        return True


def wait_for_tk(root, predicate, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)


class MainWindowWorkflowTest(unittest.TestCase):
    def make_window(self):
        root = tk.Tk()
        root.withdraw()
        with patch("app.main_window.load_settings", return_value={"auto_connect": False}):
            window = MainWindow(root)
        def _cleanup_root():
            try:
                if root.winfo_exists():
                    root.destroy()
            except tk.TclError:
                pass

        self.addCleanup(_cleanup_root)
        return window

    def test_send_failure_does_not_log_success_or_raise_name_error(self):
        window = self.make_window()
        window.receiver = FakeReceiver()
        window.output_port_var.set("out")
        record = SysexRecord(
            index=1,
            raw=b"\xf0\x42\x00\xf7",
            length=4,
            manufacturer_id=0x42,
            is_korg=True,
            dump_type="test",
            sha256="hash",
            notes="Test",
        )

        with (
            patch("app.main_window.messagebox.askyesno", return_value=True),
            patch("app.main_window.messagebox.showerror") as showerror,
            patch.object(window.logger, "error") as log_error,
        ):
            window.send_records([record], "test")
            wait_for_tk(window.root, lambda: window.current_sender is None)

        log = window.log_text.get("1.0", tk.END)
        self.assertIn("Send failed: boom", log)
        self.assertNotIn("Send complete:", log)
        log_error.assert_called()
        showerror.assert_called_once()
        self.assertIsNone(window.current_sender)

    def test_on_close_warns_for_unsaved_capture(self):
        window = self.make_window()
        window.sysex_buffer.add_message(b"\xf0\x42\x00\xf7", time.time())

        with patch("app.main_window.messagebox.askyesno", return_value=False) as ask:
            window.on_close()

        ask.assert_called_once()
        self.assertTrue(window.root.winfo_exists())

    def test_on_close_waits_for_native_capture_worker_shutdown(self):
        window = self.make_window()
        worker = FakeNativeCaptureWorker("in", window.native_capture_queue)
        worker.start()
        window.native_capture_worker = worker

        with patch("app.main_window.messagebox.askyesno", return_value=True):
            window.on_close()

        self.assertTrue(worker.stopped)
        self.assertTrue(worker.wait_called)

    def test_diagnostic_report_has_version(self):
        window = self.make_window()

        report = window.build_diagnostic_report()

        self.assertIn(f"Version: {APP_VERSION}", report)
        self.assertNotIn("Version: unknown", report)

    def test_v3_tabs_and_bank_columns(self):
        window = self.make_window()

        self.assertEqual(
            [window.tabs.tab(tab, "text") for tab in window.tabs.tabs()],
            ["Programs / Banks", "Transfer", "User OSC", "User FX", "Options"],
        )
        self.assertEqual(tuple(window.bank_tree["columns"]), ("slot", "name", "source", "status"))
        self.assertEqual(window.bank_count_var.get(), "500 / 500 shown")

    def test_transfer_tab_is_action_log_only(self):
        window = self.make_window()

        transfer_text = self.widget_texts(window.midi_tab)
        combo_children = [
            child
            for child in window.midi_tab.winfo_children()
            if child.winfo_class() == "TCombobox"
        ]

        self.assertIn("Transfer", transfer_text)
        self.assertIn("Receive SysEx", transfer_text)
        self.assertIn("Capture Bank Dump from XD", transfer_text)
        self.assertEqual(combo_children, [])
        self.assertNotIn("Inactivity finalize", transfer_text)
        self.assertNotIn("MIDI IN", transfer_text)
        self.assertNotIn("Import Program/Library", transfer_text)
        self.assertNotIn("Send Selected to XD", transfer_text)

    def test_transfer_capture_button_starts_manual_bank_receive(self):
        window = self.make_window()
        window.receiver = FakeReceiver()
        window.input_port_var.set("in")
        window.output_port_var.set("out")
        buttons = self.find_buttons_by_text(window.midi_tab, "Capture Bank Dump from XD")

        FakeNativeCaptureWorker.instances.clear()
        with (
            patch("app.main_window.Engine3SysexCaptureWorker", FakeNativeCaptureWorker),
            patch("app.main_window.detect_engine3_native_runtime", return_value=Mock(available=True, status_text="Native helper active")),
        ):
            buttons[0].invoke()

        self.assertEqual(window.receive_mode, "bank")
        self.assertEqual(FakeNativeCaptureWorker.instances[0].port_name, "in")
        self.assertTrue(FakeNativeCaptureWorker.instances[0].started)
        log = window.log_text.get("1.0", tk.END)
        self.assertIn("native dump listener started", log)
        self.assertIn("No data was sent", log)
        self.assertNotIn("TX FullBank slot", log)

    def test_receive_sysex_button_starts_generic_engine3_receive(self):
        window = self.make_window()
        window.receiver = FakeReceiver()
        window.input_port_var.set("in")
        buttons = self.find_buttons_by_text(window.midi_tab, "Receive SysEx")

        FakeNativeCaptureWorker.instances.clear()
        with (
            patch("app.main_window.Engine3SysexCaptureWorker", FakeNativeCaptureWorker),
            patch("app.main_window.detect_engine3_native_runtime", return_value=Mock(available=True, status_text="Native helper active")),
        ):
            buttons[0].invoke()

        self.assertEqual(window.receive_mode, "native_capture")
        self.assertTrue(FakeNativeCaptureWorker.instances[0].started)
        self.assertIn("Receive SysEx: native dump listener started", window.log_text.get("1.0", tk.END))

    def test_user_unit_trees_show_only_fixed_slots(self):
        window = self.make_window()

        osc_values = [window.user_osc_tree.item(item, "values") for item in window.user_osc_tree.get_children()]
        fx_values = [
            tree.item(item, "values")
            for tree in window.user_fx_trees.values()
            for item in tree.get_children()
        ]

        self.assertEqual(len(osc_values), 16)
        self.assertEqual(len(fx_values), 32)
        self.assertEqual(
            {key: len(tree.get_children()) for key, tree in window.user_fx_trees.items()},
            {"modfx": 16, "delfx": 8, "revfx": 8},
        )
        self.assertNotIn("Library", [values[0] for values in osc_values + fx_values])
        self.assertEqual(
            tuple(next(iter(window.user_fx_trees.values()))["columns"]),
            ("slot", "name", "type", "compatibility", "status"),
        )

    @staticmethod
    def make_program(name="LiveName", slot_index=1):
        prog_bin = bytearray(1024)
        prog_bin[:4] = b"PROG"
        prog_bin[4:16] = name.encode("latin-1")[:12].ljust(12, b" ")
        return XDProgram(slot_index=slot_index, name=name, prog_bin=bytes(prog_bin), source_type="test")

    def test_current_receive_updates_visible_workspace_entry(self):
        window = self.make_window()
        program = self.make_program("Current", None)
        raw = bytes.fromhex("F0 42 30 00 01 51 40") + encode_7bit_packed(program.prog_bin) + b"\xF7"

        window.receive_mode = "current_program"
        window.expected_cmd = 0x40
        window.apply_current_program_receive(raw)

        self.assertEqual(window.bank.slots[0].name, "Current")
        self.assertEqual(window.bank.slots[0].status, "Synced")
        self.assertIn("cmd=0x40", window.bank.slots[0].notes)

    def test_slot_receive_updates_target_bank_slot(self):
        window = self.make_window()
        program = self.make_program("SlotTwo", 1)
        raw = encode_program_dump(program, 1)

        window.receive_mode = "slot_program"
        window.expected_cmd = 0x4C
        window.expected_slot = 1
        window.apply_slot_program_receive(raw, 1)

        self.assertEqual(window.bank.slots[1].name, "SlotTwo")
        self.assertEqual(window.bank.slots[1].status, "Synced")
        self.assertIn("cmd=0x4C", window.bank.slots[1].notes)

    def test_bank_finalizer_ignores_non_program_commands(self):
        window = self.make_window()
        window.receive_mode = "bank"
        window.sysex_buffer.add_message(bytes.fromhex("F0 42 30 00 01 51 44 F7"), time.time())
        window.sysex_buffer.add_message(bytes.fromhex("F0 42 30 00 01 51 51 F7"), time.time())

        window.finalize_bank_receive()

        self.assertEqual(window.bank.slots[0].status, "empty")
        self.assertIn(
            "No program bank data received. Start the full program/all dump on the XD.",
            window.log_text.get("1.0", tk.END),
        )

    def test_bank_finalizer_loads_program_dumps(self):
        window = self.make_window()
        program = self.make_program("BankProg", 0)
        window.receive_mode = "bank"
        window.sysex_buffer.add_message(encode_program_dump(program, 0), time.time())

        window.finalize_bank_receive()

        self.assertEqual(window.bank.slots[0].name, "BankProg")
        self.assertEqual(window.bank.slots[0].status, "Captured")

    def test_bank_finalizer_places_captured_programs_by_slot_and_reports_count(self):
        window = self.make_window()
        program = self.make_program("SlotTen", 9)
        window.receive_mode = "bank"
        window.sysex_buffer.add_message(encode_program_dump(program, 9), time.time())

        window.finalize_bank_receive()

        self.assertEqual(window.bank.slots[9].name, "SlotTen")
        self.assertEqual(window.bank.slots[0].status, "empty")
        self.assertIn("Captured bank: 1/500 programs.", window.log_text.get("1.0", tk.END))

    def test_bank_finalizer_merges_split_dump_segments_without_clearing_previous_slots(self):
        window = self.make_window()
        window.receive_mode = "bank"
        window.sysex_buffer.add_message(encode_program_dump(self.make_program("SlotOne", 0), 0), time.time())
        window.sysex_buffer.finalize("timeout", time.time())
        window.finalize_bank_receive("timeout")

        window.sysex_buffer.add_message(encode_program_dump(self.make_program("SlotTen", 9), 9), time.time())
        window.sysex_buffer.finalize("inactivity", time.time())
        window.finalize_bank_receive("inactivity")

        self.assertEqual(window.bank.slots[0].name, "SlotOne")
        self.assertEqual(window.bank.slots[9].name, "SlotTen")
        self.assertIn("Captured bank: 2/500 programs.", window.log_text.get("1.0", tk.END))

    def test_bank_finalizer_segment_without_programs_does_not_clear_existing_capture(self):
        window = self.make_window()
        window.receive_mode = "bank"
        window.sysex_buffer.add_message(encode_program_dump(self.make_program("SlotOne", 0), 0), time.time())
        window.sysex_buffer.finalize("timeout", time.time())
        window.finalize_bank_receive("timeout")

        window.sysex_buffer.add_message(bytes.fromhex("F0 42 30 00 01 51 44 F7"), time.time())
        window.sysex_buffer.finalize("inactivity", time.time())
        window.finalize_bank_receive("inactivity")

        self.assertEqual(window.bank.slots[0].name, "SlotOne")
        self.assertIn("No new 0x4C program dumps in this capture segment.", window.log_text.get("1.0", tk.END))

    def test_native_capture_worker_disables_legacy_sysex_timeout_finalizer(self):
        window = self.make_window()
        worker = FakeNativeCaptureWorker("in", window.native_capture_queue)
        worker.start()
        window.native_capture_worker = worker
        window.sysex_buffer.add_message(encode_program_dump(self.make_program("SlotOne", 0), 0), time.time() - 10)
        window.inactivity_ms_var.set("1")
        window.max_timeout_s_var.set("1")

        window.check_capture_timeouts()

        self.assertTrue(window.sysex_buffer.capture.is_active)
        self.assertNotIn("Capture finalized by", window.log_text.get("1.0", tk.END))

    def test_incoming_sysex_capture_ignores_f8_realtime_bytes(self):
        window = self.make_window()
        raw = bytes.fromhex("F0 42 30 00 01 51 F8 44 F7")

        window.handle_midi_message(QueuedMidiMessage(message=None, raw=raw, message_type="sysex"))

        self.assertEqual(window.sysex_buffer.to_bytes(), bytes.fromhex("F0 42 30 00 01 51 44 F7"))

    def test_ctrl_z_undoes_bank_change(self):
        window = self.make_window()
        window.bank.load_programs([self.make_program("Before", 0)], "test", "test")
        window.bank.rename(0, "After")
        self.assertEqual(window.bank.slots[0].name, "After")

        window.undo_bank_key()

        self.assertEqual(window.bank.slots[0].name, "Before")

    def test_request_full_bank_starts_sequential_worker(self):
        window = self.make_window()
        window.receiver = FakeReceiver()
        window.input_port_var.set("in")
        window.output_port_var.set("out")

        with (
            patch("app.main_window.messagebox.askyesno", return_value=True),
            patch.object(window, "start_full_bank_sequential_worker") as start_worker,
        ):
            window.request_full_bank_from_xd()

        start_worker.assert_called_once()
        self.assertEqual(window.receive_mode, "full_bank_sequential")

    def test_sender_guard_prevents_parallel_send(self):
        window = self.make_window()
        window.current_sender = object()
        record = SysexRecord(
            index=1,
            raw=b"\xf0\x42\x00\xf7",
            length=4,
            manufacturer_id=0x42,
            is_korg=True,
            dump_type="test",
            sha256="hash",
            notes="Test",
        )

        with patch("app.main_window.messagebox.showwarning") as showwarning:
            window.send_records([record], "test")

        showwarning.assert_called_once()

    def test_send_selected_after_move_uses_new_slot_header_and_waits_for_ack(self):
        window = self.make_window()
        sender = SuccessfulSender()
        window.receiver = FakeReceiver(sender)
        window.output_port_var.set("out")
        window.bank.load_programs([self.make_program("Moved", 0)], "test", "test")
        window.bank.move(0, 9)
        window.refresh_bank_tree()
        window.bank_tree.selection_set(["9"])

        with patch("app.main_window.messagebox.askyesno", return_value=True):
            window.send_selected_bank_slots()
            wait_for_tk(window.root, lambda: window.current_sender is None)

        self.assertEqual(sender.messages[0][6:10], bytes.fromhex("4C 09 00 00"))
        self.assertEqual(window.bank.slots[9].status, "Modified in editor")
        window.handle_live_xd_sysex(bytes.fromhex("F0 42 30 00 01 51 23 F7"))
        self.assertEqual(window.bank.slots[9].status, "Sent to XD")

    def test_send_selected_to_buffer_uses_current_program_header(self):
        window = self.make_window()
        sender = SuccessfulSender()
        program = self.make_program("Buffer", 0)
        window.receiver = FakeReceiver(sender)
        window.output_port_var.set("out")
        window.bank.load_programs([program], "test", "test")
        window.refresh_bank_tree()
        window.bank_tree.selection_set(["0"])

        with patch("app.main_window.messagebox.askyesno", return_value=True):
            window.send_selected_to_buffer()
            wait_for_tk(window.root, lambda: window.current_sender is None)

        self.assertEqual(sender.messages, [encode_current_program_dump(program)])
        self.assertEqual(sender.messages[0][6], 0x40)
        self.assertEqual(sender.messages[0][7:12], bytes.fromhex("00 50 52 4F 47"))
        self.assertEqual(len(sender.messages[0]), 1179)

    def test_write_ack_without_pending_slot_is_logged(self):
        window = self.make_window()

        window.handle_live_xd_sysex(bytes.fromhex("F0 42 30 00 01 51 23 F7"))

        self.assertIn("Write ACK 0x23 received", window.log_text.get("1.0", tk.END))

    @staticmethod
    def widget_texts(parent):
        texts = []
        for child in parent.winfo_children():
            if "text" in child.keys():
                texts.append(child.cget("text"))
            child_texts = MainWindowWorkflowTest.widget_texts(child)
            if child_texts:
                texts.append(child_texts)
        return " ".join(texts)

    @staticmethod
    def find_buttons_by_text(parent, text):
        matches = []
        for child in parent.winfo_children():
            if child.winfo_class() == "TButton" and child.cget("text") == text:
                matches.append(child)
            matches.extend(MainWindowWorkflowTest.find_buttons_by_text(child, text))
        return matches


if __name__ == "__main__":
    unittest.main()

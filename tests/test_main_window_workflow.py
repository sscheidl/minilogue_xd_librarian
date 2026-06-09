import json
import os
import sys
import threading
import tempfile
import time
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from app.main_window import MainWindow
from app.version import APP_VERSION
from devices.korg_minilogue_xd.user_unit_inventory import UserUnitInventorySnapshot, UserUnitSlotInfo
from devices.korg_minilogue_xd.unit_types import UnitModule
from midi.capture_events import RawCaptureEvent
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
        if progress is not None:
            for index, message in enumerate(messages, start=1):
                progress(index, len(messages), len(message))
        return len(messages)


class FakeOutputPort:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


class FakeReceiver:
    def __init__(self, sender=None, output_port=None, is_open=True):
        self.sender = sender or FailingSender()
        self.output_name = None
        self.input_name = None
        self.output_port = output_port
        self._is_open = is_open

    @property
    def is_open(self):
        return self._is_open

    def open_ports(self, input_name, output_name):
        self.input_name = input_name
        self.output_name = output_name
        self._is_open = True

    def make_sender(self):
        return self.sender

    def close_ports(self):
        self._is_open = False


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


class FakeLogueCliTransport:
    calls = []

    def __init__(self, *_args, **_kwargs):
        pass

    def cancel(self):
        return None

    def resolve_port_indices(self, input_name, output_name):
        type(self).calls.append(("resolve", input_name, output_name))
        return 2, 2

    def load_unit_archive(self, unit_path, *, slot_index, input_index, output_index):
        type(self).calls.append(
            ("load", Path(unit_path).name, slot_index, input_index, output_index)
        )
        return "Load completed."

    def clear_slot(self, module, *, slot_index, input_index, output_index):
        type(self).calls.append(("clear", module, slot_index, input_index, output_index))
        return "Clear completed."


def wait_for_tk(root, predicate, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)


def write_user_unit_archive(path: Path, manifest: dict, payload: bytes) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{path.stem}/manifest.json", json.dumps(manifest))
        archive.writestr(f"{path.stem}/payload.bin", payload)


class MainWindowWorkflowTest(unittest.TestCase):
    def make_window(
        self,
        *,
        temp_path: Path | None = None,
        library_dir: Path | None = None,
        start_background_detection: bool = False,
    ):
        if temp_path is None:
            temp_dir = tempfile.TemporaryDirectory()
            self.addCleanup(temp_dir.cleanup)
            temp_path = Path(temp_dir.name)
        if library_dir is None:
            library_dir = temp_path / "user_units"
        library_dir.mkdir(parents=True, exist_ok=True)

        user_data_patcher = patch("app.main_window.user_data_dir", return_value=temp_path)
        user_units_patcher = patch("app.main_window.user_units_dir", return_value=library_dir)
        user_data_patcher.start()
        user_units_patcher.start()
        self.addCleanup(user_data_patcher.stop)
        self.addCleanup(user_units_patcher.stop)

        python_root = Path(sys.executable).resolve().parent
        os.environ["TCL_LIBRARY"] = (python_root / "tcl" / "tcl8.6").as_posix()
        os.environ["TK_LIBRARY"] = (python_root / "tcl" / "tk8.6").as_posix()
        try:
            root = tk.Tk()
        except tk.TclError:
            os.environ["TCL_LIBRARY"] = (python_root / "tcl" / "tcl8.6").as_posix()
            os.environ["TK_LIBRARY"] = (python_root / "tcl" / "tk8.6").as_posix()
            root = tk.Tk()
        root.withdraw()
        startup_detection_patcher = patch(
            "app.main_window.MainWindow.start_background_port_detection",
            new=(
                MainWindow.start_background_port_detection
                if start_background_detection
                else lambda self: None
            ),
        )
        startup_detection_patcher.start()
        self.addCleanup(startup_detection_patcher.stop)
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
            ["Edit", "Transfer", "MIDI Monitor", "User OSC", "User FX", "Options"],
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
        self.assertIn("Inactivity finalize", self.widget_texts(window.settings_tab))
        self.assertIn("Double-click program to send selected preset", self.widget_texts(window.settings_tab))

    def test_bank_view_has_play_preset_button_and_context_entry(self):
        window = self.make_window()

        self.assertIn("Play Preset", self.widget_texts(window.banks_tab))
        labels = [
            window.bank_context_menu.entrycget(index, "label")
            for index in range(window.bank_context_menu.index(tk.END) + 1)
            if window.bank_context_rules[index] != "separator"
        ]
        self.assertIn("Play Preset", labels)

    def test_midi_monitor_tab_has_local_filters(self):
        window = self.make_window()

        monitor_text = self.widget_texts(window.midi_monitor_tab)

        self.assertIn("Monitor Filters", monitor_text)
        self.assertIn("Notes", monitor_text)
        self.assertIn("Control Change", monitor_text)
        self.assertIn("Program Change", monitor_text)
        self.assertIn("Pitch Bend", monitor_text)
        self.assertIn("Aftertouch", monitor_text)
        self.assertIn("Active Sensing", monitor_text)
        self.assertIn("Clear Monitor", monitor_text)

    def test_midi_monitor_pending_lines_initialized_as_empty_list(self):
        window = self.make_window()

        self.assertIsInstance(window.midi_monitor_pending_lines, list)
        self.assertEqual(window.midi_monitor_pending_lines, [])

    def test_midi_monitor_defaults_to_korg_profile(self):
        window = self.make_window()

        self.assertEqual(window.current_midi_profile().profile_id, "korg_minilogue_xd")
        self.assertEqual(window.midi_profile_var.get(), "Korg Minilogue XD")

    def test_midi_monitor_logs_note_messages_independent_of_transfer_log_filters(self):
        window = self.make_window()
        window.show_sysex_only_var.set(True)
        window.show_note_controller_var.set(False)

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("90 3C 40"), message_type="note_on")
        )
        window.flush_midi_monitor()

        self.assertIn("Note On", window.midi_monitor_text.get("1.0", tk.END))
        self.assertNotIn("MIDI note_on", window.log_text.get("1.0", tk.END))

    def test_midi_monitor_uses_profile_name_for_filter_cutoff(self):
        window = self.make_window()

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("B0 2B 57"), message_type="control_change")
        )
        window.flush_midi_monitor()

        self.assertIn("Filter Cutoff", window.midi_monitor_text.get("1.0", tk.END))

    def test_midi_monitor_generic_profile_uses_general_midi_controller_names(self):
        window = self.make_window()
        window.select_midi_profile("generic_midi")

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("B0 07 64"), message_type="control_change")
        )
        window.flush_midi_monitor()

        self.assertIn("Channel Volume", window.midi_monitor_text.get("1.0", tk.END))

    def test_midi_monitor_program_change_is_one_based_without_99_limit(self):
        window = self.make_window()

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("C0 7F"), message_type="program_change")
        )
        window.flush_midi_monitor()

        self.assertIn("Program 128", window.midi_monitor_text.get("1.0", tk.END))

    def test_midi_monitor_program_change_uses_bank_context_for_minilogue_xd(self):
        window = self.make_window()

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("B0 00 00"), message_type="control_change")
        )
        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("B0 20 01"), message_type="control_change")
        )
        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("C0 04"), message_type="program_change")
        )
        window.flush_midi_monitor()

        monitor_output = window.midi_monitor_text.get("1.0", tk.END)
        self.assertIn("B005", monitor_output)
        self.assertIn("Program 105 / 500", monitor_output)

    def test_midi_monitor_program_change_can_be_filtered_separately(self):
        window = self.make_window()
        window.monitor_show_program_change_var.set(False)

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("C0 04"), message_type="program_change")
        )
        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("E0 00 40"), message_type="pitchwheel")
        )
        window.flush_midi_monitor()

        monitor_output = window.midi_monitor_text.get("1.0", tk.END)
        self.assertNotIn("Program Change", monitor_output)
        self.assertIn("Pitch Bend", monitor_output)

    def test_midi_monitor_aftertouch_can_be_filtered_separately(self):
        window = self.make_window()
        window.monitor_show_aftertouch_var.set(False)

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("D0 40"), message_type="aftertouch")
        )
        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("A0 3C 20"), message_type="polytouch")
        )
        window.flush_midi_monitor()

        self.assertEqual(window.midi_monitor_text.get("1.0", tk.END).strip(), "")

    def test_midi_monitor_hides_active_sensing_until_enabled(self):
        window = self.make_window()

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("FE"), message_type="active_sensing")
        )
        window.flush_midi_monitor()
        self.assertNotIn("active_sensing", window.midi_monitor_text.get("1.0", tk.END))

        window.monitor_show_active_sensing_var.set(True)
        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("FE"), message_type="active_sensing")
        )
        window.flush_midi_monitor()

        self.assertIn("Active Sensing", window.midi_monitor_text.get("1.0", tk.END))

    def test_midi_monitor_hides_cc63_in_simple_view_and_shows_it_in_technical_view(self):
        window = self.make_window()

        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("B0 3F 05"), message_type="control_change")
        )
        window.flush_midi_monitor()
        self.assertNotIn("CC63", window.midi_monitor_text.get("1.0", tk.END))

        window.monitor_show_technical_var.set(True)
        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("B0 3F 05"), message_type="control_change")
        )
        window.flush_midi_monitor()

        self.assertIn("control=63", window.midi_monitor_text.get("1.0", tk.END))

    def test_midi_monitor_toggle_pauses_display_only(self):
        window = self.make_window()
        window.monitor_show_sysex_var.set(True)
        window.monitor_enabled_var.set(False)
        window.update_monitor_toggle_text()
        raw = bytes.fromhex("F0 42 30 00 01 51 44 F7")

        window.handle_midi_message(QueuedMidiMessage(message=None, raw=raw, message_type="sysex"))
        window.flush_midi_monitor()

        self.assertEqual(window.midi_monitor_text.get("1.0", tk.END).strip(), "")
        self.assertEqual(window.sysex_buffer.to_bytes(), raw)

    def test_midi_monitor_toggle_opens_selected_ports_when_starting(self):
        window = self.make_window()
        window.receiver = FakeReceiver(is_open=False)
        window.monitor_enabled_var.set(False)
        window.update_monitor_toggle_text()
        window.input_port_map = {"1. in": "Synth In"}
        window.output_port_map = {"1. out": "Synth Out"}
        window.input_port_var.set("1. in")
        window.output_port_var.set("1. out")

        window.toggle_midi_monitoring()

        self.assertTrue(window.receiver.is_open)
        self.assertEqual(window.receiver.input_name, "Synth In")
        self.assertEqual(window.receiver.output_name, "Synth Out")
        self.assertIn("Monitor: running", window.midi_monitor_status_var.get())

    def test_midi_monitor_status_shows_waiting_when_enabled_without_open_ports(self):
        window = self.make_window()
        window.receiver = FakeReceiver(is_open=False)
        window.monitor_enabled_var.set(True)

        window.update_midi_monitor_status()

        self.assertIn("Monitor: waiting for MIDI", window.midi_monitor_status_var.get())

    def test_midi_monitor_copy_and_export_actions(self):
        window = self.make_window()
        window.handle_midi_message(
            QueuedMidiMessage(message=None, raw=bytes.fromhex("B0 2B 57"), message_type="control_change")
        )
        window.flush_midi_monitor()

        with tempfile.TemporaryDirectory() as temp_dir:
            txt_path = Path(temp_dir) / "monitor.txt"
            csv_path = Path(temp_dir) / "monitor.csv"
            with patch("app.main_window.filedialog.asksaveasfilename", side_effect=[str(txt_path), str(csv_path)]):
                window.copy_midi_monitor_to_clipboard()
                window.export_midi_monitor_txt()
                window.export_midi_monitor_csv()

            clipboard = window.root.clipboard_get()
            self.assertIn("Filter Cutoff", clipboard)
            self.assertIn("Filter Cutoff", txt_path.read_text(encoding="utf-8"))
            self.assertIn("profile_id", csv_path.read_text(encoding="utf-8"))

    def test_play_preset_warns_when_no_output_port_is_open(self):
        window = self.make_window()
        program = self.make_program("Preview", 0)
        receiver = FakeReceiver(output_port=None)
        receiver.output_name = None
        window.receiver = receiver
        window.output_port_var.set("")
        window.bank.load_programs([program], "test", "test")
        window.refresh_bank_tree()
        window.bank_tree.selection_set(["0"])

        with patch("app.main_window.messagebox.showwarning") as showwarning:
            window.play_selected_bank_preset()

        showwarning.assert_called_once_with(
            "No MIDI OUT",
            "No MIDI OUT port is open. Open a MIDI OUT port before using Play Preset.",
        )

    def test_play_preset_sends_audition_notes_and_all_notes_off(self):
        window = self.make_window()
        output_port = FakeOutputPort()
        sender = SuccessfulSender()
        receiver = FakeReceiver(sender, output_port=output_port)
        receiver.output_name = "out"
        window.receiver = receiver
        window.output_port_var.set("out")
        window.bank.load_programs([self.make_program("Preview", 0)], "test", "test")
        window.refresh_bank_tree()
        window.bank_tree.selection_set(["0"])

        with patch("app.main_window.time.sleep", return_value=None):
            window.play_selected_bank_preset()
            wait_for_tk(window.root, lambda: not window.audition_running)

        message_types = [message.type for message in output_port.messages]
        note_numbers = [message.note for message in output_port.messages if message.type == "note_on"]
        self.assertEqual(len(sender.messages), 1)
        self.assertEqual(sender.messages[0][6], 0x40)
        self.assertEqual(note_numbers, [36, 48, 55, 60, 64, 67, 72])
        self.assertEqual(message_types.count("note_on"), 7)
        self.assertEqual(message_types.count("note_off"), 7)
        self.assertEqual(message_types.count("control_change"), 1)
        self.assertEqual(output_port.messages[-1].control, 123)
        window.flush_midi_monitor()
        monitor_output = window.midi_monitor_text.get("1.0", tk.END)
        self.assertIn("SysEx Summary", monitor_output)
        self.assertIn("Note On", monitor_output)
        self.assertIn("cmd 0x40", monitor_output)
        self.assertIn("Audition: sent selected preset to XD edit buffer", window.log_text.get("1.0", tk.END))
        self.assertIn("Playing audition sequence for selected preset", window.log_text.get("1.0", tk.END))
        self.assertIn("Audition finished.", window.log_text.get("1.0", tk.END))

    def test_play_preset_button_is_disabled_during_audition(self):
        window = self.make_window()
        output_port = FakeOutputPort()
        receiver = FakeReceiver(SuccessfulSender(), output_port=output_port)
        receiver.output_name = "out"
        window.receiver = receiver
        window.output_port_var.set("out")
        window.bank.load_programs([self.make_program("Preview", 0)], "test", "test")
        window.refresh_bank_tree()
        window.bank_tree.selection_set(["0"])
        gate = threading.Event()

        def blocking_sleep(_seconds):
            gate.wait(timeout=1.0)

        with patch("app.main_window.time.sleep", side_effect=blocking_sleep):
            window.play_selected_bank_preset()
            wait_for_tk(window.root, lambda: window.audition_running)
            self.assertEqual(str(window.play_preset_buttons[0].cget("state")), tk.DISABLED)
            gate.set()
            wait_for_tk(window.root, lambda: not window.audition_running, timeout=2.0)

        self.assertEqual(str(window.play_preset_buttons[0].cget("state")), tk.NORMAL)

    def test_background_detection_preselects_port_2_minilogue_xd_pair(self):
        window = self.make_window()

        window.finish_background_port_detection(
            ["minilogue xd SOUND", "MIDIIN2 (minilogue xd) 1"],
            ["minilogue xd KBD/KNOB", "MIDIOUT2 (minilogue xd) 2"],
        )

        self.assertEqual(window.selected_input_port(), "MIDIIN2 (minilogue xd) 1")
        self.assertEqual(window.selected_output_port(), "MIDIOUT2 (minilogue xd) 2")
        self.assertIn("port-2 candidates", window.port_hint_var.get().lower())
        self.assertEqual(window.listen_status_var.get(), "minilogue xd detected. MIDI ports preselected.")

    def test_background_detection_warns_when_no_minilogue_xd_ports_exist(self):
        window = self.make_window()

        with (
            patch.object(window, "schedule_after") as schedule_after,
            patch("app.main_window.messagebox.showwarning") as showwarning,
        ):
            window.finish_background_port_detection(
                ["Generic USB MIDI In"],
                ["Generic USB MIDI Out"],
            )

        self.assertIsNone(window.selected_input_port())
        self.assertIsNone(window.selected_output_port())
        self.assertEqual(
            window.listen_status_var.get(),
            "Minilogue XD not detected. Please check MIDI connection.",
        )
        schedule_after.assert_called_once()
        delay_ms, callback = schedule_after.call_args.args
        self.assertEqual(delay_ms, 3000)
        showwarning.assert_not_called()

        with patch("app.main_window.messagebox.showwarning") as showwarning:
            callback()

        showwarning.assert_called_once_with(
            "Minilogue XD not detected",
            "Minilogue XD not detected. Please check MIDI connection.",
        )

    def test_port_name_detection_accepts_variant_windows_labels(self):
        self.assertTrue(MainWindow.is_minilogue_xd_port("KORG minilogue-xd"))
        self.assertTrue(MainWindow.is_sysex_candidate("MIDIIN2 (KORG minilogue-xd)"))
        self.assertTrue(MainWindow.is_sysex_candidate("MIDIOUT2 KORG minilogue xd"))
        self.assertFalse(MainWindow.is_sysex_candidate("MIDIIN1 (KORG minilogue-xd)"))

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
        self.assertEqual(
            tuple(next(iter(window.user_fx_trees.values()))["columns"]),
            ("slot", "name", "version"),
        )
        self.assertNotIn("file:", " ".join(window.user_osc_tree.get_children()))

    def test_user_unit_tabs_show_read_button_without_refresh(self):
        window = self.make_window()

        self.assertIn("Read from XD", self.widget_texts(window.user_osc_tab))
        self.assertIn("Read from XD", self.widget_texts(window.user_fx_tab))
        self.assertIn("Details", self.widget_texts(window.user_osc_tab))
        self.assertIn("Details", self.widget_texts(window.user_fx_tab))
        self.assertIn("Send to XD", self.widget_texts(window.user_osc_tab))
        self.assertIn("Send to XD", self.widget_texts(window.user_fx_tab))
        self.assertIn("Send ALL", self.widget_texts(window.user_osc_tab))
        self.assertIn("Send ALL", self.widget_texts(window.user_fx_tab))
        self.assertNotIn("Refresh", self.widget_texts(window.user_osc_tab))
        self.assertNotIn("Refresh", self.widget_texts(window.user_fx_tab))
        self.assertIn("MOD", self.widget_texts(window.user_fx_tab))
        self.assertIn("DELAY", self.widget_texts(window.user_fx_tab))
        self.assertIn("REVERB", self.widget_texts(window.user_fx_tab))
        self.assertNotIn("MOD FX", self.widget_texts(window.user_fx_tab))
        self.assertNotIn("DELAY FX", self.widget_texts(window.user_fx_tab))
        self.assertNotIn("REVERB FX", self.widget_texts(window.user_fx_tab))

    def test_import_user_unit_refuses_wrong_target_slot_type(self):
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "revfx",
                "api": "1.0-0",
                "version": "1.0",
                "name": "Cloud Verb",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "cloud.mnlgxdunit"
            write_user_unit_archive(source, manifest, b"UREVpayload")
            window = self.make_window(temp_path=temp_path, library_dir=temp_path / "user_units")
            window.user_osc_tree.selection_set(["osc-01"])

            with (
                patch("app.main_window.filedialog.askopenfilename", return_value=str(source)),
                patch("app.main_window.messagebox.showerror") as showerror,
            ):
                window.import_user_units()

        showerror.assert_called_once()
        self.assertIsNone(window.user_unit_workspace.slot_state("osc-01").pending_assignment)

    def test_load_selected_user_unit_slot_routes_expected_module(self):
        window = self.make_window()
        window.user_fx_trees["delfx"].selection_set(["delfx-03"])

        with patch.object(window, "activate_unit_slot") as activate:
            window.load_replace_selected_user_unit_slot()

        activate.assert_called_once_with(module=UnitModule.DELAY_FX, slot_index=2)

    def test_user_unit_tree_double_click_invokes_slot_activation(self):
        window = self.make_window()
        tree = window.user_fx_trees["revfx"]
        tree.identify_row = Mock(return_value="revfx-02")

        with patch.object(window, "load_replace_selected_user_unit_slot") as load:
            window.on_user_unit_tree_double_click(Mock(widget=tree, y=0))

        self.assertEqual(tree.selection(), ("revfx-02",))
        load.assert_called_once()

    def test_hardware_and_local_assignment_remain_distinct(self):
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "osc",
                "api": "1.0-0",
                "version": "1.0-0",
                "name": "Bright OSC",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            library_dir = temp_path / "user_units"
            library_dir.mkdir()
            write_user_unit_archive(library_dir / "bright.mnlgxdunit", manifest, b"UOSCpayload")
            window = self.make_window(temp_path=temp_path, library_dir=library_dir)
            result = window.user_unit_validator.validate_for_destination(
                path=library_dir / "bright.mnlgxdunit",
                destination_module=UnitModule.OSC,
                destination_slot=0,
            )
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.unit)
            window.user_unit_workspace.assign_pending(
                module=UnitModule.OSC,
                slot_index=0,
                unit=result.unit,
            )
            window.user_unit_slot_inventory["osc-01"] = UserUnitSlotInfo(
                module="osc",
                category="User OSC",
                slot_key="osc-01",
                slot_index=1,
                occupied=False,
                status="Empty",
                display_name=None,
                unit_name=None,
                unit_version=None,
                api_version=None,
                sdk_version=None,
                developer_id=None,
                unit_id=None,
                target_platform="minilogue xd",
                compatibility=None,
                payload_size=None,
                checksum=None,
                source="hardware_inventory",
                raw_metadata=b"[0]: free.",
                raw_protocol_command="logue-cli probe -m osc -i 2 -o 2",
                raw_metadata_length=10,
                read_timestamp="2026-06-07 17:00:00 CEST",
                device_name="minilogue xd",
                system_version="2.10",
                logue_api_version="1.01-0",
            )
            window.user_unit_workspace.set_hardware_inventory(window.user_unit_slot_inventory)
            window.refresh_user_units_trees()
            row = window.user_osc_tree.item("osc-01", "values")
            title, content = window.build_user_unit_details_dialog("osc-01")

        self.assertIsNotNone(window.user_unit_workspace.slot_state("osc-01").pending_assignment)
        self.assertEqual(row, ("User OSC 01", "Empty", "1.0-0"))
        self.assertEqual(title, "User OSC Details - Slot 01")
        self.assertIn("Hardware inventory", content)
        self.assertIn("Pending Local Assignment", content)
        pending_name = window.user_unit_workspace.slot_state("osc-01").pending_assignment.source_path.name
        self.assertIn(pending_name, content)

    def test_inventory_read_clears_matching_pending_assignment(self):
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "osc",
                "api": "1.0-0",
                "version": "1.1-0",
                "name": "HUMN",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            library_dir = temp_path / "user_units"
            library_dir.mkdir()
            source = temp_path / "humn.mnlgxdunit"
            write_user_unit_archive(source, manifest, b"UOSCpayload")
            window = self.make_window(temp_path=temp_path, library_dir=library_dir)
            result = window.user_unit_validator.validate_for_destination(
                path=source,
                destination_module=UnitModule.OSC,
                destination_slot=15,
            )
            self.assertTrue(result.ok)
            window.user_unit_workspace.assign_pending(
                module=UnitModule.OSC,
                slot_index=15,
                unit=result.unit,
            )
            snapshot = UserUnitInventorySnapshot(
                input_port_name="minilogue xd SOUND",
                output_port_name="minilogue xd SOUND",
                device_name="minilogue xd",
                system_version="2.10",
                logue_api_version="1.01-0",
                read_timestamp="2026-06-09T12:00:00+00:00",
                module_info={},
                slots={
                    "osc-16": UserUnitSlotInfo(
                        module="osc",
                        category="User OSC",
                        slot_key="osc-16",
                        slot_index=16,
                        occupied=True,
                        status="Installed",
                        display_name="HUMN",
                        unit_name="HUMN",
                        unit_version="1.1-0",
                        api_version="1.0-0",
                        sdk_version=None,
                        developer_id="00000000",
                        unit_id="00000000",
                        target_platform="minilogue xd",
                        compatibility="Unknown",
                        payload_size=None,
                        checksum=None,
                        source="hardware_inventory",
                        raw_metadata=b'[15]: "HUMN" v1.1-0 api:1.0-0 did:00000000 uid:00000000',
                        raw_protocol_command="logue-cli probe -m osc -i 2 -o 2",
                        raw_metadata_length=60,
                        read_timestamp="2026-06-09T12:00:00+00:00",
                        device_name="minilogue xd",
                        system_version="2.10",
                        logue_api_version="1.01-0",
                    )
                },
                warnings=(),
            )

            window.finish_user_unit_inventory_success(snapshot)
            row = window.user_osc_tree.item("osc-16", "values")

        self.assertIsNone(window.user_unit_workspace.slot_state("osc-16").pending_assignment)
        self.assertEqual(row, ("User OSC 16", "HUMN", "1.1-0"))
        self.assertIn(
            "Reconciled pending local User Unit state against current XD inventory.",
            window.log_text.get("1.0", tk.END),
        )

    def test_details_popup_model_for_empty_slot(self):
        window = self.make_window()
        window.user_unit_slot_inventory["osc-01"] = UserUnitSlotInfo(
            module="osc",
            category="User OSC",
            slot_key="osc-01",
            slot_index=1,
            occupied=False,
            status="Empty",
            display_name=None,
            unit_name=None,
            unit_version=None,
            api_version=None,
            sdk_version=None,
            developer_id=None,
            unit_id=None,
            target_platform="minilogue xd",
            compatibility=None,
            payload_size=None,
            checksum=None,
            source="hardware_inventory",
            raw_metadata=b"[0]: free.",
            raw_protocol_command="logue-cli probe -m osc -i 2 -o 2",
            raw_metadata_length=10,
            read_timestamp="2026-06-07 17:00:00 CEST",
            device_name="minilogue xd",
            system_version="2.10",
            logue_api_version="1.01-0",
        )
        window.user_unit_workspace.set_hardware_inventory(window.user_unit_slot_inventory)

        title, content = window.build_user_unit_details_dialog("osc-01")

        self.assertEqual(title, "User OSC Details - Slot 01")
        self.assertIn("Status: Empty on XD", content)
        self.assertIn("Read Source: minilogue xd via official logue-cli probe", content)
        self.assertIn("Pending Local Assignment\nStatus: None", content)

    def test_details_popup_model_for_installed_slot(self):
        window = self.make_window()
        window.user_unit_slot_inventory["modfx-07"] = UserUnitSlotInfo(
            module="modfx",
            category="Mod FX",
            slot_key="modfx-07",
            slot_index=7,
            occupied=True,
            status="Installed",
            display_name="Hera 2",
            unit_name="Hera 2",
            unit_version="2.00-0",
            api_version="1.01-0",
            sdk_version=None,
            developer_id="00000000",
            unit_id="00000000",
            target_platform="minilogue xd",
            compatibility="Unknown",
            payload_size=None,
            checksum=None,
            source="hardware_inventory",
            raw_metadata=b'[6]: "Hera 2" v2.00-0 api:1.01-0 did:00000000 uid:00000000',
            raw_protocol_command="logue-cli probe -m modfx -i 2 -o 2",
            raw_metadata_length=64,
            read_timestamp="2026-06-07 17:00:00 CEST",
            device_name="minilogue xd",
            system_version="2.10",
            logue_api_version="1.01-0",
        )
        window.user_unit_workspace.set_hardware_inventory(window.user_unit_slot_inventory)

        title, content = window.build_user_unit_details_dialog("modfx-07")

        self.assertEqual(title, "Mod FX Details - Slot 07")
        self.assertIn("Status: Installed on XD", content)
        self.assertIn("Display Name: Hera 2", content)
        self.assertIn("Developer ID: 00000000", content)

    def test_fx_selection_overrides_stale_osc_selection_for_details(self):
        window = self.make_window()
        window.user_osc_tree.selection_set(["osc-01"])
        window.user_osc_tree.focus("osc-01")
        window.on_user_unit_tree_select(Mock(widget=window.user_osc_tree))
        window.tabs.select(window.user_fx_tab)
        fx_tree = window.user_fx_trees["modfx"]
        fx_tree.selection_set(["modfx-07"])
        fx_tree.focus("modfx-07")
        window.on_user_unit_tree_select(Mock(widget=fx_tree))

        self.assertEqual(window.selected_user_unit_slot_key(), "modfx-07")
        self.assertEqual(window.user_osc_tree.selection(), ())
        title, _content = window.build_user_unit_details_dialog("modfx-07")
        self.assertEqual(title, "Mod FX Details - Slot 07")

    def test_fx_selection_overrides_stale_osc_selection_for_load(self):
        window = self.make_window()
        window.user_osc_tree.selection_set(["osc-01"])
        window.user_osc_tree.focus("osc-01")
        window.on_user_unit_tree_select(Mock(widget=window.user_osc_tree))
        window.tabs.select(window.user_fx_tab)
        fx_tree = window.user_fx_trees["delfx"]
        fx_tree.selection_set(["delfx-03"])
        fx_tree.focus("delfx-03")
        window.on_user_unit_tree_select(Mock(widget=fx_tree))

        with patch.object(window, "activate_unit_slot") as activate:
            window.load_replace_selected_user_unit_slot()

        activate.assert_called_once_with(module=UnitModule.DELAY_FX, slot_index=2)

    def test_send_selected_user_unit_to_xd_uses_logue_cli_load_and_clears_pending(self):
        FakeLogueCliTransport.calls = []
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "osc",
                "api": "1.0-0",
                "version": "1.2-3",
                "name": "Bright OSC",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            library_dir = temp_path / "user_units"
            library_dir.mkdir()
            source = temp_path / "bright.mnlgxdunit"
            write_user_unit_archive(source, manifest, b"UOSCpayload")
            window = self.make_window(temp_path=temp_path, library_dir=library_dir)
            result = window.user_unit_validator.validate_for_destination(
                path=source,
                destination_module=UnitModule.OSC,
                destination_slot=0,
            )
            self.assertTrue(result.ok)
            window.user_unit_workspace.assign_pending(
                module=UnitModule.OSC,
                slot_index=0,
                unit=result.unit,
            )
            window.refresh_user_units_trees()
            window.user_osc_tree.selection_set(["osc-01"])
            window.input_port_var.set("minilogue xd SOUND")
            window.output_port_var.set("minilogue xd SOUND")

            with (
                patch("app.main_window.LogueCliTransport", FakeLogueCliTransport),
                patch("app.main_window.messagebox.askyesno", return_value=True),
                patch.object(window, "schedule_after", side_effect=lambda _delay, callback: callback()),
                patch.object(window, "read_user_unit_inventory_from_xd") as auto_read,
                patch("app.main_window.messagebox.showwarning") as showwarning,
            ):
                window.send_selected_user_unit_to_xd()
                wait_for_tk(window.root, lambda: not window.user_unit_write_in_progress)

        self.assertEqual(
            FakeLogueCliTransport.calls,
            [
                ("resolve", "minilogue xd SOUND", "minilogue xd SOUND"),
                ("load", "bright.mnlgxdunit", 0, 2, 2),
            ],
        )
        self.assertIsNone(window.user_unit_workspace.slot_state("osc-01").pending_assignment)
        self.assertIn("Installed Bright OSC to User OSC 01 on XD.", window.log_text.get("1.0", tk.END))
        auto_read.assert_called_once()
        showwarning.assert_not_called()

    def test_send_selected_user_unit_to_xd_uses_logue_cli_clear_for_pending_clear(self):
        FakeLogueCliTransport.calls = []
        window = self.make_window()
        window.user_unit_workspace.mark_slot_for_clear(module=UnitModule.DELAY_FX, slot_index=2)
        window.refresh_user_units_trees()
        window.tabs.select(window.user_fx_tab)
        tree = window.user_fx_trees["delfx"]
        tree.selection_set(["delfx-03"])
        tree.focus("delfx-03")
        window.on_user_unit_tree_select(Mock(widget=tree))
        window.input_port_var.set("minilogue xd SOUND")
        window.output_port_var.set("minilogue xd SOUND")

        with (
            patch("app.main_window.LogueCliTransport", FakeLogueCliTransport),
            patch("app.main_window.messagebox.askyesno", return_value=True),
            patch.object(window, "schedule_after", side_effect=lambda _delay, callback: callback()),
            patch.object(window, "read_user_unit_inventory_from_xd") as auto_read,
            patch("app.main_window.messagebox.showwarning") as showwarning,
        ):
            window.send_selected_user_unit_to_xd()
            wait_for_tk(window.root, lambda: not window.user_unit_write_in_progress)

        self.assertEqual(
            FakeLogueCliTransport.calls,
            [
                ("resolve", "minilogue xd SOUND", "minilogue xd SOUND"),
                ("clear", "delfx", 2, 2, 2),
            ],
        )
        state = window.user_unit_workspace.slot_state("delfx-03")
        self.assertFalse(state.pending_clear)
        self.assertIn("Cleared Delay FX 03 on XD.", window.log_text.get("1.0", tk.END))
        auto_read.assert_called_once()
        showwarning.assert_not_called()

    def test_send_all_user_osc_to_xd_sends_only_pending_slots(self):
        FakeLogueCliTransport.calls = []
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "osc",
                "api": "1.0-0",
                "version": "1.2-3",
                "name": "Bright OSC",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            library_dir = temp_path / "user_units"
            library_dir.mkdir()
            bright_source = temp_path / "bright.mnlgxdunit"
            hum_source = temp_path / "hum.mnlgxdunit"
            write_user_unit_archive(bright_source, manifest, b"UOSCpayloadA")
            write_user_unit_archive(
                hum_source,
                {
                    "header": {
                        **manifest["header"],
                        "version": "1.1-0",
                        "name": "HUMN",
                    }
                },
                b"UOSCpayloadB",
            )
            window = self.make_window(temp_path=temp_path, library_dir=library_dir)
            bright_result = window.user_unit_validator.validate_for_destination(
                path=bright_source,
                destination_module=UnitModule.OSC,
                destination_slot=0,
            )
            hum_result = window.user_unit_validator.validate_for_destination(
                path=hum_source,
                destination_module=UnitModule.OSC,
                destination_slot=2,
            )
            self.assertTrue(bright_result.ok)
            self.assertTrue(hum_result.ok)
            window.user_unit_workspace.assign_pending(
                module=UnitModule.OSC,
                slot_index=0,
                unit=bright_result.unit,
            )
            window.user_unit_workspace.assign_pending(
                module=UnitModule.OSC,
                slot_index=2,
                unit=hum_result.unit,
            )
            window.refresh_user_units_trees()
            window.input_port_var.set("minilogue xd SOUND")
            window.output_port_var.set("minilogue xd SOUND")

            with (
                patch("app.main_window.LogueCliTransport", FakeLogueCliTransport),
                patch("app.main_window.messagebox.askyesno", return_value=True),
                patch.object(window, "schedule_after", side_effect=lambda _delay, callback: callback()),
                patch.object(window, "read_user_unit_inventory_from_xd") as auto_read,
                patch("app.main_window.messagebox.showwarning") as showwarning,
            ):
                window.send_all_user_osc_to_xd()
                wait_for_tk(window.root, lambda: not window.user_unit_write_in_progress)

        self.assertEqual(
            FakeLogueCliTransport.calls,
            [
                ("resolve", "minilogue xd SOUND", "minilogue xd SOUND"),
                ("load", "bright.mnlgxdunit", 0, 2, 2),
                ("load", "hum.mnlgxdunit", 2, 2, 2),
            ],
        )
        self.assertIsNone(window.user_unit_workspace.slot_state("osc-01").pending_assignment)
        self.assertIsNone(window.user_unit_workspace.slot_state("osc-03").pending_assignment)
        self.assertIn("Sent 2 User Unit change(s) to XD.", window.log_text.get("1.0", tk.END))
        auto_read.assert_called_once()
        showwarning.assert_not_called()

    def test_send_all_user_fx_to_xd_sends_pending_fx_slots_and_auto_reads(self):
        FakeLogueCliTransport.calls = []
        manifest = {
            "header": {
                "platform": "minilogue-xd",
                "module": "revfx",
                "api": "1.0-0",
                "version": "2.0-1",
                "name": "Glow Verb",
                "params": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            library_dir = temp_path / "user_units"
            library_dir.mkdir()
            source = temp_path / "glow.mnlgxdunit"
            write_user_unit_archive(source, manifest, b"UREVpayload")
            window = self.make_window(temp_path=temp_path, library_dir=library_dir)
            result = window.user_unit_validator.validate_for_destination(
                path=source,
                destination_module=UnitModule.REVERB_FX,
                destination_slot=0,
            )
            self.assertTrue(result.ok)
            window.user_unit_workspace.mark_slot_for_clear(module=UnitModule.MOD_FX, slot_index=1)
            window.user_unit_workspace.assign_pending(
                module=UnitModule.REVERB_FX,
                slot_index=0,
                unit=result.unit,
            )
            window.refresh_user_units_trees()
            window.input_port_var.set("minilogue xd SOUND")
            window.output_port_var.set("minilogue xd SOUND")

            with (
                patch("app.main_window.LogueCliTransport", FakeLogueCliTransport),
                patch("app.main_window.messagebox.askyesno", return_value=True),
                patch.object(window, "schedule_after", side_effect=lambda _delay, callback: callback()),
                patch.object(window, "read_user_unit_inventory_from_xd") as auto_read,
                patch("app.main_window.messagebox.showwarning") as showwarning,
            ):
                window.send_all_user_fx_to_xd()
                wait_for_tk(window.root, lambda: not window.user_unit_write_in_progress)

        self.assertEqual(
            FakeLogueCliTransport.calls,
            [
                ("resolve", "minilogue xd SOUND", "minilogue xd SOUND"),
                ("clear", "modfx", 1, 2, 2),
                ("load", "glow.mnlgxdunit", 0, 2, 2),
            ],
        )
        self.assertFalse(window.user_unit_workspace.slot_state("modfx-02").pending_clear)
        self.assertIsNone(window.user_unit_workspace.slot_state("revfx-01").pending_assignment)
        auto_read.assert_called_once()
        showwarning.assert_not_called()

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
        self.assertIn("Dump received successfully", window.log_text.get("1.0", tk.END))

    def test_sysex_finalizer_loads_captured_programs_into_edit_view(self):
        window = self.make_window()
        program = self.make_program("CapturedProg", 9)
        window.receive_mode = "native_capture"
        window.sysex_buffer.add_message(encode_program_dump(program, 9), time.time())

        window.finalize_sysex_receive()

        self.assertEqual(window.bank.slots[9].name, "CapturedProg")
        self.assertEqual(window.bank.slots[9].status, "Captured")
        self.assertIn(
            "Loaded 1 programs from captured SysEx dump into Edit view.",
            window.log_text.get("1.0", tk.END),
        )

    def test_syx_export_preserves_full_raw_capture_after_program_import(self):
        window = self.make_window()
        program = self.make_program("RawKeep", 0)
        raw = encode_program_dump(program, 0) + bytes.fromhex("F0 42 30 00 01 51 44 F7")
        window.receive_mode = "native_capture"
        window.sysex_buffer.add_message(encode_program_dump(program, 0), time.time())
        window.sysex_buffer.add_message(bytes.fromhex("F0 42 30 00 01 51 44 F7"), time.time())
        window.finalize_sysex_receive()

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "capture.syx"
            window.save_bank_to_path(target)
            written = target.read_bytes()

        self.assertEqual(written, raw)

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

    def test_bank_finalizer_writes_multiengine_report(self):
        window = self.make_window()
        window.receive_mode = "bank"
        program = self.make_program("UserBass", 9)
        prog_bin = bytearray(program.prog_bin)
        prog_bin[38] = 2
        prog_bin[41] = 3
        program = XDProgram(slot_index=9, name="UserBass", prog_bin=bytes(prog_bin), source_type="test")
        dumps_temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(dumps_temp_dir.cleanup)
        dumps_path = Path(dumps_temp_dir.name)

        with (
            patch("app.main_window.dumps_dir", return_value=dumps_path),
            patch("app.main_window.time.strftime", return_value="20260609_120000"),
        ):
            window.sysex_buffer.add_message(encode_program_dump(program, 9), time.time())
            window.sysex_buffer.finalize("timeout", time.time())
            window.finalize_bank_receive("timeout")

        report_path = dumps_path / "multiengine_20260609_120000.txt"
        self.assertTrue(report_path.exists())
        content = report_path.read_text(encoding="utf-8")
        self.assertIn("Source: Captured SysEx dump", content)
        self.assertIn("Programs using User OSC: 1", content)
        self.assertIn("User OSC 04", content)
        self.assertIn("UserBass", content)
        self.assertIn("Multiengine analysis: 1 programs use User OSC; report saved: multiengine_20260609_120000.txt", window.log_text.get("1.0", tk.END))

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

    def test_inactivity_timeout_without_listen_mode_does_not_log_completion(self):
        window = self.make_window()
        window.listen_active = False
        window.sysex_buffer.add_message(encode_program_dump(self.make_program("SlotOne", 0), 0), time.time() - 10)
        window.inactivity_ms_var.set("1")
        window.max_timeout_s_var.set("1")

        window.check_capture_timeouts()

        self.assertFalse(window.sysex_buffer.capture.is_active)
        self.assertNotIn("Capture completed after", window.log_text.get("1.0", tk.END))

    def test_incomplete_sysex_warning_is_logged(self):
        window = self.make_window()
        event = RawCaptureEvent(
            kind="warning",
            message="Incomplete SysEx frame: 12 bytes buffered.",
            state="capturing",
            port_name="in",
        )

        window.handle_native_capture_event(event)

        log_output = window.log_text.get("1.0", tk.END)
        self.assertIn("WARNING", log_output)
        self.assertIn("Incomplete SysEx frame", log_output)
        self.assertIn("Dump failed", window.listen_status_var.get())

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

    def test_inline_rename_commits_without_popup_dialog(self):
        window = self.make_window()
        window.bank.load_programs([self.make_program("Before", 0)], "test", "test")
        window.refresh_bank_tree()

        with patch.object(window.bank_tree, "bbox", return_value=(0, 0, 120, 20)):
            window.start_inline_bank_rename("0", 0)
            window.inline_name_editor.delete(0, tk.END)
            window.inline_name_editor.insert(0, "After")
            window.commit_inline_bank_rename()

        self.assertEqual(window.bank.slots[0].name, "After")
        self.assertIsNone(window.inline_name_editor)

    def test_case_sensitive_search_toggle_changes_matches(self):
        window = self.make_window()
        window.bank.load_programs([self.make_program("BassLine", 0)], "test", "test")
        window.refresh_bank_tree()

        window.bank_search_var.set("bass")
        self.assertEqual(window.bank_count_var.get(), "1 / 500 shown")

        window.case_sensitive_search_var.set(True)
        self.assertEqual(window.bank_count_var.get(), "0 / 500 shown")

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

    def test_send_selected_opens_selected_output_port_before_sending(self):
        window = self.make_window()
        sender = SuccessfulSender()
        program = self.make_program("PortOpen", 0)
        receiver = FakeReceiver(sender)
        receiver.output_name = None
        window.receiver = receiver
        window.output_port_var.set("out")
        window.bank.load_programs([program], "test", "test")
        window.refresh_bank_tree()
        window.bank_tree.selection_set(["0"])

        def fake_open_ports():
            receiver.output_name = "out"

        with (
            patch.object(window, "open_ports", side_effect=fake_open_ports) as open_ports,
            patch("app.main_window.messagebox.askyesno", return_value=True),
        ):
            window.send_selected_to_buffer()
            wait_for_tk(window.root, lambda: window.current_sender is None)

        open_ports.assert_called_once()
        self.assertEqual(sender.messages[0][6], 0x40)

    def test_write_ack_without_pending_slot_is_logged(self):
        window = self.make_window()

        window.handle_live_xd_sysex(bytes.fromhex("F0 42 30 00 01 51 23 F7"))

        self.assertIn("Write ACK 0x23 received", window.log_text.get("1.0", tk.END))

    def test_log_tag_for_timeout_completion_and_preparing_send(self):
        self.assertEqual(
            MainWindow.log_tag_for("Capture completed after inactivity timeout."),
            "ok",
        )
        self.assertEqual(
            MainWindow.log_tag_for("Preparing send: slot A005, index 4, patch 'Terror Key', command 0x4C, 1181 bytes."),
            "tx",
        )

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

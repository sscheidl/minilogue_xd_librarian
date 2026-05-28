import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from app.main_window import MainWindow
from librarian.models import SysexRecord


class FailingSender:
    def send_messages(self, *_args, **_kwargs):
        raise RuntimeError("boom")


class FakeReceiver:
    is_open = True

    def make_sender(self):
        return FailingSender()

    def close_ports(self):
        pass


class MainWindowWorkflowTest(unittest.TestCase):
    def make_window(self):
        root = tk.Tk()
        root.withdraw()
        window = MainWindow(root)
        self.addCleanup(lambda: root.destroy() if root.winfo_exists() else None)
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
            patch.object(window.logger, "exception"),
        ):
            window.send_records([record], "test")

        log = window.log_text.get("1.0", tk.END)
        self.assertIn("Send failed: boom", log)
        self.assertNotIn("Send complete:", log)
        showerror.assert_called_once()
        self.assertIsNone(window.current_sender)

    def test_on_close_warns_for_unsaved_capture(self):
        window = self.make_window()
        window.sysex_buffer.add_message(b"\xf0\x42\x00\xf7", time.time())

        with patch("app.main_window.messagebox.askyesno", return_value=False) as ask:
            window.on_close()

        ask.assert_called_once()
        self.assertTrue(window.root.winfo_exists())

    def test_diagnostic_report_has_version(self):
        window = self.make_window()

        report = window.build_diagnostic_report()

        self.assertIn("Version: 0.4.0", report)
        self.assertNotIn("Version: unknown", report)

    def test_v04_tabs_and_bank_columns(self):
        window = self.make_window()

        self.assertEqual(
            [window.tabs.tab(tab, "text") for tab in window.tabs.tabs()],
            ["Programs / Banks", "Transfer / SysEx", "User OSC", "User FX", "Options"],
        )
        self.assertEqual(tuple(window.bank_tree["columns"]), ("slot", "name", "source", "status", "hash", "notes"))
        self.assertEqual(window.bank_count_var.get(), "500 / 500 shown")


if __name__ == "__main__":
    unittest.main()

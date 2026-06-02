"""Tkinter main window for the minilogue xd librarian."""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
import tkinter as tk
import zipfile
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, simpledialog, scrolledtext, ttk

from app.app_paths import (
    dumps_dir,
    load_settings,
    log_path,
    save_settings,
    settings_path,
    user_data_dir,
    user_units_dir,
)
from app.version import APP_VERSION
from devices.korg_minilogue_xd.slot_mapping import map_slot
from devices.korg_minilogue_xd.sysex import classify_xd_sysex, summarize_xd_sysex_stream
from devices.korg_minilogue_xd.user_units import (
    USER_FX_SLOTS,
    USER_OSC_SLOTS,
    USER_UNIT_SLOTS_BY_KEY,
    matching_slots,
)
from librarian.bank_workspace import OfflineBank
from librarian.models import STATUS_IMPORTED, STATUS_SYNCED, SysexRecord
from librarian.sysex_tools import (
    build_records,
    read_sysex_file,
    records_to_bytes,
    report_dict,
    report_text,
    split_sysex_stream,
    write_report_files,
)
from librarian.import_validation import COMPATIBLE, PROBABLY_COMPATIBLE, validate_import_path
from librarian.user_units import (
    UserUnitAssignment,
    first_available_slot_key,
    import_user_unit,
    load_user_unit_assignments,
    save_user_unit_assignments,
    scan_user_units,
)
from midi.capture_events import RawCaptureEvent
from midi.diagnostics import MidiMessageInfo, analyze_raw_message
from midi.engine3_capture import Engine3SysexCaptureWorker
from midi.engine3_native import detect_engine3_native_runtime
from midi.engine3_sender import Engine3SysexSender
from midi.filters import (
    MidiFilterSettings,
    is_realtime_message,
    should_log_message,
)
from midi.ports import get_input_ports, get_output_ports
from midi.receiver import MidiReceiver, QueuedMidiError, QueuedMidiMessage
from midi.sysex_requests import request_current_program, request_program_slot
from midi.sysex_buffer import SysexBuffer
from utils.hexview import format_hex
from utils.logger import append_to_file, log_line
from xd_formats.filename_utils import safe_filename
from xd_formats import (
    XDLibrary,
    analyze_sysex_file,
    decode_program_dump,
    encode_current_program_dump,
    encode_program_dump,
    import_current_program_from_bytes,
    import_sysex_programs,
    import_sysex_programs_from_bytes,
    load_mnlgxdlib,
    load_mnlgxdprog,
    save_mnlgxdlib,
    save_mnlgxdprog,
)

_APP_VERSION = APP_VERSION
_BANK_COLUMNS = ("slot", "name", "source", "status")
_BANK_COLUMN_TITLES = {
    "slot": "Slot",
    "name": "Program Name",
    "source": "Source",
    "status": "Status",
}
_BANK_COLUMN_WIDTHS = {
    "slot": 80,
    "name": 190,
    "source": 240,
    "status": 180,
}


def _asset_path(filename: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return bundle_root / "assets" / filename


class ToolTip:
    """Tiny Tk tooltip for disabled hardware actions and dense controls."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event: tk.Event) -> None:
        if self.window is not None:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        ttk.Label(
            self.window,
            text=self.text,
            justify=tk.LEFT,
            relief=tk.SOLID,
            borderwidth=1,
            padding=(6, 4),
        ).pack()

    def hide(self, _event: tk.Event) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class MainWindow:
    """Tabbed librarian GUI with safe raw SysEx workflows."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.app_title = f"minilogue xd Librarian v{_APP_VERSION}"
        self._closing = False
        self._after_jobs: set[str] = set()

        self.message_queue: Queue[QueuedMidiMessage | QueuedMidiError] = Queue()
        self.gui_callback_queue: Queue = Queue()
        self.native_capture_queue: Queue[RawCaptureEvent] = Queue()
        self.program_response_queue: Queue[int] = Queue()
        self.receiver = MidiReceiver(self.message_queue)
        self.native_capture_status = detect_engine3_native_runtime()
        self.sysex_buffer = SysexBuffer()
        self.settings = load_settings()

        empty_info = MidiMessageInfo("none", 0, False, False, False, None, False)
        self.last_midi_info = empty_info
        self.last_sysex_info = empty_info
        self.total_messages = 0
        self.total_sysex_messages = 0
        self.total_sysex_bytes = 0
        self.realtime_messages = 0
        self.clock_messages = 0
        self.last_sysex_received_at: float | None = None

        self.input_port_map: dict[str, str] = {}
        self.output_port_map: dict[str, str] = {}
        self.input_combos: list[ttk.Combobox] = []
        self.output_combos: list[ttk.Combobox] = []
        self.loaded_records: list[SysexRecord] = []
        self.loaded_source_path = ""
        self.preset_records: list[SysexRecord] = []
        self.bank = OfflineBank()
        self.current_sender = None
        self.pending_write_ack_indices: list[int] = []
        self.native_capture_worker: Engine3SysexCaptureWorker | None = None
        self.capture_state = "idle"
        self.capture_program_slots: set[int] = set()
        self.capture_command_counts: dict[int | None, int] = {}
        self.bank_drag_start_index: int | None = None
        self.listen_active = False
        self.listen_started_at: float | None = None
        self.listen_saw_midi = False
        self.listen_saw_clock = False
        self.listen_saw_sysex = False
        self.receive_mode = "raw"
        self.expected_cmd: int | None = None
        self.expected_slot: int | None = None
        self.dirty = False
        self.change_log: list[str] = []
        self.last_error = ""
        self.logger = logging.getLogger(__name__)
        self.bank_sort_column: str | None = None
        self.bank_sort_reverse = False
        self.current_bank_path: Path | None = None
        self.logo_image: tk.PhotoImage | None = None
        self.user_unit_assignment_path = user_data_dir() / "user_unit_slots.json"
        self.user_unit_assignments = load_user_unit_assignments(self.user_unit_assignment_path)

        self.input_port_var = tk.StringVar()
        self.output_port_var = tk.StringVar()
        self.receive_mode_var = tk.StringVar(value="Raw SysEx Capture")
        self.show_sysex_only_var = tk.BooleanVar(value=self.settings.get("show_sysex_only", True))
        self.hide_midi_clock_var = tk.BooleanVar(value=self.settings.get("hide_midi_clock", True))
        self.show_realtime_var = tk.BooleanVar(value=self.settings.get("show_realtime", False))
        self.show_note_controller_var = tk.BooleanVar(
            value=self.settings.get("show_note_controller", False)
        )
        self.auto_connect_var = tk.BooleanVar(value=self.settings.get("auto_connect", True))
        self.wait_for_ack_var = tk.BooleanVar(value=self.settings.get("wait_for_ack", True))
        self.confirm_before_send_var = tk.BooleanVar(value=self.settings.get("confirm_before_send", True))
        self.double_click_send_var = tk.BooleanVar(value=self.settings.get("double_click_send", True))
        self.ask_double_click_once_var = tk.BooleanVar(value=self.settings.get("ask_double_click_once", True))
        self.auto_audition_var = tk.BooleanVar(value=self.settings.get("auto_audition", False))
        self.ask_overwrite_files_var = tk.BooleanVar(value=self.settings.get("ask_overwrite_files", True))
        self.backup_before_overwrite_var = tk.BooleanVar(value=self.settings.get("backup_before_overwrite", False))
        self.sanitize_filenames_var = tk.BooleanVar(value=self.settings.get("sanitize_filenames", True))
        self.colorize_log_var = tk.BooleanVar(value=self.settings.get("colorize_log", True))
        self.debug_logging_var = tk.BooleanVar(value=self.settings.get("debug_logging", False))
        self.show_details_var = tk.BooleanVar(value=self.settings.get("show_details", False))
        self.auto_detect_korg_var = tk.BooleanVar(value=True)
        self.inactivity_ms_var = tk.StringVar(value=str(self.settings.get("inactivity_ms", 500)))
        self.max_timeout_s_var = tk.StringVar(value=str(self.settings.get("max_timeout_s", 10)))
        self.ack_timeout_s_var = tk.StringVar(value=str(self.settings.get("ack_timeout_s", 3)))
        self.send_delay_var = tk.StringVar(value=str(self.settings.get("send_delay_ms", 80)))
        self.status_var = tk.StringVar()
        self.sysex_summary_var = tk.StringVar()
        self.port_hint_var = tk.StringVar()
        self.listen_status_var = tk.StringVar(value="Port test: idle")
        self.settings_status_var = tk.StringVar()
        self.bottom_status_var = tk.StringVar()
        self.analyzer_status_var = tk.StringVar(value="No SysEx file loaded.")
        self.bank_count_var = tk.StringVar(value="500 / 500 shown")
        self.user_osc_status_var = tk.StringVar()
        self.user_fx_status_var = tk.StringVar()

        self._build_layout()
        self.initialize_midi_connection()
        self.refresh_bank_tree()
        self.refresh_user_units_trees()
        self.update_status()

        self.root.bind("<Destroy>", self.on_root_destroy, add="+")
        self.root.bind_all("<Control-z>", self.undo_bank_key)
        self.root.bind_all("<Control-Z>", self.undo_bank_key)
        self.schedule_after(50, self.process_queue)
        self.schedule_after(100, self.check_capture_timeouts)

    def initialize_midi_connection(self) -> None:
        self.input_port_var.set(
            self.settings.get("last_midi_in")
            or self.settings.get("last_successful_midi_in")
            or ""
        )
        self.output_port_var.set(
            self.settings.get("last_midi_out")
            or self.settings.get("last_successful_midi_out")
            or ""
        )
        self.append_log(log_line(f"minilogue xd Librarian v{_APP_VERSION} started"))
        self.native_capture_status = detect_engine3_native_runtime()
        self.append_log(log_line(self.native_capture_status.status_text))
        self.refresh_ports()
        if not self.native_capture_status.available:
            self.listen_status_var.set(self.native_capture_status.status_text)
        if self.auto_connect_var.get() and (self.selected_input_port() or self.selected_output_port()):
            self.open_ports()
            if self.receiver.is_open:
                self.append_log(log_line("MIDI auto-connect completed. No data was sent."))
            else:
                self.listen_status_var.set("MIDI: not connected - use Reconnect MIDI")
        else:
            self.listen_status_var.set("MIDI: not connected - use Reconnect MIDI")

    def initialize_ports_without_scan(self) -> None:
        """Backward-compatible alias for older tests and launchers."""
        self.initialize_midi_connection()

    def schedule_after(self, delay_ms: int, callback) -> None:
        if self._closing:
            return
        job_id = ""

        def _wrapped_callback() -> None:
            if job_id:
                self._after_jobs.discard(job_id)
            callback()

        job_id = self.root.after(delay_ms, _wrapped_callback)
        self._after_jobs.add(job_id)

    def on_root_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        self._closing = True
        for job_id in tuple(self._after_jobs):
            try:
                self.root.after_cancel(job_id)
            except tk.TclError:
                pass
        self._after_jobs.clear()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_menu()
        self._configure_notebook_style()
        self._build_header()
        self.tabs = ttk.Notebook(self.root)
        self.tabs.grid(row=1, column=0, sticky="nsew")

        self.banks_tab = ttk.Frame(self.tabs, padding=10)
        self.midi_tab = ttk.Frame(self.tabs, padding=10)
        self.user_osc_tab = ttk.Frame(self.tabs, padding=10)
        self.user_fx_tab = ttk.Frame(self.tabs, padding=10)
        self.settings_tab = ttk.Frame(self.tabs, padding=10)

        self.tabs.add(self.banks_tab, text="Programs / Banks")
        self.tabs.add(self.midi_tab, text="Transfer")
        self.tabs.add(self.user_osc_tab, text="User OSC")
        self.tabs.add(self.user_fx_tab, text="User FX")
        self.tabs.add(self.settings_tab, text="Options")

        self._build_banks_tab()
        self._build_midi_tab()
        self._build_user_unit_placeholder_tab(self.user_osc_tab, "User OSC")
        self._build_user_unit_placeholder_tab(self.user_fx_tab, "User FX")
        self._build_settings_tab()
        ttk.Label(
            self.root,
            textvariable=self.bottom_status_var,
            anchor="w",
            relief=tk.SUNKEN,
            padding=(6, 3),
        ).grid(row=2, column=0, sticky="ew")

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg="#050505", height=58)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)

        logo_path = _asset_path("minilogue_xd.png")
        if logo_path.exists():
            try:
                logo = tk.PhotoImage(file=str(logo_path))
                if logo.height() > 48:
                    logo = logo.subsample(max(1, logo.height() // 40))
                self.logo_image = logo
                tk.Label(header, image=self.logo_image, bg="#050505", bd=0).grid(
                    row=0, column=0, sticky="w", padx=14, pady=7
                )
            except tk.TclError:
                tk.Label(
                    header,
                    text="minilogue xd",
                    bg="#050505",
                    fg="#ffffff",
                    font=("Segoe UI", 19, "bold"),
                ).grid(row=0, column=0, sticky="w", padx=14)
        else:
            tk.Label(
                header,
                text="minilogue xd",
                bg="#050505",
                fg="#ffffff",
                font=("Segoe UI", 19, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=14)

        tk.Label(
            header,
            text=f"Librarian v{_APP_VERSION}",
            bg="#050505",
            fg="#d7d7d7",
            font=("Segoe UI", 10),
        ).grid(row=0, column=1, sticky="e", padx=14)

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Open Bank...", command=self.open_bank)
        file_menu.add_command(label="Open Preset...", command=self.open_preset_into_bank)
        file_menu.add_command(label="Save Bank", command=self.save_bank)
        file_menu.add_command(label="Save Bank As...", command=self.save_bank_as)
        file_menu.add_separator()
        file_menu.add_command(label="Create Full Backup...", command=self.save_capture_backup)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.root.configure(menu=menu_bar)

    @staticmethod
    def _configure_notebook_style() -> None:
        style = ttk.Style()
        style.configure(
            "TNotebook.Tab",
            padding=(12, 6),
            background="#e5e7eb",
            foreground="#1f2328",
            font=("Segoe UI", 9),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#ffffff"), ("active", "#f3f4f6"), ("!selected", "#e5e7eb")],
            foreground=[("selected", "#111111"), ("active", "#111111"), ("!selected", "#1f2328")],
        )

    def _build_midi_tab(self) -> None:
        self.midi_tab.columnconfigure(0, weight=1)
        self.midi_tab.rowconfigure(2, weight=1)

        actions = ttk.LabelFrame(self.midi_tab, text="Transfer")
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        button_specs = [
            ("Open Bank...", self.open_bank),
            ("Save Bank", self.save_bank),
            ("Save Bank As...", self.save_bank_as),
            ("Export Bank as SysEx...", self.export_bank_as_sysex),
            ("Write Bank to XD", self.write_bank_to_xd),
            ("Receive SysEx", self.start_manual_sysex_capture),
            ("Capture Bank Dump from XD", self.start_manual_bank_capture),
            ("Reconnect MIDI", self.reconnect_midi),
            ("Cancel Send", self.cancel_send),
            ("Clear Log", self.clear_log),
        ]
        for index, (text, command) in enumerate(button_specs):
            ttk.Button(actions, text=text, command=command).grid(
                row=index // 4,
                column=index % 4,
                sticky="ew",
                padx=5,
                pady=4,
            )

        status = ttk.Frame(self.midi_tab)
        status.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.listen_status_var, foreground="#1a73e8").grid(
            row=1, column=0, sticky="ew"
        )

        self.log_text = scrolledtext.ScrolledText(self.midi_tab, wrap=tk.NONE, font=("Consolas", 10))
        self.log_text.grid(row=2, column=0, sticky="nsew")
        self.configure_log_tags()

    def configure_log_tags(self) -> None:
        self.log_text.tag_configure("tx", foreground="#6f42c1")
        self.log_text.tag_configure("rx", foreground="#0969da")
        self.log_text.tag_configure("ok", foreground="#1a7f37")
        self.log_text.tag_configure("warning", foreground="#9a6700")
        self.log_text.tag_configure("error", foreground="#cf222e")
        self.log_text.tag_configure("debug", foreground="#6e7781")

    def _build_presets_tab(self) -> None:
        """Build the optional preset workspace tab.

        This tab is currently not wired into the main notebook. Keep the method
        harmless if it is called before ``self.presets_tab`` exists.
        """
        if not hasattr(self, "presets_tab"):
            return
        self.presets_tab.columnconfigure(0, weight=1)
        self.presets_tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.presets_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for index, (text, command) in enumerate(
            [
                ("Open Single/Raw", self.load_presets),
                ("Export Selected", self.export_selected_preset),
                ("Duplicate", self.duplicate_selected_preset),
                ("Rename Display", self.rename_selected_preset),
                ("Delete from Workspace", self.delete_selected_preset),
                ("Send Selected", self.send_selected_preset),
            ]
        ):
            ttk.Button(controls, text=text, command=command).grid(row=0, column=index, padx=(0, 6))
        ttk.Label(controls, text="Search").grid(row=0, column=7)
        self.preset_search_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.preset_search_var, width=22).grid(
            row=0, column=8, padx=(5, 6)
        )
        ttk.Button(controls, text="Filter", command=self.refresh_preset_tree).grid(
            row=0, column=9
        )

        self.preset_tree = ttk.Treeview(
            self.presets_tab,
            columns=("index", "name", "type", "length", "hash", "source"),
            show="headings",
            selectmode="extended",
        )
        self._setup_tree(
            self.preset_tree,
            [
                ("index", "#", 60),
                ("name", "Name", 180),
                ("type", "Type", 180),
                ("length", "Bytes", 80),
                ("hash", "Hash", 110),
                ("source", "Source", 260),
            ],
        )
        self.preset_tree.grid(row=1, column=0, sticky="nsew")

    def _build_banks_tab(self) -> None:
        self.banks_tab.columnconfigure(0, weight=1)
        self.banks_tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.banks_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        group_specs = [
            ("File", [("Open Bank", self.open_bank), ("Open Preset", self.open_preset_into_bank), ("Save Bank", self.save_bank), ("Save Bank As", self.save_bank_as)]),
            ("Send", [("Send Selected", self.send_selected_bank_slots), ("Send to Buffer", self.send_selected_to_buffer), ("Write Bank to XD", self.write_bank_to_xd)]),
            ("Edit", [("Cut", self.cut_bank_slot), ("Copy", self.copy_bank_slot), ("Paste", self.paste_bank_slot), ("Move To", self.move_bank_slot), ("Rename", self.rename_bank_slot), ("Clear / Init", self.clear_bank_slot), ("Undo", self.undo_bank), ("Change Log", self.show_change_log)]),
        ]
        for column, (title, buttons) in enumerate(group_specs):
            group = ttk.LabelFrame(controls, text=title)
            group.grid(row=0, column=column, sticky="nw", padx=(0, 8), pady=(0, 4))
            for index, (text, command) in enumerate(buttons):
                ttk.Button(group, text=text, command=command).grid(row=index // 4, column=index % 4, padx=3, pady=3)

        self.bank_search_var = tk.StringVar()
        self.bank_search_var.trace_add("write", lambda *_: self.refresh_bank_tree())
        search_group = ttk.LabelFrame(controls, text="Search")
        search_group.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        search_group.columnconfigure(1, weight=1)
        ttk.Label(search_group, text="Search").grid(row=0, column=0, sticky="w", padx=(8, 5), pady=5)
        ttk.Entry(search_group, textvariable=self.bank_search_var, width=34).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Button(search_group, text="Clear", command=self.clear_bank_search).grid(row=0, column=2, sticky="w", padx=5, pady=5)
        ttk.Label(search_group, textvariable=self.bank_count_var, foreground="#5f6368").grid(row=0, column=3, sticky="e", padx=8, pady=5)
        ttk.Label(
            controls,
            text="No bank loaded. Open a bank, load presets, or receive data from the minilogue xd.",
            foreground="#5f6368",
        ).grid(row=2, column=0, columnspan=4, sticky="ew", pady=(5, 0))

        bank_tree_frame = ttk.Frame(self.banks_tab)
        bank_tree_frame.grid(row=1, column=0, sticky="nsew")
        bank_tree_frame.columnconfigure(0, weight=1)
        bank_tree_frame.rowconfigure(0, weight=1)
        self.bank_tree = ttk.Treeview(
            bank_tree_frame,
            columns=_BANK_COLUMNS,
            show="headings",
            selectmode="extended",
        )
        y_scroll = ttk.Scrollbar(bank_tree_frame, orient=tk.VERTICAL, command=self.bank_tree.yview)
        x_scroll = ttk.Scrollbar(bank_tree_frame, orient=tk.HORIZONTAL, command=self.bank_tree.xview)
        self.bank_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self._setup_bank_tree()
        self.bank_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.bank_tree.bind("<Enter>", lambda _event: self.bank_tree.focus_set())
        self.bank_tree.bind("<ButtonPress-1>", self.on_bank_drag_start)
        self.bank_tree.bind("<ButtonRelease-1>", self.on_bank_drag_release)
        self.bank_tree.bind("<Double-1>", self.on_bank_double_click)
        self.bank_tree.bind("<Button-3>", self.show_bank_context_menu)
        self.bank_tree.bind("<Control-c>", self.copy_bank_slot)
        self.bank_tree.bind("<Control-C>", self.copy_bank_slot)
        self.bank_tree.bind("<Control-x>", self.cut_bank_slot)
        self.bank_tree.bind("<Control-X>", self.cut_bank_slot)
        self.bank_tree.bind("<Control-v>", self.paste_bank_slot)
        self.bank_tree.bind("<Control-V>", self.paste_bank_slot)
        self.bank_tree.bind("<Delete>", self.clear_bank_slot)
        self.bank_tree.bind("<F2>", self.rename_bank_slot)
        self.bank_tree.bind("<Control-a>", self.select_all_bank_slots)
        self.bank_tree.bind("<Control-A>", self.select_all_bank_slots)
        self.bank_context_menu = self._build_bank_context_menu()

    def _build_user_unit_placeholder_tab(self, parent: ttk.Frame, label: str) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hardware_note = (
            "Read/write for User OSC/FX is pending logue SDK/logue-cli protocol verification. "
            "These slots are local assignments only; hardware status is unknown."
        )
        button_specs = [
            ("Read from XD", self.user_unit_send_not_implemented, tk.DISABLED),
            ("Load Unit", self.import_user_units, tk.NORMAL),
            ("View Details", self.view_selected_user_unit_manifest, tk.NORMAL),
            ("Rename", self.rename_selected_user_unit_assignment, tk.NORMAL),
            ("Move To", self.move_selected_user_unit_assignment, tk.NORMAL),
            ("Delete / Clear", self.remove_selected_user_units, tk.NORMAL),
            ("Save Assignments", self.save_user_unit_assignments_as, tk.NORMAL),
            ("Load Assignments", self.load_user_unit_assignments_from_file, tk.NORMAL),
            ("Send to XD", self.user_unit_send_not_implemented, tk.DISABLED),
            ("Refresh", self.refresh_user_units_trees, tk.NORMAL),
        ]
        for index, (text, command, state) in enumerate(button_specs):
            button = ttk.Button(controls, text=text, command=command, state=state)
            button.grid(row=0, column=index, padx=(0, 6), pady=(0, 2))
            if state == tk.DISABLED:
                ToolTip(button, hardware_note)
        status_var = self.user_osc_status_var if label == "User OSC" else self.user_fx_status_var
        ttk.Label(
            controls,
            textvariable=status_var,
            foreground="#5f6368",
            wraplength=1100,
        ).grid(row=1, column=0, columnspan=10, sticky="w", pady=(6, 0))

        if label == "User OSC":
            tree = ttk.Treeview(
                parent,
                columns=("slot", "name", "type", "compatibility", "status", "source", "notes"),
                show="headings",
                selectmode="extended",
            )
            self._setup_tree(
                tree,
                [
                    ("slot", "Slot", 90),
                    ("name", "Name", 170),
                    ("type", "Type", 110),
                    ("compatibility", "Compatibility", 170),
                    ("status", "Status", 190),
                    ("source", "Source", 220),
                    ("notes", "Notes", 260),
                ],
            )
            tree.grid(row=1, column=0, sticky="nsew")
            self.user_osc_tree = tree
        else:
            fx_frame = ttk.Frame(parent)
            fx_frame.grid(row=1, column=0, sticky="nsew")
            for column in range(3):
                fx_frame.columnconfigure(column, weight=1)
            fx_frame.rowconfigure(0, weight=1)
            self.user_fx_trees: dict[str, ttk.Treeview] = {}
            for column, (key, title) in enumerate(
                (("modfx", "MOD FX"), ("delfx", "DELAY FX"), ("revfx", "REVERB FX"))
            ):
                group = ttk.LabelFrame(fx_frame, text=title)
                group.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
                group.columnconfigure(0, weight=1)
                group.rowconfigure(0, weight=1)
                tree = ttk.Treeview(
                    group,
                    columns=("slot", "name", "type", "compatibility", "status"),
                    show="headings",
                    selectmode="extended",
                )
                self._setup_tree(
                    tree,
                    [
                        ("slot", "Slot", 86),
                        ("name", "Name", 150),
                        ("type", "Type", 80),
                        ("compatibility", "Compatibility", 130),
                        ("status", "Status", 180),
                    ],
                )
                tree.grid(row=0, column=0, sticky="nsew")
                ttk.Scrollbar(group, orient=tk.VERTICAL, command=tree.yview).grid(row=0, column=1, sticky="ns")
                tree.configure(yscrollcommand=group.grid_slaves(row=0, column=1)[0].set)
                self.user_fx_trees[key] = tree

    def _build_settings_tab(self) -> None:
        self.settings_tab.columnconfigure(0, weight=1)

        midi_frame = ttk.LabelFrame(self.settings_tab, text="MIDI Connection")
        midi_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        midi_frame.columnconfigure(1, weight=1)
        midi_frame.columnconfigure(3, weight=1)

        ttk.Label(midi_frame, text="MIDI IN").grid(row=0, column=0, sticky="w", padx=(8, 6), pady=(8, 4))
        self.options_input_combo = ttk.Combobox(midi_frame, textvariable=self.input_port_var, state="readonly")
        self.options_input_combo.grid(row=0, column=1, sticky="ew", pady=(8, 4), padx=(0, 10))
        self.input_combos.append(self.options_input_combo)
        ttk.Label(midi_frame, text="MIDI OUT").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=(8, 4))
        self.options_output_combo = ttk.Combobox(midi_frame, textvariable=self.output_port_var, state="readonly")
        self.options_output_combo.grid(row=0, column=3, sticky="ew", pady=(8, 4), padx=(0, 8))
        self.output_combos.append(self.options_output_combo)
        ttk.Checkbutton(midi_frame, text="Auto-connect on startup", variable=self.auto_connect_var).grid(
            row=1, column=0, sticky="w", padx=8, pady=(4, 8)
        )

        for index, (text, command) in enumerate(
            [
                ("Refresh MIDI Ports", self.refresh_ports),
                ("Reconnect MIDI", self.reconnect_midi),
                ("Disconnect MIDI", self.close_ports),
                ("Save Port Combination", self.save_current_port_combination),
                ("Open Log Folder", self.open_log_folder),
                ("Copy Diagnostic Report", self.copy_diagnostic_report),
                ("About", self.show_about),
                ("Clear communication status", self.clear_communication_status),
            ]
        ):
            ttk.Button(midi_frame, text=text, command=command).grid(
                row=2, column=index, sticky="w", padx=(8 if index == 0 else 0, 5), pady=(4, 8)
            )

        ttk.Label(midi_frame, textvariable=self.port_hint_var, foreground="#5f6368").grid(
            row=3, column=0, columnspan=6, sticky="ew", padx=8, pady=(0, 6)
        )
        ttk.Label(midi_frame, textvariable=self.listen_status_var, foreground="#1a73e8").grid(
            row=4, column=0, columnspan=6, sticky="ew", padx=8, pady=(0, 8)
        )

        transfer = ttk.LabelFrame(self.settings_tab, text="Transfer Timing")
        transfer.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(transfer, text="Inactivity finalize (ms)").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(transfer, textvariable=self.inactivity_ms_var, width=8).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(transfer, text="Max dump timeout (s)").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Entry(transfer, textvariable=self.max_timeout_s_var, width=8).grid(row=0, column=3, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(transfer, text="Send delay (ms)").grid(row=0, column=4, sticky="w", padx=8, pady=6)
        ttk.Entry(transfer, textvariable=self.send_delay_var, width=8).grid(row=0, column=5, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(transfer, text="ACK timeout (s)").grid(row=0, column=6, sticky="w", padx=8, pady=6)
        ttk.Entry(transfer, textvariable=self.ack_timeout_s_var, width=8).grid(row=0, column=7, sticky="w", padx=(0, 12), pady=6)
        ttk.Checkbutton(transfer, text="Wait for ACK after send", variable=self.wait_for_ack_var).grid(row=0, column=8, sticky="w", padx=8, pady=6)

        send_behavior = ttk.LabelFrame(self.settings_tab, text="Send Behavior")
        send_behavior.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(send_behavior, text="Confirm before sending", variable=self.confirm_before_send_var).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(send_behavior, text="Double-click sends preset to XD", variable=self.double_click_send_var).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(send_behavior, text="Ask once per session before double-click send", variable=self.ask_double_click_once_var).grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(send_behavior, text="Auto audition on selection", variable=self.auto_audition_var).grid(row=0, column=3, sticky="w", padx=8, pady=6)

        import_export = ttk.LabelFrame(self.settings_tab, text="Import / Export Behavior")
        import_export.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(import_export, text="Ask before overwriting files", variable=self.ask_overwrite_files_var).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(import_export, text="Create backup before overwrite", variable=self.backup_before_overwrite_var).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(import_export, text="Sanitize filenames", variable=self.sanitize_filenames_var).grid(row=0, column=2, sticky="w", padx=8, pady=6)

        editor = ttk.LabelFrame(self.settings_tab, text="Editor Behavior")
        editor.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(editor, text="Paste mode default: Overwrite").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Label(editor, text="Insert / Shift right is available from the context menu. Delete uses Clear / Init.").grid(row=0, column=1, sticky="w", padx=8, pady=6)

        filters = ttk.LabelFrame(self.settings_tab, text="Appearance / Log")
        filters.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(filters, text="Show SysEx only", variable=self.show_sysex_only_var).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Hide MIDI Clock", variable=self.hide_midi_clock_var).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Show MIDI realtime messages", variable=self.show_realtime_var).grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Show note/controller messages", variable=self.show_note_controller_var).grid(row=0, column=3, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Colorize log", variable=self.colorize_log_var).grid(row=0, column=4, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Show debug messages", variable=self.debug_logging_var).grid(row=0, column=5, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Show details panel", variable=self.show_details_var).grid(row=0, column=6, sticky="w", padx=8, pady=6)

        saved = ttk.LabelFrame(self.settings_tab, text="Saved Port Defaults")
        saved.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        saved.columnconfigure(1, weight=1)

        ttk.Label(saved, text="Default MIDI IN").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.default_in_var = tk.StringVar(value=self.settings.get("last_successful_midi_in", ""))
        ttk.Entry(saved, textvariable=self.default_in_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Label(saved, text="Default MIDI OUT").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.default_out_var = tk.StringVar(value=self.settings.get("last_successful_midi_out", ""))
        ttk.Entry(saved, textvariable=self.default_out_var).grid(
            row=1, column=1, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Button(saved, text="Save Settings", command=self.save_settings_from_tab).grid(
            row=2, column=0, sticky="w", padx=8, pady=(8, 8)
        )

        paths = ttk.LabelFrame(self.settings_tab, text="Debug / Advanced")
        paths.grid(row=7, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        path_rows = [
            ("Dump folder", str(dumps_dir())),
            ("Backup folder", str(user_data_dir() / "backups")),
            ("Settings file", str(settings_path())),
            ("Log file", str(log_path())),
            ("User data folder", str(user_data_dir())),
        ]
        for row, (label, value) in enumerate(path_rows):
            ttk.Label(paths, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=3)
            ttk.Label(paths, text=value).grid(row=row, column=1, sticky="w", padx=(8, 8), pady=3)
        ttk.Label(
            paths,
            text="Batch cancel enabled. First-send warning is always shown before raw SysEx transfer.",
            foreground="#5f6368",
        ).grid(row=len(path_rows), column=0, columnspan=2, sticky="w", padx=8, pady=(8, 6))

    @staticmethod
    def _setup_tree(tree: ttk.Treeview, columns: list[tuple[str, str, int]]) -> None:
        for column, text, width in columns:
            tree.heading(column, text=text)
            tree.column(column, width=width, anchor=tk.W)

    def _setup_bank_tree(self) -> None:
        for column in _BANK_COLUMNS:
            self.bank_tree.column(column, width=_BANK_COLUMN_WIDTHS[column], anchor=tk.W)
        self.update_bank_headings()

    def update_bank_headings(self) -> None:
        for column in _BANK_COLUMNS:
            title = _BANK_COLUMN_TITLES[column]
            if self.bank_sort_column == column:
                title += " " + ("v" if self.bank_sort_reverse else "^")
            self.bank_tree.heading(column, text=title, command=lambda col=column: self.set_bank_sort(col))

    def set_bank_sort(self, column: str) -> None:
        if self.bank_sort_column == column:
            self.bank_sort_reverse = not self.bank_sort_reverse
        else:
            self.bank_sort_column = column
            self.bank_sort_reverse = False
        self.update_bank_headings()
        self.refresh_bank_tree()

    def _build_bank_context_menu(self) -> tk.Menu:
        menu = tk.Menu(self.root, tearoff=False)
        self.bank_context_rules: list[str] = []
        entries = [
            ("Cut", self.cut_bank_slot, "selection"),
            ("Copy", self.copy_bank_slot, "selection"),
            ("Paste", self.paste_bank_slot, "clipboard"),
            ("Insert / Shift Right", self.insert_bank_slot, "clipboard"),
            ("Move To...", self.move_bank_slot, "single"),
            ("Rename", self.rename_bank_slot, "single"),
            ("Clear / Init", self.clear_bank_slot, "selection"),
            (None, None, "separator"),
            ("Load minilogue xd Program...", self.open_preset_into_bank, "selection"),
            ("Load SysEx...", self.open_preset_into_bank, "selection"),
            ("Save as minilogue xd Program...", self.save_selected_as_mnlgxdprog, "data"),
            ("Save as SysEx...", self.save_selected_as_sysex, "data"),
            (None, None, "separator"),
            ("Send selected to XD", self.send_selected_bank_slots, "data"),
            ("Send selected to edit buffer", self.send_selected_to_buffer, "data"),
        ]
        for label, command, rule in entries:
            if rule == "separator":
                menu.add_separator()
            else:
                menu.add_command(label=label, command=command)
                menu.entryconfig(label, state=tk.DISABLED if rule == "disabled" else tk.NORMAL)
            self.bank_context_rules.append(rule)
        return menu

    def show_bank_context_menu(self, event: tk.Event) -> None:
        item = self.bank_tree.identify_row(event.y)
        index = self.parse_bank_iid(item)
        if index is not None and item not in self.bank_tree.selection():
            self.bank_tree.selection_set(item)
        self.update_bank_context_menu()
        self.bank_context_menu.tk_popup(event.x_root, event.y_root)

    def update_bank_context_menu(self) -> None:
        selection = self.selected_bank_indices()
        has_selection = bool(selection)
        has_single = len(selection) == 1
        has_data = any(self.bank.slots[index].raw or self.bank.slots[index].prog_bin for index in selection)
        has_clipboard = bool(self.bank.clipboard)
        for index, rule in enumerate(self.bank_context_rules):
            if rule == "separator":
                continue
            enabled = (
                (rule == "selection" and has_selection)
                or (rule == "single" and has_single)
                or (rule == "data" and has_data)
                or (rule == "clipboard" and has_clipboard and has_single)
            )
            if rule == "disabled":
                enabled = False
            self.bank_context_menu.entryconfig(index, state=tk.NORMAL if enabled else tk.DISABLED)

    def refresh_ports(self) -> None:
        try:
            input_ports = get_input_ports()
            output_ports = get_output_ports()
        except Exception as exc:
            self.append_log(log_line(f"Port refresh failed: {exc}"))
            input_ports = []
            output_ports = []

        input_labels, self.input_port_map = self.build_port_labels(input_ports)
        output_labels, self.output_port_map = self.build_port_labels(output_ports)
        for combo in self.input_combos:
            combo["values"] = input_labels
        for combo in self.output_combos:
            combo["values"] = output_labels
        self.select_port_label(self.input_port_var, self.input_port_map, self.settings.get("last_successful_midi_in"), input_labels)
        self.select_port_label(self.output_port_var, self.output_port_map, self.settings.get("last_successful_midi_out"), output_labels)

        self.update_port_hint(input_ports, output_ports)
        self.append_log(log_line(f"Ports refreshed: {len(input_ports)} input, {len(output_ports)} output"))
        self.update_status()

    @staticmethod
    def build_port_labels(ports: list[str]) -> tuple[list[str], dict[str, str]]:
        labels = []
        mapping = {}
        for index, port in enumerate(ports, start=1):
            suffix = "  [possible SysEx/Librarian port]" if MainWindow.is_sysex_candidate(port) else ""
            label = f"{index}. {port}{suffix}"
            labels.append(label)
            mapping[label] = port
        return labels, mapping

    @staticmethod
    def is_sysex_candidate(port: str) -> bool:
        lowered = port.lower()
        return "minilogue xd" in lowered and (
            "midiin2" in lowered or "midiout2" in lowered or lowered.endswith(" 2") or lowered.endswith(") 2")
        )

    @staticmethod
    def select_port_label(
        variable: tk.StringVar,
        mapping: dict[str, str],
        preferred: str | None,
        labels: list[str],
    ) -> None:
        """Select the best visible combobox label while preserving valid choices."""
        if preferred:
            for label, port in mapping.items():
                if port == preferred:
                    variable.set(label)
                    return
        if variable.get() in mapping:
            return
        current_port = mapping.get(variable.get(), variable.get())
        if current_port:
            for label, port in mapping.items():
                if port == current_port:
                    variable.set(label)
                    return
        for label, port in mapping.items():
            if MainWindow.is_sysex_candidate(port):
                variable.set(label)
                return
        variable.set(labels[0] if labels else "")

    def selected_input_port(self) -> str | None:
        selected = self.input_port_var.get().strip()
        return self.input_port_map.get(selected, selected) or None

    def selected_output_port(self) -> str | None:
        selected = self.output_port_var.get().strip()
        return self.output_port_map.get(selected, selected) or None

    def update_port_hint(self, input_ports: list[str], output_ports: list[str]) -> None:
        candidates = [port for port in input_ports + output_ports if self.is_sysex_candidate(port)]
        if candidates:
            self.port_hint_var.set("SysEx hint: Port-2 candidates are marked, but selection is never forced.")
        else:
            self.port_hint_var.set("SysEx hint: all ports are shown; no Port-2 candidate detected.")

    def open_ports(self) -> None:
        input_name = self.selected_input_port()
        output_name = self.selected_output_port()
        if input_name is None and output_name is None:
            messagebox.showwarning("No ports selected", "Select at least one MIDI port.")
            return
        self.receiver.open_ports(input_name, output_name)
        if self.receiver.is_open:
            self.settings["last_midi_in"] = input_name
            self.settings["last_midi_out"] = output_name
            self.persist_settings()
            self.append_log(log_line("Ports opened. Send actions require explicit confirmation."))
        self.update_status()

    def reconnect_midi(self) -> None:
        self.refresh_ports()
        self.open_ports()

    def close_ports(self) -> None:
        self.receiver.close_ports()
        self.append_log(log_line("Ports closed."))
        self.update_status()

    def save_current_port_combination(self) -> None:
        self.settings["last_successful_midi_in"] = self.selected_input_port()
        self.settings["last_successful_midi_out"] = self.selected_output_port()
        self.default_in_var.set(self.settings.get("last_successful_midi_in") or "")
        self.default_out_var.set(self.settings.get("last_successful_midi_out") or "")
        self.persist_settings()
        self.append_log(log_line("Saved current MIDI port combination."))
        self.update_status()

    def clear_communication_status(self) -> None:
        self.listen_active = False
        self.listen_started_at = None
        self.listen_saw_midi = False
        self.listen_saw_clock = False
        self.listen_saw_sysex = False
        self.listen_status_var.set("Port test: idle")
        self.realtime_messages = 0
        self.clock_messages = 0
        self.update_status()

    def listen_for_sysex(self) -> None:
        if not self.selected_input_port():
            messagebox.showwarning("No MIDI IN selected", "Select a MIDI IN port first.")
            return
        if not self.receiver.is_open:
            self.open_ports()
        if not self.receiver.is_open:
            return
        self.listen_active = True
        self.listen_started_at = time.time()
        self.listen_saw_midi = False
        self.listen_saw_clock = False
        self.listen_saw_sysex = False
        self.listen_status_var.set("Port test: listening for SysEx on selected IN port...")
        self.append_log(log_line(f"Listening for SysEx on MIDI IN: {self.selected_input_port()}"))

    def process_queue(self) -> None:
        while True:
            try:
                callback = self.gui_callback_queue.get_nowait()
            except Empty:
                break
            callback()
        self.process_native_capture_queue()
        while True:
            try:
                item = self.message_queue.get_nowait()
            except Empty:
                break
            if isinstance(item, QueuedMidiError):
                self.append_log(log_line(item.message))
                self.flash_rx("error")
            else:
                self.handle_midi_message(item)
        self.schedule_after(50, self.process_queue)

    def process_native_capture_queue(self) -> None:
        while True:
            try:
                event = self.native_capture_queue.get_nowait()
            except Empty:
                break
            self.handle_native_capture_event(event)

    def handle_native_capture_event(self, event: RawCaptureEvent) -> None:
        if event.kind == "state":
            self.capture_state = event.state or self.capture_state
            self.append_log(log_line(event.message))
            self.listen_status_var.set("Start Full/All Dump on the minilogue xd now.")
        elif event.kind == "message":
            self.handle_native_capture_message(event.raw)
        elif event.kind == "finished":
            self.capture_state = "finalizing"
            self.listen_status_var.set("Finalizing...")
            if self.sysex_buffer.capture and self.sysex_buffer.capture.is_active:
                self.sysex_buffer.finalize("native-inactivity", time.time())
            if self.sysex_buffer.to_bytes():
                if self.receive_mode == "bank":
                    self.finalize_bank_receive("native-inactivity")
                else:
                    self.finalize_sysex_receive("native-inactivity")
                self.capture_state = "finished"
                self.listen_active = False
            else:
                self.capture_state = "finished"
                self.listen_active = False
                self.listen_status_var.set("No SysEx data received. Check MIDI input port and start the dump on the XD.")
                self.append_log(log_line("WARNING: No SysEx data received. Check MIDI input port and start the dump on the XD."))
        elif event.kind == "cancelled":
            self.capture_state = "cancelled"
            self.listen_active = False
            self.listen_status_var.set("Capture cancelled.")
            self.append_log(log_line("Capture cancelled."))
        elif event.kind == "warning":
            self.append_log(log_line(f"WARNING: {event.message}"))
        elif event.kind == "error":
            self.capture_state = "error"
            self.listen_active = False
            self.last_error = event.message
            self.listen_status_var.set(f"Capture error: {event.message}")
            self.append_log(log_line(f"ERROR: Native capture failed: {event.message}"))

    def handle_native_capture_message(self, raw: bytes) -> None:
        now = time.time()
        info = analyze_raw_message(raw, "sysex")
        self.last_midi_info = info
        self.listen_saw_midi = True
        if not info.is_sysex:
            return
        self.listen_saw_sysex = True
        self.last_sysex_info = info
        self.last_sysex_received_at = now
        sysex_message = self.sysex_buffer.add_message(raw, now)
        self.total_sysex_messages += 1
        self.total_sysex_bytes += sysex_message.length
        classification = classify_xd_sysex(raw)
        command = classification.command
        self.capture_command_counts[command] = self.capture_command_counts.get(command, 0) + 1
        if command == 0x4C and classification.slot_index is not None:
            self.capture_program_slots.add(classification.slot_index)
            self.listen_status_var.set(f"Programs received: {len(self.capture_program_slots):03d}/500")
        elif not self.capture_program_slots:
            self.listen_status_var.set("Waiting for dump...")
        if command is not None:
            self.append_log(log_line(f"RX raw len={len(raw)} cmd=0x{command:02X} type={classification.label}"))
        self.update_status()

    def handle_midi_message(self, item: QueuedMidiMessage) -> None:
        now = time.time()
        raw = self.strip_realtime_bytes(item.raw) if item.message_type == "sysex" else item.raw
        info = analyze_raw_message(raw, item.message_type)
        self.last_midi_info = info
        is_realtime = is_realtime_message(info.message_type)
        if is_realtime:
            self.realtime_messages += 1
            if info.message_type == "clock":
                self.clock_messages += 1
                if self.listen_active:
                    self.listen_saw_clock = True
        else:
            self.total_messages += 1
        if self.listen_active:
            self.listen_saw_midi = True

        if info.is_sysex:
            self.last_sysex_info = info
            self.last_sysex_received_at = now
            sysex_message = self.sysex_buffer.add_message(raw, now)
            self.total_sysex_messages += 1
            self.total_sysex_bytes += sysex_message.length
            self.flash_rx("sysex")
            self.append_sysex_log(now, raw, info)
            if self.listen_active:
                self.listen_saw_sysex = True
                self.listen_status_var.set(f"{self.receive_mode_var.get()}: SysEx received on selected IN port")
            if info.is_korg:
                self.save_successful_sysex_ports(now)
                self.handle_live_xd_sysex(raw)
                if self.listen_active:
                    self.listen_status_var.set(f"{self.receive_mode_var.get()}: Korg SysEx detected")
        else:
            if self.listen_active and not self.listen_saw_sysex:
                if info.message_type == "clock":
                    self.listen_status_var.set("Port test: MIDI clock received, no SysEx yet")
                else:
                    self.listen_status_var.set("Port test: MIDI data received, but no SysEx")
            settings = self.current_filter_settings()
            if not is_realtime or should_log_message(info.message_type, info.is_sysex, settings):
                self.flash_rx("midi")
            if should_log_message(info.message_type, info.is_sysex, settings):
                self.append_log(log_line(f"MIDI {info.message_type}: {format_hex(item.raw)}"))
        self.update_status()

    @staticmethod
    def strip_realtime_bytes(raw: bytes) -> bytes:
        return bytes(byte for byte in raw if byte not in {0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE})

    def handle_live_xd_sysex(self, raw: bytes) -> None:
        classification = classify_xd_sysex(raw)
        command = classification.command
        if command is not None:
            self.append_log(
                log_line(
                    f"RX SysEx len={len(raw)} cmd=0x{command:02X} type={classification.label}"
                )
            )
        if command == 0x23:
            self.handle_write_ack()
            return
        if self.receive_mode == "current_program" and command == 0x40:
            self.apply_current_program_receive(raw)
        elif self.receive_mode in {"slot_program", "full_bank_sequential"} and command == 0x4C:
            self.apply_slot_program_receive(raw, classification.slot_index)

    def handle_write_ack(self) -> None:
        if self.pending_write_ack_indices:
            index = self.pending_write_ack_indices.pop(0)
            self.bank.mark_sent([index])
            self.refresh_bank_tree()
            self.listen_status_var.set(f"Write ACK received for slot {index + 1:03d}")
            self.append_log(log_line(f"Write ACK 0x23: slot {index + 1:03d} marked Sent to XD."))
        else:
            self.listen_status_var.set("Write ACK received")
            self.append_log(log_line("Write ACK 0x23 received with no pending slot."))

    def apply_current_program_receive(self, raw: bytes) -> None:
        program = import_current_program_from_bytes(raw)
        if program is None:
            self.append_log(log_line("WARNING: 0x40 current program response could not be decoded."))
            return
        name = program.name or "name unknown"
        target_slot = self.expected_slot if self.expected_slot is not None else 0
        self.bank.set_program(
            target_slot,
            program,
            "Live receive",
            "Received",
            f"cmd=0x40 len={len(raw)}; current program response",
            status=STATUS_SYNCED,
        )
        self.refresh_bank_tree()
        self.mark_dirty("Updated browser/workspace current program from live receive")
        self.listen_status_var.set(f"Decoded current program: {name}")
        self.append_log(log_line(f'Decoded current program: name="{name}"'))
        self.append_log(log_line("Updated browser/workspace current program"))
        self.expected_cmd = None
        self.listen_active = False

    def apply_slot_program_receive(self, raw: bytes, slot_index: int | None) -> None:
        programs = import_sysex_programs_from_bytes(raw)
        if not programs:
            self.append_log(log_line("WARNING: 0x4C slot program response could not be decoded."))
            return
        program = programs[0]
        target_slot = self.expected_slot
        if target_slot is None:
            target_slot = slot_index if slot_index is not None else program.slot_index
        if target_slot is None or not 0 <= target_slot < len(self.bank.slots):
            self.append_log(log_line("WARNING: 0x4C response did not contain a valid target slot."))
            return
        name = program.name or "name unknown"
        self.bank.set_program(
            target_slot,
            program,
            "Live receive",
            "Received",
            f"cmd=0x4C len={len(raw)}",
            status=STATUS_SYNCED,
        )
        self.refresh_bank_tree()
        self.mark_dirty(f"Updated slot {target_slot + 1:03d} from live receive")
        self.listen_status_var.set(f"Decoded slot {target_slot + 1:03d}: {name}")
        self.append_log(
            log_line(f'Decoded slot {target_slot + 1:03d}: name="{name}"')
        )
        self.program_response_queue.put(target_slot)
        if self.receive_mode != "full_bank_sequential":
            self.expected_cmd = None
            self.listen_active = False

    def current_filter_settings(self) -> MidiFilterSettings:
        return MidiFilterSettings(
            show_sysex_only=self.show_sysex_only_var.get(),
            hide_midi_clock=self.hide_midi_clock_var.get(),
            show_realtime=self.show_realtime_var.get(),
            show_note_controller=self.show_note_controller_var.get(),
        )

    def append_sysex_log(self, timestamp: float, raw: bytes, info: MidiMessageInfo) -> None:
        manufacturer = f"0x{info.manufacturer_id:02X}" if info.manufacturer_id is not None else "none"
        self.append_log(
            f"[{time.strftime('%H:%M:%S', time.localtime(timestamp))}] SysEx "
            f"length={info.length} manufacturer={manufacturer} korg={info.is_korg}\n"
            f"{format_hex(raw)}\n"
        )

    def check_capture_timeouts(self) -> None:
        if self.native_capture_worker is not None and self.native_capture_worker.is_running:
            result = None
        else:
            result = self.sysex_buffer.check_timeouts(
                time.time(),
                self.read_int(self.inactivity_ms_var.get(), 500),
                self.read_int(self.max_timeout_s_var.get(), 10),
            )
            if result:
                self.append_log(log_line(f"Capture finalized by {result}."))
                self.finalize_live_receive(result)
        self.check_listen_timeout()
        self.update_status()
        self.schedule_after(100, self.check_capture_timeouts)

    def finalize_live_receive(self, reason: str) -> None:
        if self.receive_mode == "bank":
            self.finalize_bank_receive(reason)
        elif self.receive_mode == "current_program" and self.expected_cmd == 0x40:
            self.append_log(log_line("Request Current timeout: no 0x40 response received"))
            self.listen_status_var.set("Request Current timeout: no 0x40 response received")
        elif self.receive_mode == "slot_program" and self.expected_cmd == 0x4C:
            slot_text = (
                f" for slot {self.expected_slot + 1:03d}"
                if self.expected_slot is not None
                else ""
            )
            self.append_log(log_line(f"Request Slot timeout: no 0x4C response received{slot_text}"))
            self.listen_status_var.set(f"Request Slot timeout: no 0x4C response received{slot_text}")

    def finalize_bank_receive(self, reason: str = "inactivity") -> None:
        raw = self.sysex_buffer.to_bytes()
        summary = summarize_xd_sysex_stream(raw)
        self.append_log(log_line("SysEx receive summary:"))
        for label, count in summary.items():
            self.append_log(log_line(f"{label}: {count}"))
        programs = import_sysex_programs_from_bytes(raw)
        if programs:
            self.bank.merge_programs(programs, "XD Capture", "Received", status="Captured")
            self.refresh_bank_tree()
            total_filled = sum(1 for slot in self.bank.slots if slot.raw or slot.prog_bin)
            result = f"Captured bank: {total_filled}/500 programs."
            self.mark_dirty(result)
            self.listen_status_var.set(result)
            self.append_log(log_line(f"{result} Finalized by {reason}."))
            if total_filled != 500:
                missing = [
                    index
                    for index, slot in enumerate(self.bank.slots)
                    if not (slot.raw or slot.prog_bin)
                ]
                preview = ", ".join(f"{index + 1:03d}" for index in missing[:20])
                self.append_log(log_line(f"WARNING: Captured bank incomplete. Missing slot(s): {preview}"))
        else:
            total_filled = sum(1 for slot in self.bank.slots if slot.raw or slot.prog_bin)
            if total_filled:
                message = "No new 0x4C program dumps in this capture segment."
                self.append_log(log_line(f"WARNING: {message}"))
            else:
                message = "No program bank data received. Start the full program/all dump on the XD."
                self.listen_status_var.set(message)
                self.append_log(log_line(f"WARNING: {message}"))
        self.expected_cmd = None
        self.expected_slot = None

    def finalize_sysex_receive(self, reason: str = "inactivity") -> None:
        capture = self.sysex_buffer.capture
        message_count = len(capture.messages) if capture else 0
        total_bytes = capture.total_bytes if capture else len(self.sysex_buffer.to_bytes())
        result = f"Captured SysEx: {message_count} message(s), {total_bytes} bytes."
        self.listen_status_var.set(result)
        self.append_log(log_line(f"{result} Finalized by {reason}."))
        self.expected_cmd = None
        self.expected_slot = None

    def check_listen_timeout(self) -> None:
        if self.native_capture_worker is not None and self.native_capture_worker.is_running:
            return
        if not self.listen_active or self.listen_started_at is None:
            return
        if self.listen_saw_sysex:
            return
        if time.time() - self.listen_started_at < 10:
            return
        self.listen_active = False
        if self.listen_saw_midi:
            if self.listen_saw_clock:
                self.listen_status_var.set("Port test: MIDI clock received, no SysEx yet")
            else:
                self.listen_status_var.set("Port test: MIDI data received, but no SysEx")
        else:
            self.listen_status_var.set("Port test: No MIDI data received on selected port")

    def load_sysex_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open SysEx or raw Korg file",
            filetypes=[
                ("Korg / SysEx files", "*.syx *.mnlgxdprog *.mnlgxdlib"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            self.loaded_records = read_sysex_file(Path(path))
        except OSError as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.loaded_source_path = path
        self.analyzer_status_var.set(report_text(path, self.loaded_records))
        self.append_log(log_line(f"Loaded {len(self.loaded_records)} SysEx message(s) from {path}"))

    def export_analyzer_report(self) -> None:
        if not self.loaded_records:
            messagebox.showinfo("No loaded data", "Load a .syx file first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save analyzer report",
            defaultextension=".txt",
            filetypes=[("Text report", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        write_report_files(Path(path), self.loaded_source_path, self.loaded_records)
        self.append_log(log_line(f"Analyzer report written next to {path}"))

    def save_sysex_dump(self) -> None:
        data = self.sysex_buffer.to_bytes()
        if not data:
            messagebox.showinfo("No SysEx data", "No SysEx capture is available to save.")
            return
        path = filedialog.asksaveasfilename(
            title="Save SysEx Dump",
            initialdir=dumps_dir(),
            initialfile=time.strftime("minilogue_xd_capture_%Y%m%d_%H%M%S.syx"),
            defaultextension=".syx",
            filetypes=[("SysEx dump", "*.syx"), ("All files", "*.*")],
        )
        if not path:
            return
        if self.sysex_buffer.capture and self.sysex_buffer.capture.is_active:
            self.sysex_buffer.finalize("manual", time.time())
        Path(path).write_bytes(data)
        self.append_log(log_line(f"Saved SysEx dump: {path} ({len(data)} bytes)"))

    def send_loaded_records(self) -> None:
        self.send_records(self.loaded_records, "loaded SysEx file")

    def send_capture(self) -> None:
        records = build_records(self.sysex_buffer.to_bytes())
        self.send_records(records, "current capture")

    def send_records(self, records: list[SysexRecord], label: str, success_callback=None, error_callback=None) -> bool:
        if self.current_sender is not None:
            messagebox.showwarning("Busy", "A send operation is already in progress.")
            return False
        if not records:
            messagebox.showinfo("Nothing to send", f"No SysEx messages in {label}.")
            return False
        invalid = [
            record.index
            for record in records
            if not (record.raw.startswith(b"\xF0") and record.raw.endswith(b"\xF7"))
        ]
        if invalid:
            messagebox.showwarning(
                "Cannot send raw file",
                "Only complete SysEx messages can be sent. "
                f"Invalid record(s): {', '.join(map(str, invalid[:10]))}",
            )
            return False
        if not self.engine3_output_ready():
            messagebox.showwarning("No MIDI OUT", "Select a MIDI OUT port first.")
            return False
        slot_text = self.describe_record_slots(records)
        if self.confirm_before_send_var.get() and not messagebox.askyesno(
            "Send to XD?",
            f"Are you sure?\nOverwriting preset(s) on the XD.\n\nSlots: {slot_text}",
        ):
            return False
        delay_ms = self.read_int(self.send_delay_var.get(), 80)
        messages = [record.raw for record in records]
        self.start_send_worker_with_callbacks(
            messages,
            delay_ms,
            f"Send {label}",
            lambda index, total, length: self.append_log(
                log_line(f"Sent SysEx {index:03d}/{total:03d} ({length} bytes)")
            ),
            success_callback,
            error_callback,
        )
        return True

    @staticmethod
    def describe_record_slots(records: list[SysexRecord]) -> str:
        if not records:
            return "none"
        first = records[0].index
        last = records[-1].index
        if len(records) == 1:
            return f"{first:03d}"
        return f"{first:03d}-{last:03d}"

    def cancel_send(self) -> None:
        if self.native_capture_worker is not None and self.native_capture_worker.is_running:
            self.native_capture_worker.stop()
            self.capture_state = "cancelled"
            self.listen_active = False
            self.listen_status_var.set("Capture cancelled.")
            self.append_log(log_line("Cancel requested for native dump capture."))
            return
        if self.current_sender is not None:
            self.current_sender.cancel()
            self.append_log(log_line("Cancel requested for current send."))

    def start_send_worker(self, messages: list[bytes], delay_ms: int, label: str, progress) -> None:
        self.start_send_worker_with_callbacks(messages, delay_ms, label, progress)

    def engine3_output_ready(self) -> bool:
        return bool(self.selected_output_port())

    def make_sysex_sender(self):
        return Engine3SysexSender(self.receiver.make_sender())

    def start_send_worker_with_callbacks(
        self,
        messages: list[bytes],
        delay_ms: int,
        label: str,
        progress,
        success_callback=None,
        error_callback=None,
    ) -> None:
        if self.current_sender is not None:
            messagebox.showwarning("Busy", "A send operation is already in progress.")
            return
        sender = self.make_sysex_sender()
        self.current_sender = sender

        def worker() -> None:
            try:
                sent = sender.send_messages(
                    messages,
                    delay_ms,
                    lambda index, total, length: self.gui_callback_queue.put(
                        lambda index=index, total=total, length=length: progress(index, total, length)
                    ),
                )
            except Exception as exc:
                self.gui_callback_queue.put(
                    lambda exc=exc: self.finish_send_with_error(label, exc, error_callback)
                )
            else:
                self.gui_callback_queue.put(
                    lambda sent=sent: self.finish_send_success(label, sent, len(messages), success_callback)
                )

        threading.Thread(target=worker, name=f"{label}-worker", daemon=True).start()

    def finish_send_success(self, label: str, sent: int, total: int, success_callback=None) -> None:
        self.append_log(log_line(f"{label}: sent {sent}/{total} message(s)."))
        if success_callback is not None:
            success_callback(sent, total)
        self.current_sender = None

    def finish_send_with_error(self, label: str, exc: Exception, error_callback=None) -> None:
        self.last_error = str(exc)
        self.logger.error("%s failed: %s", label, exc, exc_info=exc)
        if label.startswith("Send "):
            self.append_log(log_line(f"Send failed: {exc}"))
        else:
            self.append_log(log_line(f"{label} failed: {exc}"))
        if error_callback is not None:
            error_callback(exc)
        self.current_sender = None
        self.flash_rx("error")
        messagebox.showerror(label, str(exc))

    def load_presets(self) -> None:
        path = filedialog.askopenfilename(
            title="Open single preset or SysEx file",
            filetypes=[("Korg / SysEx files", "*.syx *.mnlgxdprog"), ("All files", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        validation = validate_import_path(source_path)
        if validation.status not in {COMPATIBLE, PROBABLY_COMPATIBLE}:
            messagebox.showwarning("Import blocked", f"{validation.status}: {validation.message}")
            return
        if source_path.suffix.lower() == ".mnlgxdprog":
            try:
                program = load_mnlgxdprog(source_path)
                records = [self.program_to_record(program, 1)]
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                messagebox.showerror("Open failed", str(exc))
                return
        elif source_path.suffix.lower() == ".syx":
            programs = import_sysex_programs(source_path)
            records = [self.program_to_record(program, index + 1) for index, program in enumerate(programs)]
            if not records:
                records = read_sysex_file(source_path)
        else:
            records = read_sysex_file(source_path)
        self.preset_records.extend(records)
        self.loaded_source_path = path
        if hasattr(self, "preset_tree"):
            self.refresh_preset_tree()

    def open_preset_into_bank(self) -> None:
        path = filedialog.askopenfilename(
            title="Open preset or SysEx file into bank workspace",
            filetypes=[("Korg / SysEx files", "*.syx *.mnlgxdprog *.mnlgxdlib"), ("All files", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        validation = validate_import_path(source_path)
        if validation.status not in {COMPATIBLE, PROBABLY_COMPATIBLE}:
            messagebox.showwarning("Import blocked", f"{validation.status}: {validation.message}")
            return
        try:
            if source_path.suffix.lower() == ".mnlgxdprog":
                programs = [load_mnlgxdprog(source_path)]
            elif source_path.suffix.lower() == ".mnlgxdlib":
                programs = load_mnlgxdlib(source_path).programs
            elif source_path.suffix.lower() == ".syx":
                programs = import_sysex_programs(source_path)
            else:
                programs = []
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        if programs:
            start_index = self.ask_import_start_slot(len(programs))
            if start_index is None:
                return
            if start_index + len(programs) > len(self.bank.slots):
                messagebox.showwarning(
                    "Import too long",
                    f"{len(programs)} program(s) do not fit starting at slot {start_index + 1:03d}.",
                )
                return
            if not self.confirm_program_import_preview(programs, start_index, source_path):
                return
            self.bank.remember()
            for offset, program in enumerate(programs):
                index = start_index + offset
                slot = self.bank.slots[index]
                raw = self.program_to_record(program, index + 1).raw
                slot.name = program.name
                slot.source = path
                slot.raw = raw
                slot.prog_bin = program.prog_bin
                slot.sha256 = self.bank.hash_raw(program.prog_bin)
                slot.status = STATUS_IMPORTED
                slot.notes = "Decoded minilogue xd program data."
            self.bank.mark_duplicates()
            self.mark_dirty(
                f"Imported {len(programs)} decoded program(s) into bank workspace starting at slot {start_index + 1:03d}"
            )
            self.refresh_bank_tree()
            return

        records = read_sysex_file(source_path)
        start_index = self.ask_import_start_slot(len(records))
        if start_index is None:
            return
        if start_index + len(records) > len(self.bank.slots):
            messagebox.showwarning(
                "Import too long",
                f"{len(records)} SysEx record(s) do not fit starting at slot {start_index + 1:03d}.",
            )
            return
        self.bank.remember()
        for offset, record in enumerate(records):
            index = start_index + offset
            slot = self.bank.slots[index]
            slot.name = f"Program {index + 1:03d}"
            slot.source = path
            slot.raw = record.raw
            slot.prog_bin = b""
            slot.sha256 = record.sha256
            slot.status = STATUS_IMPORTED
            slot.notes = "Loaded as preset into offline bank workspace."
        self.bank.mark_duplicates()
        self.mark_dirty(f"Imported {len(records)} raw record(s) into bank workspace starting at slot {start_index + 1:03d}")
        self.refresh_bank_tree()

    def ask_import_start_slot(self, import_count: int) -> int | None:
        selected = self.selected_bank_indices() if hasattr(self, "bank_tree") else []
        first_empty = next((i for i, slot in enumerate(self.bank.slots) if not slot.raw and not slot.prog_bin), 0)
        default = selected[0] + 1 if selected else first_empty + 1
        value = simpledialog.askinteger(
            "Target slot",
            f"Import {import_count} program(s) starting at slot:",
            initialvalue=default,
            minvalue=1,
            maxvalue=len(self.bank.slots),
        )
        return None if value is None else value - 1

    def confirm_program_import_preview(self, programs: list[object], start_index: int, source_path: Path) -> bool:
        lines = [
            f"Source: {source_path.name}",
            f"Programs: {len(programs)}",
            "",
            "Target | Current -> Import",
        ]
        for offset, program in enumerate(programs[:20]):
            index = start_index + offset
            current = self.bank.slots[index].name or "Empty"
            incoming = getattr(program, "name", "") or "name unknown"
            lines.append(f"{index + 1:03d} | {current} -> {incoming}")
        if len(programs) > 20:
            lines.append(f"... {len(programs) - 20} more")
        lines.append("")
        lines.append("This imports into the editor only. Nothing is sent to the XD.")
        return messagebox.askyesno("Confirm import", "\n".join(lines))

    def refresh_preset_tree(self) -> None:
        query = self.preset_search_var.get().lower() if hasattr(self, "preset_search_var") else ""
        self.preset_tree.delete(*self.preset_tree.get_children())
        for index, record in enumerate(self.preset_records):
            name = f"Program {record.index:03d}"
            if query and query not in name.lower() and query not in record.dump_type.lower():
                continue
            self.preset_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(record.index, name, record.dump_type, record.length, record.short_hash, self.loaded_source_path),
            )

    def selected_preset_records(self) -> list[SysexRecord]:
        indices = []
        for item in self.preset_tree.selection():
            try:
                indices.append(int(item))
            except ValueError:
                pass
        return [self.preset_records[index] for index in indices if 0 <= index < len(self.preset_records)]

    def export_selected_preset(self) -> None:
        records = self.selected_preset_records()
        if not records:
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx", filetypes=[("SysEx", "*.syx")])
        if path:
            Path(path).write_bytes(records_to_bytes(records))

    def duplicate_selected_preset(self) -> None:
        records = self.selected_preset_records()
        for record in records:
            self.preset_records.append(
                SysexRecord(
                    index=len(self.preset_records) + 1,
                    raw=record.raw,
                    length=record.length,
                    manufacturer_id=record.manufacturer_id,
                    is_korg=record.is_korg,
                    dump_type=record.dump_type,
                    sha256=record.sha256,
                    notes="Duplicated in preset workspace.",
                )
            )
        self.refresh_preset_tree()

    def rename_selected_preset(self) -> None:
        messagebox.showinfo("Display rename", "Preset name decoding is not verified yet; rename is kept as a bank display override after loading into a bank.")

    def delete_selected_preset(self) -> None:
        indices = {
            int(item)
            for item in self.preset_tree.selection()
            if item.isdigit()
        }
        self.preset_records = [
            record for index, record in enumerate(self.preset_records) if index not in indices
        ]
        self.refresh_preset_tree()

    def send_selected_preset(self) -> None:
        self.send_records(self.selected_preset_records(), "selected preset")

    def open_bank(self) -> None:
        path = filedialog.askopenfilename(
            title="Open bank/library/raw file",
            filetypes=[("Korg / SysEx files", "*.syx *.mnlgxdlib *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        if source_path.suffix.lower() == ".txt":
            self.load_pocket_dump_into_bank(source_path)
            return
        validation = validate_import_path(source_path)
        if validation.status not in {COMPATIBLE, PROBABLY_COMPATIBLE}:
            messagebox.showwarning("Import blocked", f"{validation.status}: {validation.message}")
            return
        if source_path.suffix.lower() == ".mnlgxdlib":
            try:
                library = load_mnlgxdlib(source_path)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                messagebox.showerror("Open failed", str(exc))
                return
            self.bank.load_programs(library.programs, path, "mnlgxdlib")
            self.current_bank_path = source_path
            self.clear_dirty_state()
            self.change_log.clear()
            self.refresh_bank_tree()
            self.append_log(log_line(f"Loaded {len(library.programs)} decoded program(s) from {path}"))
            return
        if source_path.suffix.lower() == ".syx":
            programs = import_sysex_programs(source_path)
            if programs:
                self.bank.load_programs(programs, path, "syx")
                self.current_bank_path = source_path
                self.clear_dirty_state()
                self.change_log.clear()
                self.refresh_bank_tree()
                self.append_log(log_line(f"Loaded {len(programs)} decoded SysEx program dump(s) from {path}"))
                return
        records = read_sysex_file(source_path)
        self.bank.load_records(records, path)
        self.current_bank_path = source_path
        self.clear_dirty_state()
        self.change_log.clear()
        self.refresh_bank_tree()

    def open_pocket_midi_dump(self) -> None:
        path = filedialog.askopenfilename(
            title="Import Pocket MIDI dump",
            filetypes=[
                ("Pocket MIDI / SysEx", "*.txt *.syx"),
                ("Pocket MIDI text", "*.txt"),
                ("SysEx", "*.syx"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.load_pocket_dump_into_bank(Path(path))

    def load_pocket_dump_into_bank(self, source_path: Path) -> None:
        try:
            analysis = analyze_sysex_file(source_path)
            validation = analysis.validate_bank()
            programs = import_sysex_programs_from_bytes(analysis.bank_only_bytes())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Pocket MIDI import failed", str(exc))
            return
        counts = analysis.command_counts
        if not analysis.bank_programs:
            messagebox.showwarning("No bank dumps", "No 0x4C program bank dumps were found.")
            return
        if not programs:
            messagebox.showwarning("Decode failed", "0x4C program dumps were found, but no programs could be decoded.")
            return
        self.loaded_records = build_records(analysis.all_sysex_bytes())
        self.loaded_source_path = str(source_path)
        self.analyzer_status_var.set(self.pocket_analysis_text(source_path, analysis, validation))
        self.bank.load_programs(programs, str(source_path), "pocket-midi")
        self.current_bank_path = None
        self.clear_dirty_state()
        self.change_log.clear()
        self.refresh_bank_tree()
        self.append_log(
            log_line(
                "Pocket MIDI import: "
                f"total={len(analysis.messages)}, 0x40={counts[0x40]}, 0x4C={counts[0x4C]}, "
                f"0x44={counts[0x44]}, 0x45={counts[0x45]}, 0x51={counts[0x51]}, "
                f"bank={len({message.slot_index for message in analysis.bank_programs if message.slot_index is not None})}/500, "
                f"complete={'yes' if validation.complete else 'no'}"
            )
        )

    def pocket_analysis_text(self, source_path: Path, analysis, validation) -> str:
        counts = analysis.command_counts
        unique_slots = len({message.slot_index for message in analysis.bank_programs if message.slot_index is not None})
        lines = [
            f"File: {source_path}",
            f"SysEx messages total: {len(analysis.messages)}",
            f"0x40 current program: {counts[0x40]}",
            f"0x4C program dumps: {counts[0x4C]}",
            f"0x44 bank index: {counts[0x44]}",
            f"0x45 sequencer index: {counts[0x45]}",
            f"0x51 global data: {counts[0x51]}",
            f"unknown: {counts[None]}",
            f"Bank completeness: {unique_slots}/500",
            f"Bank complete: {'yes' if validation.complete else 'no'}",
        ]
        if validation.missing_slots:
            missing = ", ".join(f"{slot + 1:03d}" for slot in validation.missing_slots[:25])
            lines.append(f"Missing slots: {missing}")
        if validation.duplicate_slots:
            duplicate = ", ".join(f"{slot + 1:03d}" for slot in validation.duplicate_slots[:25])
            lines.append(f"Duplicate slots: {duplicate}")
        if validation.invalid_lengths:
            invalid = ", ".join(f"{slot + 1:03d}" for slot in validation.invalid_lengths[:25])
            lines.append(f"Invalid 0x4C lengths: {invalid}")
        return "\n".join(lines)

    def refresh_bank_tree(self) -> None:
        if not hasattr(self, "bank_tree"):
            return
        self.bank_tree.delete(*self.bank_tree.get_children())
        visible_indices = [
            index for index, slot in enumerate(self.bank.slots) if self.bank_slot_matches_filter(index, slot)
        ]
        if self.bank_sort_column:
            visible_indices.sort(
                key=lambda index: self.bank_sort_value(index, self.bank_sort_column or "slot"),
                reverse=self.bank_sort_reverse,
            )
        for index in visible_indices:
            slot = self.bank.slots[index]
            self.bank_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    map_slot(index).display_number_text,
                    slot.name or "Empty",
                    slot.source,
                    slot.status or "empty",
                ),
            )
        self.bank_count_var.set(f"{len(visible_indices)} / {len(self.bank.slots)} shown")

    def bank_slot_matches_filter(self, index: int, slot) -> bool:
        query = self.bank_search_var.get().strip().lower() if hasattr(self, "bank_search_var") else ""
        if not query:
            return True
        slot_mapping = map_slot(index)
        searchable = " ".join(
            [
                slot_mapping.display_number_text,
                slot.name or "",
                slot.source or "",
                slot.status or "",
                slot.notes or "",
            ]
        ).lower()
        return query in searchable

    def bank_sort_value(self, index: int, column: str):
        slot = self.bank.slots[index]
        values = {
            "slot": index + 1,
            "name": (slot.name or "").casefold(),
            "source": (slot.source or "").casefold(),
            "status": (slot.status or "").casefold(),
        }
        return values.get(column, index)

    def clear_bank_search(self) -> None:
        self.bank_search_var.set("")
        self.refresh_bank_tree()

    def selected_bank_indices(self) -> list[int]:
        indices = []
        for item in self.bank_tree.selection():
            index = self.parse_bank_iid(item)
            if index is not None:
                indices.append(index)
        return indices

    def parse_bank_iid(self, item: str) -> int | None:
        try:
            index = int(item)
        except (TypeError, ValueError):
            return None
        if not 0 <= index < len(self.bank.slots):
            return None
        return index

    def save_bank(self) -> None:
        if self.current_bank_path is None:
            self.save_bank_as()
            return
        if self.current_bank_path.suffix.lower() not in {".mnlgxdlib", ".syx"}:
            self.save_bank_as()
            return
        self.save_bank_to_path(self.current_bank_path)

    def save_bank_as(self) -> None:
        if not any(slot.raw or slot.prog_bin for slot in self.bank.slots):
            messagebox.showinfo("Empty bank", "No raw bank data is loaded.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".mnlgxdlib",
            filetypes=[
                ("minilogue xd Library", "*.mnlgxdlib"),
                ("SysEx", "*.syx"),
            ],
        )
        if path:
            self.save_bank_to_path(Path(path))

    def save_bank_copy(self) -> None:
        self.save_bank_as()

    def save_bank_to_path(self, target: Path) -> None:
        if not any(slot.raw or slot.prog_bin for slot in self.bank.slots):
            messagebox.showinfo("Empty bank", "No raw bank data is loaded.")
            return
        if self.ask_overwrite_files_var.get() and target.exists() and not messagebox.askokcancel(
            "Overwrite existing bank file?",
            f"Overwrite existing bank file?\n\n{target}",
        ):
            return
        programs = self.bank.export_programs()
        if target.suffix.lower() == ".mnlgxdlib":
            if len(programs) != 500:
                messagebox.showwarning(
                    "Incomplete library",
                    f"A .mnlgxdlib export needs 500 decoded programs; found {len(programs)}.",
                )
                return
            save_mnlgxdlib(XDLibrary(programs=programs), target)
        else:
            raw = b"".join(self.bank.raw_for_slot(index) for index in range(len(self.bank.slots)) if self.bank.raw_for_slot(index))
            if not raw:
                messagebox.showinfo("Empty bank", "No raw SysEx data is available to export.")
                return
            target.write_bytes(raw)
        self.current_bank_path = target
        self.clear_dirty_state()
        self.append_log(log_line(f"Saved bank/export: {target}"))

    def export_bank_as_sysex(self) -> None:
        if not any(slot.raw or slot.prog_bin for slot in self.bank.slots):
            messagebox.showinfo("Empty bank", "No raw bank data is loaded.")
            return
        path = filedialog.asksaveasfilename(
            title="Export Bank as SysEx",
            defaultextension=".syx",
            filetypes=[("SysEx", "*.syx")],
        )
        if path:
            self.save_bank_to_path(Path(path))

    def export_selected_bank_slots(self) -> None:
        indices = self.selected_bank_indices()
        data = self.bank.export_selected_bytes(indices)
        if not data:
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx", filetypes=[("SysEx", "*.syx")])
        if path:
            Path(path).write_bytes(data)
            self.append_log(log_line(f"Exported selected bank slot(s): {path}"))

    def send_selected_bank_slots(self) -> None:
        indices = [i for i in self.selected_bank_indices() if self.bank.raw_for_slot(i)]
        invalid_headers = []
        for index in indices:
            raw = self.bank.raw_for_slot(index)
            if not self.is_slot_header(raw, index):
                invalid_headers.append(index)
            else:
                slot = self.bank.slots[index]
                self.append_log(
                    log_line(
                        "Preparing send: "
                        f"GUI slot={map_slot(index).bank_slot_text} index={index} "
                        f"Model patch name={slot.name or 'Empty'} "
                        f"Raw header={format_hex(raw[6:10])} Bytes={len(raw)}"
                    )
                )
        if invalid_headers:
            messagebox.showerror(
                "Invalid slot header",
                "Cannot send slot(s) with invalid minilogue xd 0x4C headers: "
                + ", ".join(map_slot(index).bank_slot_text for index in invalid_headers[:10]),
            )
            return
        records = [
            SysexRecord(i + 1, raw, len(raw), None, False, "bank-slot", self.bank.slots[i].sha256)
            for i in indices
            for raw in [self.bank.raw_for_slot(i)]
        ]
        self.pending_write_ack_indices = list(indices)
        started = self.send_records(
            records,
            "selected bank slots",
            success_callback=lambda _sent, _total, indices=indices: self.finish_bank_slot_send(indices),
            error_callback=lambda exc, indices=indices: self.fail_bank_slot_send(indices, exc),
        )
        if not started:
            self.pending_write_ack_indices = []

    @staticmethod
    def is_slot_header(raw: bytes, slot_index: int) -> bool:
        return (
            len(raw) > 9
            and raw[0] == 0xF0
            and raw[6] == 0x4C
            and raw[7] == (slot_index & 0x7F)
            and raw[8] == ((slot_index >> 7) & 0x7F)
            and raw[9] == 0x00
            and raw[-1] == 0xF7
        )

    def finish_bank_slot_send(self, indices: list[int]) -> None:
        if not self.wait_for_ack_var.get():
            self.bank.mark_sent(indices)
            self.pending_write_ack_indices = []
            self.refresh_bank_tree()
            self.append_log(log_line(f"Send completed for {len(indices)} slot(s); ACK wait disabled."))
            return
        self.append_log(log_line(f"Waiting for 0x23 ACK for {len(indices)} sent slot(s)."))

    def fail_bank_slot_send(self, indices: list[int], exc: Exception) -> None:
        self.pending_write_ack_indices = []
        self.bank.mark_error(indices, str(exc))
        self.refresh_bank_tree()

    def rename_bank_slot(self, _event: tk.Event | None = None):
        indices = self.selected_bank_indices()
        if not indices:
            return
        name = simpledialog.askstring(
            "Rename program",
            "New program name:",
            initialvalue=self.bank.slots[indices[0]].name,
        )
        if name is not None:
            old_name = self.bank.slots[indices[0]].name
            self.bank.rename(indices[0], name)
            self.mark_dirty(f'Renamed {map_slot(indices[0]).bank_slot_text}: "{old_name}" -> "{name}"')
            self.refresh_bank_tree()
        return "break" if _event is not None else None

    def copy_bank_slot(self, _event: tk.Event | None = None):
        indices = self.selected_bank_indices()
        if indices:
            count = self.bank.copy_indices(indices)
            self.append_log(log_line(f"Copied {count} slot(s)."))
        return "break" if _event is not None else None

    def cut_bank_slot(self, _event: tk.Event | None = None):
        indices = self.selected_bank_indices()
        if not indices:
            return "break" if _event is not None else None
        self.bank.copy_indices(indices)
        if not self.bank.clear_slots(indices):
            messagebox.showwarning("Init template missing", "INIT template missing. Cannot clear slot safely.")
            return "break" if _event is not None else None
        self.mark_dirty("Cut " + ", ".join(map_slot(index).display_number_text for index in indices[:10]))
        self.refresh_bank_tree()
        return "break" if _event is not None else None

    def duplicate_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices:
            return
        self.bank.copy(indices[0])
        empty_indices = [i for i, slot in enumerate(self.bank.slots) if not slot.raw]
        if empty_indices:
            self.bank.paste(empty_indices[0])
            self.mark_dirty(f'Duplicated {map_slot(indices[0]).bank_slot_text} into {map_slot(empty_indices[0]).bank_slot_text}')
            self.refresh_bank_tree()

    def paste_bank_slot(self, _event: tk.Event | None = None):
        indices = self.selected_bank_indices()
        if not indices:
            return "break" if _event is not None else None
        target_index = indices[0]
        count = len(self.bank.clipboard)
        if not count:
            return "break" if _event is not None else None
        if target_index + count > len(self.bank.slots):
            messagebox.showwarning("Paste too long", f"{count} preset(s) do not fit starting at slot {target_index + 1:03d}.")
            return "break" if _event is not None else None
        target_range = range(target_index, target_index + count)
        occupied = [index for index in target_range if self.bank.slots[index].raw or self.bank.slots[index].prog_bin]
        if occupied and not messagebox.askyesno(
            "Overwrite slots",
            f"Overwrite {len(occupied)} occupied slot(s) starting at {target_index + 1:03d}?",
        ):
            return "break" if _event is not None else None
        pasted = self.bank.paste_many(target_index)
        if pasted:
            self.mark_dirty(f'Pasted {pasted} slot(s) into {map_slot(target_index).bank_slot_text}')
            self.refresh_bank_tree()
        return "break" if _event is not None else None

    def insert_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices or not self.bank.clipboard:
            return
        target_index = indices[0]
        count = len(self.bank.clipboard)
        if not self.bank.can_insert(target_index, count):
            messagebox.showwarning(
                "Not enough room",
                f"Not enough free/Init slots at end to insert {count} preset(s) without losing data.",
            )
            return
        inserted = self.bank.insert_many(target_index)
        if inserted:
            self.mark_dirty(f"Inserted {inserted} preset(s) at {map_slot(target_index).bank_slot_text}")
            self.refresh_bank_tree()

    def move_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices:
            return
        target = simpledialog.askinteger("Move to slot", "Target slot 1-500:", minvalue=1, maxvalue=500)
        if target:
            self.bank.move(indices[0], target - 1)
            self.mark_dirty(f'Moved {map_slot(indices[0]).bank_slot_text} -> {map_slot(target - 1).bank_slot_text}')
            self.refresh_bank_tree()

    def swap_bank_slots(self) -> None:
        indices = self.selected_bank_indices()
        if len(indices) == 2:
            self.bank.swap(indices[0], indices[1])
            self.mark_dirty(f'Swapped {map_slot(indices[0]).bank_slot_text} <-> {map_slot(indices[1]).bank_slot_text}')
            self.refresh_bank_tree()

    def clear_bank_slot(self, _event: tk.Event | None = None):
        cleared = self.selected_bank_indices()
        occupied = [index for index in cleared if self.bank.slots[index].raw or self.bank.slots[index].prog_bin or self.bank.slots[index].name]
        if occupied and not messagebox.askyesno(
            "Clear selected slot(s)",
            f"Clear {len(occupied)} occupied slot(s) in the local workspace?",
        ):
            return "break" if _event is not None else None
        if not self.bank.clear_slots(cleared):
            messagebox.showwarning("Init template missing", "INIT template missing. Cannot clear slot safely.")
            return "break" if _event is not None else None
        if cleared:
            self.mark_dirty("Cleared " + ", ".join(map_slot(index).bank_slot_text for index in cleared[:10]))
        self.refresh_bank_tree()
        return "break" if _event is not None else None

    def select_all_bank_slots(self, _event: tk.Event | None = None):
        self.bank_tree.selection_set(self.bank_tree.get_children())
        return "break"

    def create_init_program_slot(self) -> None:
        messagebox.showinfo(
            "Init program template required",
            "Create Init Program needs a verified init template from an imported bank. "
            "Use Clear / Init to empty the local workspace slot for now.",
        )

    def save_selected_as_mnlgxdprog(self) -> None:
        indices = self.selected_bank_indices()
        if len(indices) != 1:
            messagebox.showinfo("Select one program", "Select exactly one decoded program.")
            return
        slot = self.bank.slots[indices[0]]
        programs = self.bank.export_programs(indices)
        if not programs:
            messagebox.showinfo("No decoded program", "The selected slot has no decoded minilogue xd program data.")
            return
        default_stem = safe_filename(slot.name.strip(), fallback=f"Slot_{indices[0] + 1:03d}")
        default_name = default_stem + ".mnlgxdprog"
        path = filedialog.asksaveasfilename(
            title="Save as minilogue xd Program",
            initialfile=default_name,
            defaultextension=".mnlgxdprog",
            filetypes=[("minilogue xd Program", "*.mnlgxdprog")],
        )
        if path:
            save_mnlgxdprog(programs[0], Path(path))
            self.append_log(log_line(f"Saved single program: {path}"))

    def save_selected_as_sysex(self) -> None:
        indices = self.selected_bank_indices()
        data = self.bank.export_selected_bytes(indices)
        if not data:
            messagebox.showinfo("No SysEx data", "The selected slot has no sendable SysEx data.")
            return
        initialfile = self.default_sysex_filename(indices)
        path = filedialog.asksaveasfilename(
            title="Save selected as SysEx",
            initialfile=initialfile,
            defaultextension=".syx",
            filetypes=[("SysEx", "*.syx")],
        )
        if path:
            Path(path).write_bytes(data)
            self.append_log(log_line(f"Saved selected SysEx: {path}"))

    def default_sysex_filename(self, indices: list[int]) -> str:
        valid = sorted(index for index in indices if 0 <= index < len(self.bank.slots))
        if not valid:
            return "Selected_Presets.syx"
        if len(valid) == 1:
            index = valid[0]
            name = safe_filename(self.bank.slots[index].name or "Preset", fallback="Preset")
            return f"A{index + 1:03d}_{name}.syx"
        return f"A{valid[0] + 1:03d}-A{valid[-1] + 1:03d}_Selected_Presets.syx"

    def sort_bank(self, reverse: bool) -> None:
        self.bank.sort_by_name(reverse)
        self.mark_dirty("Sorted bank Z-A" if reverse else "Sorted bank A-Z")
        self.refresh_bank_tree()

    def undo_bank(self) -> None:
        self.bank.undo()
        self.mark_dirty("Undo bank operation")
        self.refresh_bank_tree()

    def undo_bank_key(self, event: tk.Event | None = None):
        widget_class = event.widget.winfo_class() if event is not None else ""
        if widget_class in {"Entry", "TEntry", "Text", "TCombobox", "Spinbox"}:
            return None
        self.undo_bank()
        return "break"

    def on_bank_drag_start(self, event: tk.Event) -> None:
        item = self.bank_tree.identify_row(event.y)
        index = self.parse_bank_iid(item)
        if index is not None:
            self.bank_drag_start_index = index
            self.bank_tree.configure(cursor="fleur")
        else:
            self.bank_drag_start_index = None

    def on_bank_drag_release(self, event: tk.Event) -> None:
        self.bank_tree.configure(cursor="")
        if self.bank_drag_start_index is None:
            return
        item = self.bank_tree.identify_row(event.y)
        target = self.parse_bank_iid(item)
        if target is not None:
            if target != self.bank_drag_start_index:
                source = self.bank_drag_start_index
                self.bank.move(source, target)
                self.mark_dirty(f"Moved {map_slot(source).bank_slot_text} -> {map_slot(target).bank_slot_text} by drag")
                self.refresh_bank_tree()
                self.append_log(
                    log_line(
                        f"Moved bank slot {source + 1} to {target + 1} by drag."
                    )
                )
        self.bank_drag_start_index = None

    def on_bank_double_click(self, event: tk.Event) -> None:
        if not self.double_click_send_var.get():
            return
        region = self.bank_tree.identify_region(event.x, event.y)
        item = self.bank_tree.identify_row(event.y)
        if region != "cell" or self.parse_bank_iid(item) is None:
            return
        self.bank_tree.selection_set(item)
        self.send_selected_bank_slots()

    @staticmethod
    def program_to_record(program, index: int) -> SysexRecord:
        raw = encode_program_dump(program, index - 1)
        return SysexRecord(
            index=index,
            raw=raw,
            length=len(raw),
            manufacturer_id=0x42,
            is_korg=True,
            dump_type=program.source_type or "program-dump",
            sha256=OfflineBank.hash_raw(program.prog_bin),
            notes=program.name,
        )

    def save_capture_backup(self) -> None:
        data = self.sysex_buffer.to_bytes()
        if not data:
            messagebox.showinfo("No capture", "Receive or load SysEx data first.")
            return
        backup_dir = user_data_dir() / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        syx_path = backup_dir / f"backup_{stamp}.syx"
        manifest_path = backup_dir / f"backup_{stamp}.json"
        zip_path = backup_dir / f"backup_{stamp}.zip"
        records = build_records(data)
        syx_path.write_bytes(data)
        manifest = report_dict(str(syx_path), records)
        manifest["notes"] = simpledialog.askstring("Backup note", "Optional note:") or ""
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(syx_path, syx_path.name)
            archive.write(manifest_path, manifest_path.name)
        self.append_log(log_line(f"Created backup bundle: {zip_path}"))

    def refresh_user_units_trees(self) -> None:
        units = scan_user_units(user_units_dir())
        units_by_filename = {unit.path.name: unit for unit in units}
        if hasattr(self, "user_osc_tree"):
            self.user_osc_tree.delete(*self.user_osc_tree.get_children())
            for slot in USER_OSC_SLOTS:
                self.insert_user_unit_row(self.user_osc_tree, slot, units_by_filename, include_source=True)
        for prefix, tree in getattr(self, "user_fx_trees", {}).items():
            tree.delete(*tree.get_children())
            for slot in (slot for slot in USER_FX_SLOTS if slot.key.startswith(prefix)):
                self.insert_user_unit_row(tree, slot, units_by_filename, include_source=False)
        self.user_osc_status_var.set(
            "User OSC local slots 1-16. Read from XD is not implemented because User Units "
            "do not use the normal Program Dump workflow."
        )
        self.user_fx_status_var.set(
            "User FX local slots: Mod FX 1-16, Delay FX 1-8, Reverb FX 1-8. "
            "Send/read hardware actions stay disabled until the logue transfer protocol is verified."
        )

    def insert_user_unit_row(self, tree: ttk.Treeview, slot, units_by_filename: dict[str, object], *, include_source: bool) -> None:
        assignment = self.user_unit_assignments.get(slot.key)
        unit = units_by_filename.get(assignment.filename) if assignment else None
        if assignment and unit is None:
            values = (
                slot.label,
                assignment.display_name or assignment.filename,
                "",
                "unknown compatibility",
                "local assignment missing file",
                assignment.filename,
                "File is not in the local user-unit library folder.",
            )
        elif unit is None:
            values = (slot.label, "Empty", "", "", "empty", "", "")
        else:
            display_name = assignment.display_name if assignment and assignment.display_name else unit.name
            values = (
                slot.label,
                display_name,
                unit.module,
                unit.compatibility,
                "local assignment; hardware status unknown",
                unit.path.name,
                unit.notes or f"{unit.size} bytes | {unit.short_hash}",
            )
        tree.insert("", tk.END, iid=slot.key, values=values if include_source else values[:5])

    def import_user_units(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Import User OSC / User FX files",
            filetypes=[("User unit files", "*.mnlgxdunit *.logueunit *.prlgunit *.zip *.bin *.wav"), ("All files", "*.*")],
        )
        warnings = []
        for path in paths:
            try:
                unit = import_user_unit(Path(path), user_units_dir())
                slot_key = first_available_slot_key(unit, self.user_unit_assignments)
                slot_note = "not assigned"
                if slot_key:
                    self.user_unit_assignments[slot_key] = UserUnitAssignment(filename=unit.path.name)
                    save_user_unit_assignments(self.user_unit_assignment_path, self.user_unit_assignments)
                    slot_note = USER_UNIT_SLOTS_BY_KEY[slot_key].label
                elif unit.module not in {"osc", "modfx", "delfx", "revfx"}:
                    warnings.append(f"{unit.path.name}: unsupported or unknown unit type")
                else:
                    warnings.append(f"{unit.path.name}: no compatible empty local slot")
                self.append_log(
                    log_line(
                        f"Imported user unit: {unit.path.name} | {unit.kind} | "
                        f"{unit.compatibility} | {unit.status} | {slot_note}"
                    )
                )
                if unit.status in {"invalid container/header", "parser error"}:
                    warnings.append(f"{unit.path.name}: {unit.status} - {unit.notes}")
            except Exception as exc:
                self.append_log(log_line(f"Could not import user unit {path}: {exc}"))
                warnings.append(f"{Path(path).name}: {exc}")
        self.refresh_user_units_trees()
        if warnings:
            messagebox.showwarning("User unit import", "\n".join(warnings))

    def remove_selected_user_units(self) -> None:
        selected = self.selected_user_unit_slot_keys()
        selected_files = self.selected_user_unit_file_names()
        if not selected and not selected_files:
            return
        assigned = [key for key in selected if key in self.user_unit_assignments]
        if selected_files:
            if not messagebox.askyesno(
                "Remove local files",
                "Remove selected unassigned user-unit file(s) from the local library folder? "
                "This does not touch the synth.",
            ):
                return
            for filename in selected_files:
                path = user_units_dir() / filename
                try:
                    if path.is_file():
                        path.unlink()
                        self.append_log(log_line(f"Removed local user-unit file: {filename}"))
                except OSError as exc:
                    self.append_log(log_line(f"Could not remove {filename}: {exc}"))
            self.refresh_user_units_trees()
            return
        if not messagebox.askyesno(
            "Clear local assignment",
            "Clear selected local user-unit slot assignment(s)? This does not touch the synth or delete files.",
        ):
            return
        for key in assigned:
            assignment = self.user_unit_assignments.pop(key)
            self.append_log(log_line(f"Cleared local user-unit slot {key}: {assignment.filename}"))
        save_user_unit_assignments(self.user_unit_assignment_path, self.user_unit_assignments)
        self.refresh_user_units_trees()

    def selected_user_unit_slot_keys(self) -> list[str]:
        selected = []
        for tree in self.iter_user_unit_trees():
            for item in tree.selection():
                if item in USER_UNIT_SLOTS_BY_KEY:
                    selected.append(item)
        return selected

    def selected_user_unit_file_names(self) -> list[str]:
        selected = []
        for tree in self.iter_user_unit_trees():
            for item in tree.selection():
                if item.startswith("file:"):
                    selected.append(item.removeprefix("file:"))
        return selected

    def iter_user_unit_trees(self):
        if hasattr(self, "user_osc_tree"):
            yield self.user_osc_tree
        for tree in getattr(self, "user_fx_trees", {}).values():
            yield tree

    def selected_user_unit_path(self) -> Path | None:
        selected_files = self.selected_user_unit_file_names()
        if selected_files:
            path = user_units_dir() / selected_files[0]
            if path.is_file():
                return path
        for key in self.selected_user_unit_slot_keys():
            assignment = self.user_unit_assignments.get(key)
            if assignment:
                path = user_units_dir() / assignment.filename
                if path.is_file():
                    return path
        return None

    def rename_selected_user_unit_assignment(self) -> None:
        selected = self.selected_user_unit_slot_keys()
        if not selected:
            return
        key = selected[0]
        assignment = self.user_unit_assignments.get(key)
        if not assignment:
            messagebox.showinfo("No assignment", "Select an assigned local user-unit slot first.")
            return
        default_name = assignment.display_name or Path(assignment.filename).stem
        name = simpledialog.askstring("Rename local display", "Display name:", initialvalue=default_name)
        if name is None:
            return
        assignment.display_name = name.strip()
        save_user_unit_assignments(self.user_unit_assignment_path, self.user_unit_assignments)
        self.refresh_user_units_trees()

    def move_selected_user_unit_assignment(self) -> None:
        selected = self.selected_user_unit_slot_keys()
        selected_files = self.selected_user_unit_file_names()
        if not selected and not selected_files:
            return
        source_key = selected[0] if selected else ""
        assignment = (
            self.user_unit_assignments.get(source_key)
            if source_key
            else UserUnitAssignment(filename=selected_files[0])
        )
        if assignment is None:
            messagebox.showinfo("No assignment", "Select an assigned local user-unit slot first.")
            return
        unit = next(
            (item for item in scan_user_units(user_units_dir()) if item.path.name == assignment.filename),
            None,
        )
        if unit is None:
            messagebox.showwarning("Missing file", "The assigned user-unit file is no longer in the local library.")
            return
        choices = matching_slots(unit.module)
        prompt = "Target slot key:\n\n" + "\n".join(f"{slot.key}  {slot.label}" for slot in choices)
        target_key = simpledialog.askstring("Move local assignment", prompt, initialvalue=source_key)
        if not target_key:
            return
        target_key = target_key.strip().lower()
        valid_keys = {slot.key for slot in choices}
        if target_key not in valid_keys:
            messagebox.showwarning("Invalid slot", "Choose a compatible slot key from the list.")
            return
        self.user_unit_assignments[target_key] = assignment
        if target_key != source_key:
            self.user_unit_assignments.pop(source_key, None)
        save_user_unit_assignments(self.user_unit_assignment_path, self.user_unit_assignments)
        self.refresh_user_units_trees()

    def user_unit_send_not_implemented(self) -> None:
        messagebox.showinfo(
            "Not implemented yet",
            "Read/write for User OSC / User FX is not implemented.\n\n"
            "The minilogue xd does not expose User Unit slot contents through the normal Program Dump workflow. "
            "Use local .mnlgxdunit files and local slot assignments for now.",
        )

    def save_user_unit_assignments_as(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save local User Unit assignments",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            save_user_unit_assignments(Path(path), self.user_unit_assignments)
            self.append_log(log_line(f"Saved local user-unit assignments: {path}"))
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))

    def load_user_unit_assignments_from_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load local User Unit assignments",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self.user_unit_assignments = load_user_unit_assignments(Path(path))
        save_user_unit_assignments(self.user_unit_assignment_path, self.user_unit_assignments)
        self.append_log(log_line(f"Loaded local user-unit assignments: {path}"))
        self.refresh_user_units_trees()

    def export_user_units_manifest(self) -> None:
        messagebox.showinfo(
            "Manifest export removed",
            "User OSC / FX now uses slot-based inventory. Manifest export is no longer part of the normal workflow.",
        )

    def view_selected_user_unit_manifest(self) -> None:
        """Show the manifest or basic metadata for the selected user unit."""
        path = self.selected_user_unit_path()
        if path is None:
            messagebox.showinfo("No user unit selected", "Select a User OSC or User FX file first.")
            return
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                manifest_name = next(
                    (name for name in names if name.endswith("manifest.json")),
                    None,
                )
                if manifest_name:
                    content = archive.read(manifest_name).decode("utf-8", errors="replace")
                else:
                    content = "No manifest.json found.\n\nArchive contents:\n" + "\n".join(sorted(names))
        except zipfile.BadZipFile:
            try:
                content = (
                    f"File: {path.name}\n"
                    f"Size: {path.stat().st_size} bytes\n"
                    "This file is not a ZIP-based .mnlgxdunit archive."
                )
            except OSError as exc:
                messagebox.showerror("Manifest view failed", str(exc))
                return
        except OSError as exc:
            messagebox.showerror("Manifest view failed", str(exc))
            return
        self.show_text_dialog(f"Manifest - {path.name}", content)

    def show_about(self) -> None:
        messagebox.showinfo(
            "About minilogue xd Librarian",
            f"minilogue xd Librarian v{_APP_VERSION}\n\n"
            "Purpose:\n"
            "Local librarian, SysEx, backup and diagnostic tool for Korg minilogue xd.\n\n"
            "Supported formats:\n"
            ".mnlgxdprog\n"
            ".mnlgxdlib\n"
            ".syx\n"
            ".mnlgxdunit\n\n"
            "Not an official Korg product.",
        )

    def open_log_folder(self) -> None:
        """Open the folder containing the application log."""
        folder = log_path().parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            self.last_error = str(exc)
            self.logger.exception("Could not open log folder.")
            messagebox.showerror(
                "Could not open log folder",
                f"Could not open log folder:\n{folder}\n\n{exc}",
            )

    def copy_diagnostic_report(self) -> None:
        report = self.build_diagnostic_report()
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self.append_log(log_line("Diagnostic report copied to clipboard."))
        messagebox.showinfo("Diagnostic Report", "Diagnostic report copied to clipboard.")

    def build_diagnostic_report(self) -> str:
        try:
            input_ports = get_input_ports()
        except Exception as exc:
            input_ports = [f"<error: {exc}>"]
        try:
            output_ports = get_output_ports()
        except Exception as exc:
            output_ports = [f"<error: {exc}>"]
        return "\n".join(
            [
                "minilogue xd Librarian Diagnostic Report",
                f"Version: {_APP_VERSION}",
                f"OS: {platform.platform()}",
                f"Python: {platform.python_version()}",
                f"Executable: {sys.executable}",
                f"Capture backend: {self.native_capture_status.status_text}",
                "Send backend: Open MIDI OUT via mido/WinMM",
                f"App data path: {user_data_dir()}",
                f"Log file: {log_path()}",
                f"Log level: {logging.getLevelName(logging.getLogger().getEffectiveLevel())}",
                "Available MIDI IN ports:",
                *(f"  - {port}" for port in input_ports),
                "Available MIDI OUT ports:",
                *(f"  - {port}" for port in output_ports),
                f"Selected MIDI IN: {self.selected_input_port() or 'none'}",
                f"Selected MIDI OUT: {self.selected_output_port() or 'none'}",
                f"Last loaded bank: {self.loaded_source_path or 'unknown'}",
                f"Unsaved changes: {'yes' if self.dirty else 'no'}",
                f"Last error: {self.last_error or 'none'}",
            ]
        )

    def midi_connection_test(self) -> None:
        """Start a non-destructive MIDI connection test using the existing listener."""
        self.start_receive_mode("test")

    def start_manual_bank_capture(self) -> None:
        self.start_native_capture("bank", "Capture Bank Dump from XD")

    def start_manual_sysex_capture(self) -> None:
        self.start_native_capture("native_capture", "Receive SysEx")

    def start_native_capture(self, mode: str, label: str) -> None:
        input_name = self.selected_input_port()
        if not input_name:
            messagebox.showwarning("No MIDI IN", "Select a MIDI IN port first.")
            return
        self.native_capture_status = detect_engine3_native_runtime()
        if not self.native_capture_status.available:
            messagebox.showerror("Native capture helper missing", self.native_capture_status.status_text)
            self.listen_status_var.set(self.native_capture_status.status_text)
            self.append_log(log_line(self.native_capture_status.status_text))
            return
        if self.native_capture_worker is not None and self.native_capture_worker.is_running:
            messagebox.showwarning("Capture running", "A bank capture is already running.")
            return
        if self.receiver.is_open:
            self.receiver.close_ports()
            self.append_log(log_line("Closed mido MIDI ports before native capture."))
        self.receive_mode = mode
        self.receive_mode_var.set(label)
        self.capture_state = "capturing"
        self.capture_program_slots.clear()
        self.capture_command_counts.clear()
        self.expected_cmd = None
        self.expected_slot = None
        self.listen_active = True
        self.listen_started_at = time.time()
        self.listen_saw_midi = False
        self.listen_saw_clock = False
        self.listen_saw_sysex = False
        self.sysex_buffer.clear()
        while True:
            try:
                self.native_capture_queue.get_nowait()
            except Empty:
                break
        self.native_capture_worker = Engine3SysexCaptureWorker(
            input_name,
            self.native_capture_queue,
            inactivity_ms=max(self.read_int(self.inactivity_ms_var.get(), 500), 5000),
            no_data_timeout_s=max(self.read_int(self.max_timeout_s_var.get(), 10), 60),
        )
        self.native_capture_worker.start()
        if mode == "bank":
            self.listen_status_var.set("Start Full/All Dump on the minilogue xd now.")
            self.append_log(log_line("Capture Bank from XD: native dump listener started. No data was sent."))
        else:
            self.listen_status_var.set("Start SysEx transmission on the device now.")
            self.append_log(log_line("Receive SysEx: native dump listener started. No data was sent."))

    def start_receive_mode(self, mode: str) -> None:
        if mode == "bank":
            self.start_manual_bank_capture()
            return
        labels = {
            "single": "Receive Single Program",
            "current_program": "Receive Current Program",
            "slot_program": "Receive Slot Program",
            "bank": "Receive Full Bank / All Programs",
            "full_bank_sequential": "Receive Full Bank Sequential",
            "raw": "Raw SysEx Capture",
            "native_capture": "Raw SysEx Capture",
            "test": "MIDI Connection Test",
        }
        self.receive_mode = mode
        self.receive_mode_var.set(labels.get(mode, mode))
        self.sysex_buffer.clear()
        self.listen_for_sysex()
        if mode == "bank":
            self.append_log(
                log_line(
                    "Receive mode: Full Bank / All Programs. Waiting for captured 0x4C program dumps."
                )
            )
        elif mode == "full_bank_sequential":
            self.append_log(
                log_line("Receive mode: Full Bank Sequential. Sending one 0x1C slot request at a time.")
            )
        elif mode == "current_program":
            self.append_log(log_line("Receive mode: Current Program. Waiting for 0x40 response."))
        elif mode == "slot_program":
            self.append_log(log_line("Receive mode: Slot Program. Waiting for 0x4C response."))
        elif mode == "single":
            self.append_log(log_line("Receive mode: Single Program. Waiting for one program SysEx dump."))
        elif mode == "test":
            self.append_log(log_line("MIDI Connection Test: waiting for non-destructive incoming SysEx."))
        else:
            self.append_log(log_line("Receive mode: Raw SysEx Capture."))

    def request_current_from_xd(self) -> None:
        if not self.ensure_receive_request_ports():
            return
        self.expected_cmd = 0x40
        self.expected_slot = None
        self.start_receive_mode("current_program")
        raw = request_current_program()
        self.append_log(log_line(f"TX Request Current: {format_hex(raw)}"))
        self.send_request_sysex(raw, "Request Current")

    def request_selected_slot_from_xd(self) -> None:
        if not self.ensure_receive_request_ports():
            return
        indices = self.selected_bank_indices()
        slot_index = indices[0] if indices else simpledialog.askinteger(
            "Request slot",
            "Slot 001-500:",
            minvalue=1,
            maxvalue=500,
        )
        if slot_index is None:
            return
        if isinstance(slot_index, int) and slot_index >= 1 and not indices:
            slot_index -= 1
        self.expected_cmd = 0x4C
        self.expected_slot = slot_index
        self.start_receive_mode("slot_program")
        raw = request_program_slot(slot_index)
        self.append_log(log_line(f"TX Request Slot {slot_index + 1:03d}: {format_hex(raw)}"))
        self.send_request_sysex(raw, f"Request Slot {slot_index + 1:03d}")

    def request_full_bank_from_xd(self) -> None:
        if not self.ensure_receive_request_ports():
            return
        if self.current_sender is not None:
            messagebox.showwarning("Busy", "A send operation is already in progress.")
            return
        if not messagebox.askyesno(
            "Request full bank sequentially",
            "Request all 500 program slots one by one?\n\n"
            "This does not use 0x0E. Hardware tests show 0x0E returns 0x51 global data, not programs.\n\n"
            "The app sends one 0x1C slot request, waits for 0x4C or timeout, then continues.",
        ):
            return
        self.expected_cmd = 0x4C
        self.expected_slot = None
        self.start_receive_mode("full_bank_sequential")
        self.start_full_bank_sequential_worker()

    def start_full_bank_sequential_worker(self) -> None:
        sender = self.receiver.make_sender()
        self.current_sender = sender
        timeout_s = self.read_int(self.max_timeout_s_var.get(), 10)
        delay_ms = self.read_int(self.send_delay_var.get(), 80)

        def drain_responses() -> None:
            while True:
                try:
                    self.program_response_queue.get_nowait()
                except Empty:
                    return

        def gui_log(message: str) -> None:
            self.gui_callback_queue.put(lambda message=message: self.append_log(log_line(message)))

        def gui_progress(message: str) -> None:
            self.gui_callback_queue.put(lambda message=message: self.listen_status_var.set(message))

        def worker() -> None:
            received = 0
            timeouts = 0
            try:
                for slot_index in range(500):
                    if sender.cancel_requested:
                        gui_log("Full Bank sequential request cancelled.")
                        break
                    drain_responses()
                    self.expected_slot = slot_index
                    raw = request_program_slot(slot_index)
                    gui_log(f"TX FullBank slot {slot_index + 1:03d}: {format_hex(raw)}")
                    sender.send_messages([raw], 0)
                    deadline = time.time() + timeout_s
                    response_slot = None
                    while time.time() < deadline and not sender.cancel_requested:
                        try:
                            response_slot = self.program_response_queue.get(timeout=0.05)
                            break
                        except Empty:
                            pass
                    if response_slot is None:
                        timeouts += 1
                        gui_log(f"Timeout waiting for 0x4C slot {slot_index + 1:03d}; continuing.")
                    else:
                        received += 1
                        gui_log(
                            f"RX 0x4C for requested slot {slot_index + 1:03d}; stored slot {response_slot + 1:03d}."
                        )
                    gui_progress(
                        f"Full Bank sequential: {slot_index + 1}/500 requested, received={received}, timeouts={timeouts}"
                    )
                    if delay_ms > 0 and slot_index < 499:
                        time.sleep(delay_ms / 1000)
            except Exception as exc:
                self.gui_callback_queue.put(
                    lambda exc=exc: self.finish_send_with_error("Request Full Bank sequential", exc)
                )
                return
            self.gui_callback_queue.put(
                lambda received=received, timeouts=timeouts: self.finish_full_bank_sequential(received, timeouts)
            )

        threading.Thread(target=worker, name="full-bank-sequential-worker", daemon=True).start()

    def finish_full_bank_sequential(self, received: int, timeouts: int) -> None:
        self.append_log(
            log_line(f"Full Bank sequential finished: received={received}, timeouts={timeouts}.")
        )
        self.listen_status_var.set(
            f"Full Bank sequential finished: received={received}, timeouts={timeouts}."
        )
        self.current_sender = None
        self.expected_cmd = None
        self.expected_slot = None
        self.listen_active = False

    def ensure_receive_request_ports(self) -> bool:
        if not self.selected_input_port():
            messagebox.showwarning("No MIDI IN", "Select a MIDI IN port first.")
            return False
        if not self.selected_output_port():
            messagebox.showwarning("No MIDI OUT", "Select a MIDI OUT port first.")
            return False
        if not self.receiver.is_open:
            self.open_ports()
        return bool(self.receiver.is_open and self.engine3_output_ready())

    def send_request_sysex(self, raw: bytes, label: str) -> None:
        self.send_request_sysex_batch([raw], label)

    def send_request_sysex_batch(self, messages: list[bytes], label: str) -> None:
        if self.current_sender is not None:
            messagebox.showwarning("Busy", "A send operation is already in progress.")
            return
        if not self.engine3_output_ready():
            messagebox.showwarning("No MIDI OUT", "Select a MIDI OUT port first.")
            return
        self.start_send_worker(
            messages,
            self.read_int(self.send_delay_var.get(), 80),
            label,
            lambda index, total, length: self.listen_status_var.set(
                f"{label}: sent {index}/{total} request(s)"
            ),
        )

    def send_selected_to_buffer(self) -> None:
        if self.current_sender is not None:
            messagebox.showwarning("Busy", "A send operation is already in progress.")
            return
        indices = [index for index in self.selected_bank_indices() if self.bank.raw_for_slot(index)]
        if len(indices) != 1:
            messagebox.showinfo("Select one program", "Select exactly one program to send to the edit buffer.")
            return
        if not self.engine3_output_ready():
            messagebox.showwarning("No MIDI OUT", "Select a MIDI OUT port first.")
            return
        index = indices[0]
        slot = self.bank.slots[index]
        try:
            raw = self.current_buffer_raw_for_slot(index)
        except ValueError as exc:
            messagebox.showwarning("Cannot send to buffer", str(exc))
            return
        if self.confirm_before_send_var.get() and not messagebox.askyesno(
            "Send to edit buffer?",
            "Send selected program to the XD edit buffer?\n\n"
            "This changes the current sound but does not overwrite a stored XD slot.",
        ):
            return
        self.append_log(
            log_line(
                "Preparing buffer send: "
                f"source slot={map_slot(index).bank_slot_text} "
                f"program={slot.name or 'Empty'} header={format_hex(raw[6:8])} Bytes={len(raw)}"
            )
        )
        self.start_send_worker_with_callbacks(
            [raw],
            self.read_int(self.send_delay_var.get(), 80),
            "Send selected to edit buffer",
            lambda sent, total, length: self.append_log(
                log_line(f"Sent edit buffer SysEx {sent:03d}/{total:03d} ({length} bytes)")
            ),
            success_callback=lambda _sent, _total: self.listen_status_var.set(
                f"Sent {slot.name or map_slot(index).bank_slot_text} to edit buffer"
            ),
        )

    def current_buffer_raw_for_slot(self, slot_index: int) -> bytes:
        slot = self.bank.slots[slot_index]
        if slot.prog_bin:
            return encode_current_program_dump(self.bank.export_programs([slot_index])[0])
        raw = self.bank.raw_for_slot(slot_index)
        if not raw:
            raise ValueError("The selected slot has no sendable program data.")
        if not self.is_slot_header(raw, slot_index):
            raise ValueError("The selected slot is not a valid 0x4C program dump.")
        try:
            program = decode_program_dump(raw)
        except ValueError as exc:
            raise ValueError(f"The selected 0x4C dump cannot be decoded: {exc}") from exc
        return encode_current_program_dump(program)

    def write_bank_to_xd(self) -> None:
        if not messagebox.askyesno(
            "Backup recommended",
            "It is recommended to create a full backup before overwriting the minilogue xd.\n\n"
            "Continue to send all populated bank slots without creating a backup now?",
        ):
            return
        indices = [index for index, slot in enumerate(self.bank.slots) if slot.raw]
        if not indices:
            messagebox.showinfo("Nothing to send", "No sendable bank slots are loaded.")
            return
        self.bank_tree.selection_set([str(index) for index in indices])
        self.send_selected_bank_slots()

    def mark_dirty(self, description: str) -> None:
        self.dirty = True
        if description:
            self.change_log.append(description)
            self.append_log(log_line(description))
        self.update_window_title()

    def clear_dirty_state(self) -> None:
        self.dirty = False
        self.update_window_title()

    def update_window_title(self) -> None:
        marker = " *" if self.dirty else ""
        self.root.title(f"{self.app_title}{marker}")

    def show_change_log(self) -> None:
        if not self.change_log:
            messagebox.showinfo("Change Log", "No bank changes recorded in this session.")
            return
        self.show_text_dialog("Change Log", "\n".join(self.change_log))

    def show_text_dialog(self, title: str, content: str) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("720x480")
        dialog.transient(self.root)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        text_widget = scrolledtext.ScrolledText(dialog, wrap=tk.WORD, font=("Consolas", 10))
        text_widget.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        text_widget.insert("1.0", content)
        text_widget.configure(state=tk.DISABLED)
        ttk.Button(dialog, text="Close", command=dialog.destroy).grid(row=1, column=0, pady=(0, 8))


    def update_status(self) -> None:
        ports_open = "connected" if self.receiver.is_open else "not connected"
        self.status_var.set(
            f"MIDI: {ports_open} | Last action: {self.listen_status_var.get() or 'idle'}"
        )
        capture = self.sysex_buffer.capture
        capture_count = len(capture.messages) if capture else 0
        capture_bytes = capture.total_bytes if capture else 0
        capture_state = "idle" if capture is None else ("active" if capture.is_active else "finalized")
        finalized_by = "none" if capture is None else (capture.finalized_by or "none")
        manufacturer = (
            f"0x{self.last_sysex_info.manufacturer_id:02X}"
            if self.last_sysex_info.manufacturer_id is not None
            else "none"
        )
        korg = "disabled"
        if self.auto_detect_korg_var.get():
            korg = "yes" if self.last_sysex_info.is_korg else "no"
        self.sysex_summary_var.set(
            "Last SysEx summary\n"
            f"Starts with F0: {'yes' if self.last_sysex_info.starts_with_f0 else 'no'}\n"
            f"Ends with F7: {'yes' if self.last_sysex_info.ends_with_f7 else 'no'}\n"
            f"Manufacturer ID: {manufacturer}\n"
            f"Korg 0x42 detected: {korg}\n\n"
            "Current capture\n"
            f"Messages: {capture_count}\n"
            f"Bytes: {capture_bytes}\n"
            f"State: {capture_state}\n"
            f"Finalized by: {finalized_by}"
        )
        self.settings_status_var.set(
            f"Settings: {settings_path()} | Last successful IN: "
            f"{self.settings.get('last_successful_midi_in', 'none')} | OUT: "
            f"{self.settings.get('last_successful_midi_out', 'none')} | SysEx: "
            f"{self.settings.get('last_successful_sysex_received_at', 'never')}"
        )
        capture_backend = "native ready" if self.native_capture_status.available else "native missing"
        send_backend = "midi out selected" if self.selected_output_port() else "midi out missing"
        self.bottom_status_var.set(
            f"Capture backend: {capture_backend} | Send backend: {send_backend} | "
            f"MIDI: {ports_open} | IN: {self.selected_input_port() or 'none'} | "
            f"OUT: {self.selected_output_port() or 'none'} | "
            f"Last SysEx: {'yes' if self.total_sysex_messages else 'no'} | "
            f"Realtime hidden: {'yes' if self.hide_midi_clock_var.get() else 'no'} | "
            f"Capture: {capture_state}"
        )

    def save_successful_sysex_ports(self, timestamp: float) -> None:
        if self.selected_input_port():
            self.settings["last_successful_midi_in"] = self.selected_input_port()
        if self.selected_output_port():
            self.settings["last_successful_midi_out"] = self.selected_output_port()
        self.settings["last_successful_sysex_received_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        self.persist_settings()

    def _collect_settings(self) -> None:
        """Copy current GUI settings into the persisted settings dictionary."""
        self.settings["inactivity_ms"] = self.read_int(self.inactivity_ms_var.get(), 500)
        self.settings["max_timeout_s"] = self.read_int(self.max_timeout_s_var.get(), 10)
        self.settings["ack_timeout_s"] = self.read_int(self.ack_timeout_s_var.get(), 3)
        self.settings["send_delay_ms"] = self.read_int(self.send_delay_var.get(), 80)
        self.settings["show_sysex_only"] = self.show_sysex_only_var.get()
        self.settings["hide_midi_clock"] = self.hide_midi_clock_var.get()
        self.settings["show_realtime"] = self.show_realtime_var.get()
        self.settings["show_note_controller"] = self.show_note_controller_var.get()
        self.settings["auto_connect"] = self.auto_connect_var.get()
        self.settings["wait_for_ack"] = self.wait_for_ack_var.get()
        self.settings["confirm_before_send"] = self.confirm_before_send_var.get()
        self.settings["double_click_send"] = self.double_click_send_var.get()
        self.settings["ask_double_click_once"] = self.ask_double_click_once_var.get()
        self.settings["auto_audition"] = self.auto_audition_var.get()
        self.settings["ask_overwrite_files"] = self.ask_overwrite_files_var.get()
        self.settings["backup_before_overwrite"] = self.backup_before_overwrite_var.get()
        self.settings["sanitize_filenames"] = self.sanitize_filenames_var.get()
        self.settings["colorize_log"] = self.colorize_log_var.get()
        self.settings["debug_logging"] = self.debug_logging_var.get()
        self.settings["show_details"] = self.show_details_var.get()

    def save_settings_from_tab(self) -> None:
        self._collect_settings()
        self.settings["last_successful_midi_in"] = self.default_in_var.get()
        self.settings["last_successful_midi_out"] = self.default_out_var.get()
        self.persist_settings()
        self.update_status()

    def persist_settings(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.append_log(log_line(f"Could not save settings: {exc}"))

    def clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)
        self.append_log(log_line("Log cleared. Current capture is preserved."))

    def append_log(self, text: str) -> None:
        clean = text.rstrip()
        tag = self.log_tag_for(clean) if self.colorize_log_var.get() else None
        self.log_text.insert(tk.END, clean + "\n", tag)
        self.log_text.see(tk.END)
        try:
            append_to_file(log_path(), text)
        except OSError:
            pass

    @staticmethod
    def log_tag_for(text: str) -> str | None:
        lowered = text.lower()
        if "error" in lowered or "failed" in lowered or "timeout" in lowered:
            return "error"
        if "warning" in lowered or "blocked" in lowered:
            return "warning"
        if "ack" in lowered or " ok" in lowered or "completed" in lowered or "sent to xd" in lowered:
            return "ok"
        if "tx" in lowered or "sent sysex" in lowered or "preparing send" in lowered:
            return "tx"
        if "rx" in lowered or "received" in lowered:
            return "rx"
        if "debug" in lowered or "summary" in lowered or "settings:" in lowered:
            return "debug"
        return None

    def flash_rx(self, mode: str) -> None:
        if not hasattr(self, "rx_indicator"):
            return
        color = {"midi": "#2e7d32", "sysex": "#f9a825", "error": "#c62828"}.get(mode, "#2e7d32")
        self.rx_indicator.configure(bg=color)
        self.schedule_after(180, lambda: self.rx_indicator.configure(bg="#9e9e9e"))

    @staticmethod
    def read_int(value: str, default: int) -> int:
        try:
            return max(0, int(value))
        except ValueError:
            return default

    def on_close(self) -> None:
        """Close MIDI resources, persist settings and destroy the root window."""
        unsaved_items = []
        if self.dirty:
            unsaved_items.append("the current bank has unsaved changes")
        if self.sysex_buffer.to_bytes():
            unsaved_items.append("there is an unsaved SysEx capture")
        if unsaved_items:
            if not messagebox.askyesno(
                "Unsaved changes",
                "Unsaved data is present:\n\n"
                + "\n".join(f"- {item}" for item in unsaved_items)
                + "\n\nClose anyway?",
            ):
                return
        self._collect_settings()
        self.settings["last_midi_in"] = self.selected_input_port()
        self.settings["last_midi_out"] = self.selected_output_port()
        self.persist_settings()
        if self.native_capture_worker is not None and self.native_capture_worker.is_running:
            self.native_capture_worker.stop()
            self.native_capture_worker.wait_stopped(timeout=2.0)
        self.receiver.close_ports()
        self.root.destroy()

    def close(self) -> None:
        """Backward-compatible alias used by tests and older entry points."""
        self.on_close()
